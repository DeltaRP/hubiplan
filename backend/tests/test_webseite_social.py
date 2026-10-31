"""Social-Media-Beiträge der Webseite: Verbinden, Abruf, Abgleich, Schnittstelle.

Meta wird nie wirklich aufgerufen: ``_request`` und ``_download`` sind ersetzt.
Alle Konten, Beiträge und Bilder sind erfunden.
"""

import datetime
import io
import urllib.parse

import pytest
from django.core import mail
from django.test import Client
from django.utils import timezone
from PIL import Image

from core.tenancy import rls_bypass
from organizations.models import Department
from website import social
from website.models import SocialFeed, SocialPost, SocialPostImage, Website, WebsiteDomain

from .factories import give_role, make_user

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def private_root(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"
    settings.FRONTEND_URL = "https://hubiplan.example"


def jpeg(color="blue", exif=True) -> bytes:
    img = Image.new("RGB", (1200, 900), color)
    buf = io.BytesIO()
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "Kamerahersteller"
        img.save(buf, "JPEG", exif=ex)
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


class FakeMeta:
    """Nachgebildete Meta-Schnittstelle."""

    def __init__(self):
        self.calls = []
        self.media = []
        self.fb_posts = []
        self.pages = [{"id": "111", "name": "Verein A", "access_token": "SEITE-1"}]
        # Systemnutzer-Zugang („Unified Login“) und ihm zugewiesene Instagram-Konten
        self.assigned = [{"id": "17841", "username": "verein_a"}]
        self.suat_exchange_fails = True
        self.token_info = {}
        self.business_accounts = []
        self.valid = True
        self.error = None

    def request(self, method, url, params):
        self.calls.append((method, url, dict(params)))
        if self.error:
            raise self.error
        if url == "https://api.instagram.com/oauth/access_token":
            assert params["client_secret"] == "geheim123"
            return {"data": [{"access_token": "KURZ", "user_id": 42}]}
        if url == "https://graph.instagram.com/access_token":
            assert params["access_token"] == "KURZ"
            return {"access_token": "LANG-IG", "expires_in": 5184000}
        if url == "https://graph.instagram.com/refresh_access_token":
            return {"access_token": "LANG-IG-2", "expires_in": 5184000}
        if url.endswith("/me") and "instagram" in url:
            return {"user_id": "17841", "username": "verein_a"}
        if url.endswith("/me/media"):
            assert params["access_token"].startswith("LANG-IG")
            return {"data": self.media}
        if url.endswith("/oauth/access_token") and "facebook" in url:
            if "code" in params:
                return {"access_token": "SUAT" if params["code"].startswith("SUAT") else "FB-KURZ"}
            if params["fb_exchange_token"] == "SUAT" and self.suat_exchange_fails:
                raise social.MetaError("Invalid token type", code=100)
            return {"access_token": "FB-LANG", "expires_in": 5184000}
        if url.endswith("/me/assigned_instagram_accounts"):
            assert params["access_token"] == "SUAT"
            return {"data": self.assigned}
        if url.endswith("/me/accounts"):
            return {"data": self.pages}
        if url.endswith("/me/businesses"):
            return {"data": [{"id": "555"}] if self.business_accounts else []}
        if url.endswith("/555/owned_instagram_accounts"):
            return {"data": self.business_accounts}
        if url.endswith("/555/instagram_accounts"):
            raise social.MetaError("Unsupported get request", code=100)
        if url.endswith("/17841/media") or url.endswith("/17999/media"):
            assert params["access_token"] in ("SUAT", "SEITE-IG")
            return {"data": self.media}
        if url.endswith("/debug_token"):
            return {"data": {"is_valid": self.valid, **self.token_info}}
        if url.endswith("/17841") and params.get("fields") in ("username", "id,username"):
            return {"id": "17841", "username": "verein_a"}
        if url.endswith("/posts"):
            return {"data": self.fb_posts}
        raise AssertionError(url)

    def download(self, url):
        assert social.cdn_allowed(url), url
        return jpeg()


@pytest.fixture
def meta(monkeypatch):
    fake = FakeMeta()
    monkeypatch.setattr(social, "_request", fake.request)
    monkeypatch.setattr(social, "_download", fake.download)
    monkeypatch.setattr(social, "ASSIGN_DELAY", 0)
    return fake


@pytest.fixture
def setup(orgs):
    org = orgs["a"]
    org.enabled_modules = ["members", "website"]
    org.save()
    site = Website.objects.create(organization=org, public_key="schluessel-a", state="public")
    WebsiteDomain.objects.create(organization=org, website=site, hostname="www.verein-a.example")
    admin = make_user("webseite@example.org")
    give_role(admin, org, permissions=["website.manage"], name="Webseite")
    return {"org": org, "site": site, "admin": admin}


def url(org, rest=""):
    return f"/api/orgs/{org.pk}/website/social/{rest}"


def ig_media(n=1, **extra):
    base = {
        "id": f"m{n}",
        "caption": f"Schützenfest {n}\nSchön war's!\n\n#schuetzen #neuss",
        "media_type": "IMAGE",
        "media_url": f"https://scontent.cdninstagram.com/bild{n}.jpg?sig=x",
        "permalink": f"https://www.instagram.com/p/abc{n}/",
        "timestamp": f"2026-10-{10 + n:02d}T12:00:00+0000",
    }
    base.update(extra)
    return base


def connect(api, setup, kind="instagram", **extra):
    """Verbindet einen Kanal. Instagram standardmäßig über „Unified Login“ (Konfiguration)."""
    if kind == "instagram" and extra.get("via_facebook", True) and "config_id" not in extra:
        extra["config_id"] = "987654"
    c = api(setup["admin"])
    resp = c.post(
        url(setup["org"]),
        {"kind": kind, "app_id": "123456", "app_secret": "geheim123", **extra},
        "application/json",
    )
    assert resp.status_code == 201, resp.content
    feed_id = resp.json()["id"]
    start = c.post(url(setup["org"], f"{feed_id}/connect/")).json()["url"]
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(start).query)["state"][0]
    # Mit Konfiguration liefert Meta einen Systemnutzer-Zugang (in der Nachbildung am Code erkannt)
    code = "SUAT-CODE" if extra.get("config_id") else "CODE"
    resp = c.get(f"/api/website/social/callback/?code={code}%23_&state={state}")
    assert resp.status_code == 302, resp.content
    return c, feed_id, resp["Location"]


class TestVerbinden:
    def test_instagram_verbinden_und_abrufen(self, setup, api, meta):
        """Unified Login: Konfiguration, Systemnutzer-Zugang, zugewiesenes Konto."""
        meta.media = [ig_media(1), ig_media(2)]
        c, feed_id, location = connect(api, setup)
        assert location == "https://hubiplan.example/social-rueckkehr?verbunden=1"
        with rls_bypass():
            feed = SocialFeed.objects.get(pk=feed_id)
            assert feed.status == "ok" and feed.account_name == "verein_a"
            assert feed.account_id == "17841" and feed.config_id == "987654"
            # Geheimnis und Zugang verschlüsselt
            assert feed.app_secret.startswith("enc1:") and "geheim" not in feed.app_secret
            assert feed.access_token.startswith("enc1:") and social.token(feed) == "SUAT"
            assert feed.token_expires_at is None
            assert SocialPost.objects.filter(feed=feed).count() == 2
        data = c.get(url(setup["org"])).json()
        assert data["redirect_uri"] == "https://hubiplan.example/api/website/social/callback/"
        listed = data["feeds"][0]
        assert listed["has_secret"] is True and "app_secret" not in listed
        assert listed["post_count"] == 2 and listed["config_id"] == "987654"
        # Code ohne angehängtes „#_“ an Meta; Beiträge über graph.facebook.com
        exchange = next(c for c in meta.calls if c[1].endswith("oauth/access_token"))
        assert exchange[2]["code"] == "SUAT-CODE"
        assert any(
            u.endswith("/17841/media") and "graph.facebook.com" in u for _, u, _ in meta.calls
        )
        assert not any("instagram.com" in u for _, u, _ in meta.calls)

    def test_instagram_startadresse_mit_konfiguration(self, setup, api, meta):
        c = api(setup["admin"])
        feed_id = c.post(
            url(setup["org"]),
            {"kind": "instagram", "app_id": "1", "app_secret": "geheim123", "config_id": "555"},
            "application/json",
        ).json()["id"]
        start = c.post(url(setup["org"], f"{feed_id}/connect/")).json()["url"]
        parts = urllib.parse.urlsplit(start)
        query = urllib.parse.parse_qs(parts.query)
        assert parts.netloc == "www.facebook.com" and parts.path.endswith("/dialog/oauth")
        assert query["config_id"] == ["555"] and "scope" not in query
        # Konfigurations-ID nur Ziffern
        resp = c.put(url(setup["org"], f"{feed_id}/"), {"config_id": "12a"}, "application/json")
        assert resp.status_code == 400

    def test_instagram_ueber_facebook_seite(self, setup, api, meta):
        """Ohne Konfiguration: Profikonto hängt an einer Facebook-Seite, Seiten-Zugang."""
        meta.pages = [
            {"id": "111", "name": "Verein A", "access_token": "SEITE-1"},
            {
                "id": "222",
                "name": "Verein A Jugend",
                "access_token": "SEITE-IG",
                "instagram_business_account": {"id": "17999", "username": "verein_a_jugend"},
            },
        ]
        meta.media = [ig_media(1)]
        c, feed_id, _ = connect(api, setup, config_id="")
        with rls_bypass():
            feed = SocialFeed.objects.get(pk=feed_id)
            assert feed.status == "ok" and feed.account_id == "17999"
            assert feed.account_name == "verein_a_jugend" and social.token(feed) == "SEITE-IG"
            assert SocialPost.objects.filter(feed=feed).count() == 1
        long = [p for _, u, p in meta.calls if p.get("grant_type") == "fb_exchange_token"]
        assert long and long[0]["fb_exchange_token"] == "FB-KURZ"

    def test_instagram_ohne_profikonto(self, setup, api, meta):
        _, feed_id, location = connect(api, setup, config_id="")
        assert "fehler=" in location
        assert "Profikonto" in urllib.parse.unquote(location)

    def test_mehrere_zugewiesene_konten_auswahl(self, setup, api, meta):
        meta.assigned = [
            {"id": "17841", "username": "verein_a"},
            {"id": "17999", "username": "verein_a_jugend"},
        ]
        c, feed_id, _ = connect(api, setup)
        listed = c.get(url(setup["org"])).json()["feeds"][0]
        assert listed["status"] == "choose"
        assert [p["name"] for p in listed["pages"]] == ["verein_a", "verein_a_jugend"]
        assert "SUAT" not in str(listed)
        resp = c.post(url(setup["org"], f"{feed_id}/page/"), {"page": "17999"}, "application/json")
        assert resp.status_code == 200, resp.content
        with rls_bypass():
            feed = SocialFeed.objects.get(pk=feed_id)
            assert feed.account_id == "17999" and social.token(feed) == "SUAT"

    def test_konto_aus_freigabe_der_anmeldung(self, setup, api, meta):
        """Keine zugewiesenen Konten: Konto aus den freigegebenen Rechten (debug_token)."""
        meta.assigned = []
        meta.token_info = {
            "type": "USER",
            "granular_scopes": [{"scope": "instagram_basic", "target_ids": ["17841"]}],
        }
        meta.media = [ig_media(1)]
        c, feed_id, location = connect(api, setup)
        assert location.endswith("verbunden=1"), location
        with rls_bypass():
            feed = SocialFeed.objects.get(pk=feed_id)
            assert feed.account_id == "17841" and feed.account_name == "verein_a"
            assert SocialPost.objects.filter(feed=feed).count() == 1

    def test_kein_konto_meldung_mit_zugangsart(self, setup, api, meta):
        meta.assigned = []
        meta.token_info = {"type": "SYSTEM_USER", "scopes": ["instagram_basic"]}
        _, _, location = connect(api, setup)
        text = urllib.parse.unquote_plus(location)
        assert "Assets" in text and "Art SYSTEM_USER" in text and "instagram_basic" in text
        assert (
            "zugewiesen: 0 (4× gefragt)" in text and "Portfolios: 0" in text and "Seiten: 1" in text
        )
        assert "SUAT" not in text

    def test_zuweisung_kommt_verzoegert(self, setup, api, meta, monkeypatch):
        calls = {"n": 0}
        real = meta.request

        def later(method, url_, params):
            if url_.endswith("/me/assigned_instagram_accounts"):
                calls["n"] += 1
                if calls["n"] < 3:
                    return {"data": []}
            return real(method, url_, params)

        monkeypatch.setattr(social, "_request", later)
        meta.media = [ig_media(1)]
        _, feed_id, location = connect(api, setup)
        assert location.endswith("verbunden=1"), location
        assert calls["n"] == 3

    def test_konto_aus_dem_portfolio(self, setup, api, meta):
        meta.assigned = []
        meta.business_accounts = [{"id": "17841", "username": "verein_a"}]
        meta.media = [ig_media(1)]
        c, feed_id, location = connect(api, setup)
        assert location.endswith("verbunden=1"), location
        with rls_bypass():
            feed = SocialFeed.objects.get(pk=feed_id)
            assert feed.account_id == "17841" and social.token(feed) == "SUAT"

    def test_instagram_alter_weg(self, setup, api, meta):
        """Ältere Apps: Instagram-Login über instagram.com, Zugang läuft nach 60 Tagen ab."""
        meta.media = [ig_media(1), ig_media(2)]
        c, feed_id, location = connect(api, setup, via_facebook=False)
        assert location == "https://hubiplan.example/social-rueckkehr?verbunden=1"
        with rls_bypass():
            feed = SocialFeed.objects.get(pk=feed_id)
            assert feed.status == "ok" and feed.account_name == "verein_a"
            assert social.token(feed) == "LANG-IG"
            assert feed.token_expires_at > timezone.now() + datetime.timedelta(days=59)
            assert SocialPost.objects.filter(feed=feed).count() == 2
        exchange = next(c for c in meta.calls if c[1].endswith("oauth/access_token"))
        assert exchange[1] == "https://api.instagram.com/oauth/access_token"
        assert exchange[2]["code"] == "CODE"

    def test_rueckleitung_nur_fuer_starter(self, setup, api, meta):
        c = api(setup["admin"])
        feed_id = c.post(
            url(setup["org"]),
            {"kind": "instagram", "app_id": "1", "app_secret": "geheim123"},
            "application/json",
        ).json()["id"]
        start = c.post(url(setup["org"], f"{feed_id}/connect/")).json()["url"]
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(start).query)["state"][0]
        other = make_user("fremd@example.org")
        give_role(other, setup["org"], permissions=["website.manage"], name="Andere")
        resp = api(other).get(f"/api/website/social/callback/?code=C&state={state}")
        assert "fehler=" in resp["Location"]
        assert not any("access_token" in call[1] for call in meta.calls)
        # Abgelaufen
        with rls_bypass():
            SocialFeed.objects.filter(pk=feed_id).update(
                oauth_started_at=timezone.now() - datetime.timedelta(minutes=20)
            )
        resp = c.get(f"/api/website/social/callback/?code=C&state={state}")
        assert "fehler=" in resp["Location"]

    def test_ohne_geheimnis_kein_start(self, setup, api, meta):
        c = api(setup["admin"])
        feed_id = c.post(url(setup["org"]), {"kind": "instagram"}, "application/json").json()["id"]
        resp = c.post(url(setup["org"], f"{feed_id}/connect/"))
        assert resp.status_code == 400

    def test_inhalte_bearbeiten_darf_nicht_verbinden(self, setup, api, meta, orgs):
        editor = make_user("schrift@example.org")
        give_role(editor, orgs["a"], permissions=["website.content"], name="Schriftführer")
        resp = api(editor).post(url(orgs["a"]), {"kind": "instagram"}, "application/json")
        assert resp.status_code == 403

    def test_facebook_mehrere_seiten_auswahl(self, setup, api, meta):
        meta.pages = [
            {"id": "111", "name": "Verein A", "access_token": "SEITE-1"},
            {"id": "222", "name": "Andere Seite", "access_token": "SEITE-2"},
        ]
        meta.fb_posts = [
            {
                "id": "111_1",
                "message": "Unser Frühschoppen",
                "created_time": "2026-10-20T10:00:00+0000",
                "permalink_url": "https://www.facebook.com/111/posts/1",
                "attachments": {
                    "data": [
                        {
                            "type": "album",
                            "subattachments": {
                                "data": [
                                    {
                                        "type": "photo",
                                        "media": {"image": {"src": "https://x.fbcdn.net/1.jpg"}},
                                        "target": {"id": "p1"},
                                    },
                                    {
                                        "type": "photo",
                                        "media": {"image": {"src": "https://x.fbcdn.net/2.jpg"}},
                                        "target": {"id": "p2"},
                                    },
                                ]
                            },
                        }
                    ]
                },
            },
            {
                "id": "111_2",
                "message": "Geteilt",
                "parent_id": "999_1",
                "created_time": "2026-10-21T10:00:00+0000",
            },
            {
                "id": "111_3",
                "message": "Lest mal",
                "created_time": "2026-10-22T10:00:00+0000",
                "attachments": {
                    "data": [
                        {"type": "share", "media": {"image": {"src": "https://x.fbcdn.net/3.jpg"}}}
                    ]
                },
            },
        ]
        c, feed_id, _ = connect(api, setup, kind="facebook")
        data = c.get(url(setup["org"])).json()["feeds"][0]
        assert data["status"] == "choose"
        assert data["pages"] == [
            {"id": "111", "name": "Verein A"},
            {"id": "222", "name": "Andere Seite"},
        ]
        resp = c.post(url(setup["org"], f"{feed_id}/page/"), {"page": "111"}, "application/json")
        assert resp.json()["status"] == "ok" and resp.json()["account_name"] == "Verein A"
        with rls_bypass():
            feed = SocialFeed.objects.get(pk=feed_id)
            assert social.token(feed) == "SEITE-1" and feed.token_expires_at is None
            assert feed.pending_pages == ""
        c.post(url(setup["org"], f"{feed_id}/sync/"))
        with rls_bypass():
            posts = list(SocialPost.objects.filter(feed_id=feed_id))
            # Geteilte Beiträge und Links Dritter fehlen
            assert [p.external_id for p in posts] == ["111_1"]
            assert posts[0].media_type == "album" and posts[0].images.count() == 2


class TestAbruf:
    def test_bilder_neu_geschrieben_und_hashtags_weg(self, setup, api, meta):
        meta.media = [ig_media(1)]
        connect(api, setup)
        with rls_bypass():
            post = SocialPost.objects.get()
            assert post.text == "Schützenfest 1\nSchön war's!"
            image = post.images.get()
            img = Image.open(image.file.open("rb"))
            assert not img.getexif()

    def test_album_und_video(self, setup, api, meta):
        meta.media = [
            ig_media(
                1,
                media_type="CAROUSEL_ALBUM",
                media_url=None,
                children={
                    "data": [
                        {
                            "id": "c1",
                            "media_type": "IMAGE",
                            "media_url": "https://a.cdninstagram.com/c1.jpg",
                        },
                        {
                            "id": "c2",
                            "media_type": "VIDEO",
                            "media_url": "https://a.cdninstagram.com/c2.mp4",
                            "thumbnail_url": "https://a.cdninstagram.com/c2.jpg",
                        },
                    ]
                },
            ),
            ig_media(2, media_type="VIDEO", thumbnail_url="https://a.cdninstagram.com/v.jpg"),
        ]
        connect(api, setup)
        with rls_bypass():
            album = SocialPost.objects.get(external_id="m1")
            assert album.media_type == "album"
            assert [i.is_video for i in album.images.all()] == [False, True]
            video = SocialPost.objects.get(external_id="m2")
            assert video.media_type == "video" and video.images.get().is_video

    def test_fremde_bildadresse_wird_nicht_geladen(self, setup, api, meta):
        assert not social.cdn_allowed("https://evil.example/bild.jpg")
        assert not social.cdn_allowed("http://a.cdninstagram.com/bild.jpg")
        assert not social.cdn_allowed("https://cdninstagram.com.evil.example/x.jpg")
        assert social.cdn_allowed("https://scontent-dus1-1.cdninstagram.com/x.jpg")

    def test_geloeschte_beitraege_verschwinden(self, setup, api, meta):
        meta.media = [ig_media(1), ig_media(2), ig_media(3)]
        c, feed_id, _ = connect(api, setup)
        with rls_bypass():
            files = [i.file.path for i in SocialPostImage.objects.all()]
        meta.media = [ig_media(1), ig_media(3)]
        c.post(url(setup["org"], f"{feed_id}/sync/"))
        with rls_bypass():
            assert sorted(SocialPost.objects.values_list("external_id", flat=True)) == ["m1", "m3"]
        import os

        assert sum(os.path.exists(f) for f in files) == 2
        # Leere Antwort gilt als Aussetzer
        meta.media = []
        c.post(url(setup["org"], f"{feed_id}/sync/"))
        with rls_bypass():
            assert SocialPost.objects.count() == 2

    def test_hoechstens_n_beitraege(self, setup, api, meta):
        meta.media = [ig_media(i) for i in range(1, 6)]
        c, feed_id, _ = connect(api, setup)
        c.put(url(setup["org"], f"{feed_id}/"), {"max_posts": 2}, "application/json")
        c.post(url(setup["org"], f"{feed_id}/sync/"))
        with rls_bypass():
            assert sorted(SocialPost.objects.values_list("external_id", flat=True)) == ["m4", "m5"]

    def test_freigabe_modus(self, setup, api, meta):
        meta.media = [ig_media(1)]
        c, feed_id, _ = connect(api, setup)
        c.put(url(setup["org"], f"{feed_id}/"), {"mode": "approval"}, "application/json")
        meta.media = [ig_media(1), ig_media(2)]
        c.post(url(setup["org"], f"{feed_id}/sync/"))
        posts = {p["text"].split("\n")[0]: p for p in c.get(url(setup["org"], "posts/")).json()}
        assert posts["Schützenfest 2"]["state"] == "pending"
        assert posts["Schützenfest 1"]["state"] == "visible"
        pk = posts["Schützenfest 2"]["id"]
        resp = c.put(url(setup["org"], f"posts/{pk}/"), {"state": "visible"}, "application/json")
        assert resp.json()["state"] == "visible"

    def test_modus_wechsel_gibt_wartende_nicht_frei(self, setup, api, meta):
        # UX-Audit 31.10. N07: der Modus gilt nur für künftige Beiträge
        meta.media = []
        c, feed_id, _ = connect(api, setup)
        c.put(url(setup["org"], f"{feed_id}/"), {"mode": "approval"}, "application/json")
        meta.media = [ig_media(1), ig_media(2)]
        c.post(url(setup["org"], f"{feed_id}/sync/"))
        c.put(url(setup["org"], f"{feed_id}/"), {"mode": "auto"}, "application/json")
        states = {p["state"] for p in c.get(url(setup["org"], "posts/")).json()}
        assert states == {"pending"}
        resp = c.post(url(setup["org"], f"{feed_id}/publish-pending/"))
        assert resp.status_code == 200 and resp.json()["published"] == 2
        assert resp.json()["pending_count"] == 0
        states = {p["state"] for p in c.get(url(setup["org"], "posts/")).json()}
        assert states == {"visible"}

    def test_trennen_loescht_alles(self, setup, api, meta):
        meta.media = [ig_media(1)]
        c, feed_id, _ = connect(api, setup)
        data = c.delete(url(setup["org"], f"{feed_id}/connect/")).json()
        assert data["status"] == "new" and data["post_count"] == 0
        with rls_bypass():
            feed = SocialFeed.objects.get(pk=feed_id)
            assert feed.access_token == "" and SocialPostImage.objects.count() == 0


class TestZugang:
    def test_instagram_verlaengern(self, setup, api, meta):
        connect(api, setup, via_facebook=False)
        with rls_bypass():
            feed = SocialFeed.objects.get()
            SocialFeed.objects.filter(pk=feed.pk).update(
                token_refreshed_at=timezone.now() - datetime.timedelta(days=8)
            )
            feed.refresh_from_db()
            social.maintain_feed(feed)
            feed.refresh_from_db()
            assert social.token(feed) == "LANG-IG-2"

    def test_abgelehnter_zugang_meldet_sich_einmal(self, setup, api, meta):
        connect(api, setup)
        mail.outbox.clear()
        meta.error = social.MetaError("Session has expired", code=190)
        with rls_bypass():
            feed = SocialFeed.objects.get()
            social.sync_feed(feed)
            feed.refresh_from_db()
            assert feed.status == "expired"
            social.maintain_feed(feed)
        assert len(mail.outbox) == 1
        assert "neu verbinden" in mail.outbox[0].subject
        assert mail.outbox[0].to == ["webseite@example.org"]

    def test_facebook_ungueltig(self, setup, api, meta):
        c, feed_id, _ = connect(api, setup, kind="facebook")
        meta.valid = False
        with rls_bypass():
            feed = SocialFeed.objects.get(pk=feed_id)
            social.maintain_feed(feed)
            feed.refresh_from_db()
            assert feed.status == "expired"


class TestSchnittstelle:
    def test_beitraege_oeffentlich(self, setup, api, meta):
        meta.media = [ig_media(1), ig_media(2)]
        c, feed_id, _ = connect(api, setup)
        info = Client().get("/api/public/site/v1/schluessel-a/").json()
        assert info["posts"] == {"instagram": True, "facebook": False}
        data = Client().get("/api/public/site/v1/schluessel-a/posts/?art=instagram&anzahl=1").json()
        assert len(data["posts"]) == 1
        post = data["posts"][0]
        assert post["text"].startswith("Schützenfest 2") and post["kind"] == "instagram"
        assert post["permalink"] == "https://www.instagram.com/p/abc2/"
        # Bilder kommen von HUBIplan, nie von Meta
        assert "cdninstagram" not in str(data)
        image_url = post["images"][0]["url"].replace("http://testserver", "")
        resp = Client().get(image_url)
        assert resp.status_code == 200 and resp["Content-Type"] == "image/jpeg"
        # Ausgeblendet: weder Beitrag noch Bild
        own = c.get(url(setup["org"], "posts/")).json()
        pk = next(p["id"] for p in own if p["text"].startswith("Schützenfest 2"))
        c.put(url(setup["org"], f"posts/{pk}/"), {"state": "hidden"}, "application/json")
        data = Client().get("/api/public/site/v1/schluessel-a/posts/").json()
        assert [p["text"][:14] for p in data["posts"]] == ["Schützenfest 1"]
        assert Client().get(image_url).status_code == 404

    def test_link_abschaltbar_und_baustein_aus(self, setup, api, meta):
        meta.media = [ig_media(1)]
        c, feed_id, _ = connect(api, setup)
        c.put(url(setup["org"], f"{feed_id}/"), {"show_link": False}, "application/json")
        data = Client().get("/api/public/site/v1/schluessel-a/posts/").json()
        assert data["posts"][0]["permalink"] is None
        site = setup["site"]
        site.blocks = {**site.blocks, "posts": False}
        site.save()
        assert Client().get("/api/public/site/v1/schluessel-a/posts/").status_code == 404
        info = Client().get("/api/public/site/v1/schluessel-a/").json()
        assert info["posts"] == {"instagram": False, "facebook": False}

    def test_kanal_einer_untereinheit(self, setup, api, meta):
        unit = Department.objects.create(
            organization=setup["org"], parent=setup["org"], name="Jägerzug"
        )
        meta.media = [ig_media(1)]
        c = api(setup["admin"])
        resp = c.post(
            url(setup["org"]),
            {
                "kind": "instagram",
                "department": unit.pk,
                "app_id": "1",
                "app_secret": "geheim123",
                "config_id": "987654",
            },
            "application/json",
        )
        feed_id = resp.json()["id"]
        start = c.post(url(setup["org"], f"{feed_id}/connect/")).json()["url"]
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(start).query)["state"][0]
        c.get(f"/api/website/social/callback/?code=SUAT-C&state={state}")
        main = Client().get("/api/public/site/v1/schluessel-a/posts/").json()
        assert main["posts"] == []
        zug = Client().get("/api/public/site/v1/schluessel-a/posts/?einheit=jaegerzug").json()
        assert len(zug["posts"]) == 1
        detail = Client().get("/api/public/site/v1/schluessel-a/units/jaegerzug/").json()
        assert detail["posts"]["instagram"] is True

    def test_datenschutz_nennt_beitraege(self, setup, api, meta):
        connect(api, setup)
        from website.privacy import website_privacy

        with rls_bypass():
            text = website_privacy(Website.objects.get(pk=setup["site"].pk))
        assert "Beiträge aus unseren Kanälen bei Instagram" in text
        assert "keine Daten an Meta" in text
