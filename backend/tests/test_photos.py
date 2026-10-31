"""Mitgliederfotos: Upload durch den Vorstand, Upload-Link für Mitglieder, Datenschutz."""

import datetime
import io
import re

import pytest
from django.core import mail
from django.core.cache import cache
from PIL import Image

from access.models import Role
from audit.models import AuditEntry
from members.models import MemberPhoto, Membership, PhotoUploadLink
from members.photo_models import hash_token
from members.workflows import purge_expired

from .factories import give_role, make_user
from .test_m2_members import admit, make_types

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"
    settings.CELERY_TASK_ALWAYS_EAGER = True


@pytest.fixture
def types(orgs):
    return {key: make_types(orgs[key]) for key in ("a", "b")}


@pytest.fixture
def member(api, orgs, types, board_a):
    return admit(api(board_a), orgs["a"], types["a"]["aktiv"]).json()


def image_file(fmt="JPEG", size=(2000, 1500), name="bild.jpg", exif_gps=True, orientation=None):
    img = Image.new("RGB", size, "red")
    img.paste(Image.new("RGB", (size[0] // 2, size[1]), "blue"), (0, 0))  # links blau
    buf = io.BytesIO()
    kwargs = {}
    if fmt == "JPEG":
        exif = Image.Exif()
        exif[0x010F] = "Kamera Testhersteller"  # Make
        if orientation:
            exif[0x0112] = orientation
        if exif_gps:
            exif[0x8825] = {1: "N", 2: (52.0, 31.0, 0.0)}  # GPS
        kwargs["exif"] = exif
    img.save(buf, fmt, **kwargs)
    buf.seek(0)
    buf.name = name
    return buf


def url(orgs, member, suffix=""):
    return f"/api/orgs/{orgs['a'].pk}/members/{member['id']}/photo/{suffix}"


def fetch_image(client, path) -> Image.Image:
    resp = client.get(path)
    assert resp.status_code == 200, resp
    return Image.open(io.BytesIO(b"".join(resp.streaming_content)))


class TestSeitenverhaeltnis:
    @pytest.mark.parametrize(
        ("size", "expected"),
        [
            ((1600, 1200), (900, 1200)),  # quer -> 3:4, mittig
            ((900, 1200), (900, 1200)),  # schon 3:4
            ((1000, 1000), (1000, 1000)),  # quadratisch bleibt
            ((600, 1600), (600, 800)),  # sehr hoch -> 3:4
        ],
    )
    def test_nur_3_4_oder_quadratisch(self, size, expected):
        from members.photos import enforce_aspect

        assert enforce_aspect(Image.new("RGB", size)).size == expected

    def test_mittiger_zuschnitt(self):
        from members.photos import enforce_aspect

        img = Image.new("RGB", (1600, 1200), "red")
        img.paste(Image.new("RGB", (300, 1200), "blue"), (0, 0))  # Rand links (schmaler als 350 px)
        cropped = enforce_aspect(img)
        assert cropped.getpixel((0, 600)) == (255, 0, 0)  # Rand abgeschnitten
        assert cropped.getpixel((cropped.width // 2, 600)) == (255, 0, 0)


class TestVorstand:
    def test_hochladen_braucht_einwilligung(self, api, orgs, member, board_a):
        resp = api(board_a).post(url(orgs, member), {"file": image_file()})
        assert resp.status_code == 400
        assert "consent" in resp.json()

    def test_hochladen_verkleinert_und_entfernt_metadaten(self, api, orgs, member, board_a):
        c = api(board_a)
        resp = c.post(url(orgs, member), {"file": image_file(), "consent": "true"})
        assert resp.status_code == 200, resp.json()
        data = resp.json()
        assert data["photo_consent_at"] == datetime.date.today().isoformat()
        photo = data["photo"]["approved"]
        full = fetch_image(c, photo["url"])
        assert full.size == (900, 1200)  # Querformat wird mittig auf 3:4 zugeschnitten
        assert not full.getexif()  # keine EXIF-/GPS-Daten mehr
        thumb = fetch_image(c, photo["thumbnail_url"])
        assert max(thumb.size) == 160
        detail = c.get(f"/api/orgs/{orgs['a'].pk}/members/{member['id']}/").json()
        assert detail["photo"]["approved"]["source"] == "board"
        rows = c.get(f"/api/orgs/{orgs['a'].pk}/members/").json()["results"]
        version = photo["url"].split("v=")[1]
        assert rows[0]["photo_url"].endswith(f"size=thumb&v={version}")
        assert AuditEntry.objects.filter(changes__has_key="Foto").exists()

    def test_exif_ausrichtung_wird_angewendet(self, api, orgs, member, board_a):
        c = api(board_a)
        # Orientation 6 = um 90° gedreht aufgenommen: Ergebnis steht hochkant
        c.post(url(orgs, member), {"file": image_file(orientation=6), "consent": "true"})
        img = fetch_image(c, url(orgs, member, "?size=full"))
        assert img.height > img.width

    def test_drehen_ersetzen_loeschen(
        self, api, orgs, member, board_a, settings, django_capture_on_commit_callbacks
    ):
        c = api(board_a)
        c.post(url(orgs, member), {"file": image_file(), "consent": "true"})
        assert fetch_image(c, url(orgs, member)).size == (900, 1200)
        # Alte Dateien werden erst nach dem Commit gelöscht
        with django_capture_on_commit_callbacks(execute=True):
            c.post(url(orgs, member, "rotate/"), {"direction": "left"}, content_type=JSON)
        assert fetch_image(c, url(orgs, member)).size == (1200, 900)
        with django_capture_on_commit_callbacks(execute=True):
            c.post(
                url(orgs, member), {"file": image_file(fmt="PNG", name="b.png", size=(400, 400))}
            )
        assert MemberPhoto.objects.count() == 1
        photo = MemberPhoto.objects.get()
        files = [photo.image.path, photo.thumbnail.path]
        with django_capture_on_commit_callbacks(execute=True):
            c.delete(url(orgs, member))
        assert not MemberPhoto.objects.exists()
        import os

        assert not any(os.path.exists(f) for f in files)  # Dateien sind weg
        stored = list((settings.PRIVATE_ROOT / "photos").rglob("*.jpg"))
        assert stored == []

    def test_nur_bilder_erlaubt(self, api, orgs, member, board_a):
        fake = io.BytesIO(b"GIF89a" + b"0" * 100)
        fake.name = "x.gif"
        resp = api(board_a).post(url(orgs, member), {"file": fake, "consent": "true"})
        assert resp.status_code == 400
        gif = io.BytesIO()
        Image.new("RGB", (10, 10)).save(gif, "GIF")
        gif.seek(0)
        gif.name = "x.gif"
        resp = api(board_a).post(url(orgs, member), {"file": gif, "consent": "true"})
        assert resp.status_code == 400

    def test_rechte(self, api, orgs, member, board_a):
        c = api(board_a)
        c.post(url(orgs, member), {"file": image_file(), "consent": "true"})
        reader = make_user("leser@example.org")
        give_role(reader, orgs["a"], ["members.view"], name="Leser")
        r = api(reader)
        assert r.get(url(orgs, member)).status_code == 200  # ansehen ja
        assert r.delete(url(orgs, member)).status_code == 403  # ändern nein
        editor = make_user("editor@example.org")
        give_role(editor, orgs["a"], ["members.view", "members.edit"], name="Bearbeiter")
        assert api(editor).delete(url(orgs, member)).status_code == 403  # braucht „Fotos verwalten“

    def test_anderer_verein_sieht_nichts(self, api, orgs, member, board_a, board_b):
        api(board_a).post(url(orgs, member), {"file": image_file(), "consent": "true"})
        assert api(board_b).get(url(orgs, member)).status_code == 404
        resp = api(board_b).get(f"/api/orgs/{orgs['b'].pk}/members/{member['id']}/photo/")
        assert resp.status_code == 404

    def test_widerruf_der_einwilligung_loescht_foto(self, api, orgs, member, board_a):
        c = api(board_a)
        c.post(url(orgs, member), {"file": image_file(), "consent": "true"})
        resp = c.patch(url(orgs, member, "consent/"), {"photo_consent_at": None}, content_type=JSON)
        assert resp.json()["photo"]["approved"] is None
        assert not MemberPhoto.objects.exists()

    def test_vorstand_hat_recht_standardmaessig(self, orgs, board_a):
        role = Role.objects.get(organization=orgs["a"], name="Vorstand")
        assert "photos.manage" in role.permissions

    def test_loeschfrist_entfernt_fotos(self, api, orgs, member, board_a):
        c = api(board_a)
        c.post(url(orgs, member), {"file": image_file(), "consent": "true"})
        c.post(
            f"/api/orgs/{orgs['a'].pk}/members/{member['id']}/exit/",
            {"exit_date": "2020-12-31", "exit_reason": "exit"},
            content_type=JSON,
        )
        purge_expired(datetime.date(2024, 1, 1))
        assert not MemberPhoto.objects.exists()
        assert Membership.objects.get().photo_consent_at is None

    def test_pdf_export_mit_foto(self, api, orgs, member, board_a):
        c = api(board_a)
        c.post(url(orgs, member), {"file": image_file(), "consent": "true"})
        resp = c.post(
            f"/api/orgs/{orgs['a'].pk}/exports/",
            {
                "kind": "members",
                "file_format": "pdf",
                "columns": ["photo", "last_name"],
                "filters": {"status": "alle"},
            },
            content_type=JSON,
        )
        job = c.get(f"/api/orgs/{orgs['a'].pk}/exports/{resp.json()['id']}/").json()
        assert job["status"] == "done", job
        xlsx = c.post(
            f"/api/orgs/{orgs['a'].pk}/exports/",
            {
                "kind": "members",
                "file_format": "xlsx",
                "columns": ["photo", "last_name"],
                "filters": {"status": "alle"},
            },
            content_type=JSON,
        )
        assert (
            c.get(f"/api/orgs/{orgs['a'].pk}/exports/{xlsx.json()['id']}/").json()["status"]
            == "done"
        )


class TestUploadLink:
    @pytest.fixture(autouse=True)
    def _cache(self):
        cache.clear()

    def create_link(self, c, orgs, member, **data):
        resp = c.post(url(orgs, member).replace("photo/", "photo-links/"), data, content_type=JSON)
        assert resp.status_code == 201, resp.json()
        return resp.json()

    def public(self, link):
        return "/api/public/photo/" + link["url"].rsplit("/", 1)[1] + "/"

    def test_link_erzeugen_und_mail(self, api, orgs, member, board_a):
        link = self.create_link(api(board_a), orgs, member, send_email=True)
        assert link["state"] == "open"
        assert link["sent_to"] == "erika@example.org"
        token = link["url"].rsplit("/", 1)[1]
        # Gespeichert ist nur der Hash, das Token enthält keinen Personenbezug
        stored = PhotoUploadLink.objects.get()
        assert stored.token_hash == hash_token(token) and token not in stored.token_hash
        assert len(token) >= 40 and "erika" not in token.lower() and "muster" not in token.lower()
        assert re.search(r"/foto/\S+", mail.outbox[0].body)
        # Die Adresse wird später nicht mehr angezeigt
        listing = api(board_a).get(url(orgs, member).replace("photo/", "photo-links/")).json()
        assert "url" not in listing[0]

    def test_oeffentliche_seite_zeigt_nur_vorname(self, client, api, orgs, member, board_a):
        link = self.create_link(api(board_a), orgs, member)
        data = client.get(self.public(link)).json()
        assert data["first_name"] == "Erika"
        assert data["organization"] == "Verein A"
        assert "last_name" not in data and "email" not in data and "birth_date" not in data

    def test_upload_mit_einwilligung_einmalig(self, client, api, orgs, member, board_a):
        link = self.create_link(api(board_a), orgs, member)
        no_consent = client.post(self.public(link), {"file": image_file()})
        assert no_consent.status_code == 400
        resp = client.post(self.public(link), {"file": image_file(), "consent": "true"})
        assert resp.status_code == 201, resp.json()
        assert resp.json()["status"] == "approved"
        m = Membership.objects.get()
        assert m.photo_consent_source == "member"
        assert m.photo_consent_at == datetime.date.today()
        photo = MemberPhoto.objects.get()
        assert photo.source == "member" and photo.uploaded_by is None
        # einmal nutzbar
        assert (
            client.post(self.public(link), {"file": image_file(), "consent": "true"}).status_code
            == 404
        )
        assert client.get(self.public(link)).status_code == 404
        assert AuditEntry.objects.filter(changes__has_key="Foto-Einwilligung").exists()

    def test_freigabe_wenn_eingestellt(self, client, api, orgs, member, board_a):
        orgs["a"].photo_approval_required = True
        orgs["a"].save()
        c = api(board_a)
        link = self.create_link(c, orgs, member)
        resp = client.post(self.public(link), {"file": image_file(), "consent": "true"})
        assert resp.json()["status"] == "pending"
        detail = c.get(f"/api/orgs/{orgs['a'].pk}/members/{member['id']}/").json()
        assert detail["photo"]["approved"] is None and detail["photo"]["pending"]
        rows = c.get(f"/api/orgs/{orgs['a'].pk}/members/").json()["results"]
        assert rows[0]["photo_url"] is None  # wartendes Foto erscheint nicht in der Liste
        reader = make_user("leser@example.org")
        give_role(reader, orgs["a"], ["members.view"], name="Leser")
        assert api(reader).get(url(orgs, member, "?status=pending")).status_code == 404
        approved = c.post(url(orgs, member, "approve/"), {}, content_type=JSON).json()
        assert approved["photo"]["approved"]["source"] == "member"
        assert approved["photo"]["pending"] is None

    def test_ablehnen(self, client, api, orgs, member, board_a):
        orgs["a"].photo_approval_required = True
        orgs["a"].save()
        c = api(board_a)
        client.post(
            self.public(self.create_link(c, orgs, member)),
            {"file": image_file(), "consent": "true"},
        )
        c.post(url(orgs, member, "approve/"), {"decision": "reject"}, content_type=JSON)
        assert not MemberPhoto.objects.exists()

    def test_widerrufen_und_abgelaufen(self, client, api, orgs, member, board_a):
        c = api(board_a)
        link = self.create_link(c, orgs, member)
        c.post(url(orgs, member).replace("photo/", f"photo-links/{link['id']}/revoke/"))
        assert client.get(self.public(link)).status_code == 404
        second = self.create_link(c, orgs, member)
        PhotoUploadLink.objects.filter(pk=second["id"]).update(
            expires_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
        )
        assert client.get(self.public(second)).status_code == 404

    def test_falsches_token(self, client, db):
        assert client.get("/api/public/photo/erfunden123/").status_code == 404

    def test_rate_limit(self, client, db):
        codes = [client.get("/api/public/photo/x/").status_code for _ in range(32)]
        assert codes[0] == 404 and codes[-1] == 429

    def test_anderer_verein_kann_keine_links(self, api, orgs, member, board_b):
        resp = api(board_b).post(f"/api/orgs/{orgs['b'].pk}/members/{member['id']}/photo-links/")
        assert resp.status_code == 404
