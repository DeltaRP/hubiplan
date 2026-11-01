"""Webseite: Texte (Entwurf, Veröffentlichen, Fassungen) und Bilder (alles erfunden)."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from organizations.models import Department
from website.models import Website, WebsiteImage, WebsiteText

from .factories import give_role, make_user

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def private_root(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def site(orgs):
    org = orgs["a"]
    org.enabled_modules = ["members", "website"]
    org.save()
    return Website.objects.create(organization=org, public_key=Website.new_key())


def url(org, rest=""):
    return f"/api/orgs/{org.pk}/website/{rest}"


def png(size=(3000, 1500), exif=True, mode="RGB"):
    img = Image.new(mode, size, "red")
    buf = io.BytesIO()
    if exif and mode == "RGB":
        ex = Image.Exif()
        ex[0x010F] = "Kamerahersteller"
        img.save(buf, "JPEG", exif=ex)
        return SimpleUploadedFile("foto.jpg", buf.getvalue(), content_type="image/jpeg")
    img.save(buf, "PNG")
    return SimpleUploadedFile("bild.png", buf.getvalue(), content_type="image/png")


@pytest.fixture
def editor(orgs):
    user = make_user("schrift@example.org")
    give_role(user, orgs["a"], permissions=["website.content"], name="Schriftführer")
    return user


class TestTexte:
    def test_begruessung_wird_angelegt(self, orgs, editor, api, site):
        data = api(editor).get(url(orgs["a"], "texts/")).json()
        assert [t["kind"] for t in data["texts"]] == ["greeting"]
        assert data["texts"][0]["is_published"] is False

    def test_seite_entwurf_veroeffentlichen_fassungen(self, orgs, editor, api, site):
        c = api(editor)
        resp = c.post(
            url(orgs["a"], "texts/"),
            {
                "kind": "page",
                "slug": "geschichte",
                "title": "Geschichte",
                "body": "# 1920\nGegründet.",
            },
            "application/json",
        )
        assert resp.status_code == 201, resp.content
        pk = resp.json()["id"]
        assert resp.json()["has_changes"] is True
        pub = c.post(url(orgs["a"], f"texts/{pk}/publish/")).json()
        assert pub["is_published"] is True and pub["has_changes"] is False
        assert pub["published_body"] == "# 1920\nGegründet."
        # Entwurf ändern: veröffentlichte Fassung bleibt
        data = c.put(url(orgs["a"], f"texts/{pk}/"), {"body": "Neu"}, "application/json").json()
        assert data["has_changes"] is True and data["published_body"] == "# 1920\nGegründet."
        c.post(url(orgs["a"], f"texts/{pk}/publish/"))
        data = c.get(url(orgs["a"], f"texts/{pk}/")).json()
        assert len(data["revisions"]) == 2
        # alte Fassung zurückholen
        old = data["revisions"][1]["id"]
        data = c.post(url(orgs["a"], f"texts/{pk}/revisions/{old}/restore/")).json()
        assert data["body"] == "# 1920\nGegründet." and data["published_body"] == "Neu"
        # zurücknehmen
        data = c.delete(url(orgs["a"], f"texts/{pk}/publish/")).json()
        assert data["is_published"] is False

    def test_adresse_pruefen(self, orgs, editor, api, site):
        c = api(editor)
        post = lambda slug: c.post(  # noqa: E731
            url(orgs["a"], "texts/"), {"slug": slug, "title": "X"}, "application/json"
        )
        assert post("Geschichte!").status_code == 400
        assert post("kontakt").status_code == 400
        assert post("geschichte").status_code == 201
        assert post("geschichte").status_code == 400

    def test_text_einer_untereinheit(self, orgs, editor, api, site):
        unit = Department.objects.create(organization=orgs["a"], parent=orgs["a"], name="Zug 1")
        other = Department.objects.create(organization=orgs["b"], parent=orgs["b"], name="Zug B")
        c = api(editor)
        body = {"kind": "unit", "department": unit.pk, "title": "Zug 1", "body": "Seit 1950"}
        assert c.post(url(orgs["a"], "texts/"), body, "application/json").status_code == 201
        assert c.post(url(orgs["a"], "texts/"), body, "application/json").status_code == 400
        body["department"] = other.pk
        assert c.post(url(orgs["a"], "texts/"), body, "application/json").status_code == 400

    def test_linkziele_fuer_den_editor(self, orgs, editor, api, site):
        Department.objects.create(organization=orgs["a"], parent=orgs["a"], name="Jägerzug")
        c = api(editor)
        c.post(
            url(orgs["a"], "texts/"),
            {"kind": "page", "slug": "festfolge", "title": "Festfolge"},
            "application/json",
        )
        targets = c.get(url(orgs["a"], "texts/")).json()["link_targets"]
        hrefs = [t["href"] for t in targets]
        assert hrefs[0] == "seite:start"
        for href in ("seite:termine", "seite:vorstand", "seite:kontakt", "seite:impressum"):
            assert href in hrefs
        assert "seite:einheit/jaegerzug" in hrefs
        page = next(t for t in targets if t["href"] == "seite:seite/festfolge")
        assert page["label"] == "Festfolge (noch nicht veröffentlicht)"
        # ausgeschaltete Bereiche fehlen
        site.blocks = {**(site.blocks or {}), "contact": False}
        site.save()
        hrefs = [t["href"] for t in c.get(url(orgs["a"], "texts/")).json()["link_targets"]]
        assert "seite:kontakt" not in hrefs

    def test_begruessung_nicht_loeschbar(self, orgs, editor, api, site):
        c = api(editor)
        pk = c.get(url(orgs["a"], "texts/")).json()["texts"][0]["id"]
        assert c.delete(url(orgs["a"], f"texts/{pk}/")).status_code == 400
        resp = c.post(url(orgs["a"], "texts/"), {"kind": "greeting"}, "application/json")
        assert resp.status_code == 400

    def test_ohne_recht(self, orgs, api, site):
        user = make_user("kasse@example.org")
        give_role(user, orgs["a"], permissions=["finance.view"], name="Kasse")
        assert api(user).get(url(orgs["a"], "texts/")).status_code == 404

    def test_fremde_webseite(self, orgs, board_b, api, site):
        assert api(board_b).get(url(orgs["a"], "texts/")).status_code == 404


class TestBilder:
    def test_hochladen_verkleinert_ohne_exif(self, orgs, editor, api, site):
        c = api(editor)
        resp = c.post(
            url(orgs["a"], "images/"),
            {"file": png(), "caption": "Fahne", "alt_text": "Vereinsfahne"},
        )
        assert resp.status_code == 201, resp.content
        data = resp.json()
        assert data["width"] == 2000 and data["height"] == 1000
        assert data["markdown"] == f"![Vereinsfahne](bild:{data['key']})"
        image = WebsiteImage.objects.get(pk=data["id"])
        with image.file.open("rb") as f:
            stored = Image.open(f)
            assert not stored.getexif()
        with image.small.open("rb") as f:
            assert max(Image.open(f).size) == 800
        file = c.get(data["small_url"])
        assert file.status_code == 200 and file["Content-Type"] == "image/jpeg"

    def test_transparenz_bleibt_png(self, orgs, editor, api, site):
        resp = api(editor).post(url(orgs["a"], "images/"), {"file": png((100, 100), mode="RGBA")})
        assert resp.status_code == 201
        assert WebsiteImage.objects.get().file.name.endswith(".png")

    def test_kein_bild(self, orgs, editor, api, site):
        bad = SimpleUploadedFile("x.jpg", b"kein bild", content_type="image/jpeg")
        assert api(editor).post(url(orgs["a"], "images/"), {"file": bad}).status_code == 400

    def test_loeschen_nur_nach_rueckfrage(self, orgs, editor, api, site):
        c = api(editor)
        image = c.post(url(orgs["a"], "images/"), {"file": png((50, 50))}).json()
        text = c.post(
            url(orgs["a"], "texts/"),
            {"slug": "fahne", "title": "Fahne", "body": image["markdown"]},
            "application/json",
        ).json()
        resp = c.delete(url(orgs["a"], f"images/{image['id']}/"))
        assert resp.status_code == 409 and resp.json()["places"] == ["Fahne: im Text"]
        c.put(url(orgs["a"], f"texts/{text['id']}/"), {"body": ""}, "application/json")
        assert c.delete(url(orgs["a"], f"images/{image['id']}/")).status_code == 204
        assert not WebsiteImage.objects.exists()

    def test_bild_am_text(self, orgs, editor, api, site):
        c = api(editor)
        image = c.post(url(orgs["a"], "images/"), {"file": png((50, 50))}).json()
        pk = c.get(url(orgs["a"], "texts/")).json()["texts"][0]["id"]
        data = c.put(url(orgs["a"], f"texts/{pk}/"), {"image": image["id"]}, "application/json")
        assert data.json()["image_data"]["key"] == image["key"]
        c.post(url(orgs["a"], f"texts/{pk}/publish/"))
        assert WebsiteText.objects.get(pk=pk).published_image_id == image["id"]


class TestBilderkarussell:
    def test_karussell_der_begruessung(self, orgs, editor, api, site):
        from django.test import Client

        site.state = "public"
        site.save()
        c = api(editor)
        a = c.post(url(orgs["a"], "images/"), {"file": png((60, 40)), "alt_text": "A"}).json()
        b = c.post(url(orgs["a"], "images/"), {"file": png((60, 40)), "alt_text": "B"}).json()
        pk = c.get(url(orgs["a"], "texts/")).json()["texts"][0]["id"]
        resp = c.put(
            url(orgs["a"], f"texts/{pk}/"), {"gallery": [b["id"], a["id"]]}, "application/json"
        )
        assert resp.status_code == 200 and resp.json()["gallery"] == [b["id"], a["id"]]
        assert resp.json()["has_changes"] is True
        # Noch nicht veröffentlicht: öffentlich nichts
        public = f"/api/public/site/v1/{site.public_key}/"
        assert Client().get(public).json()["greeting"] is None
        c.post(url(orgs["a"], f"texts/{pk}/publish/"))
        greeting = Client().get(public).json()["greeting"]
        assert [i["alt"] for i in greeting["gallery"]] == ["B", "A"]
        # Bilder des Karussells sind öffentlich abrufbar und nicht löschbar
        assert Client().get(f"{public}images/{a['key']}/").status_code == 200
        assert c.delete(url(orgs["a"], f"images/{a['id']}/")).status_code == 409

    def test_karussell_pruefen(self, orgs, editor, api, site):
        c = api(editor)
        a = c.post(url(orgs["a"], "images/"), {"file": png((60, 40))}).json()
        pk = c.get(url(orgs["a"], "texts/")).json()["texts"][0]["id"]

        def put(value):
            return c.put(url(orgs["a"], f"texts/{pk}/"), {"gallery": value}, "application/json")

        assert put([a["id"], a["id"]]).status_code == 400
        assert put([999999]).status_code == 400
        assert put("x").status_code == 400
        page = c.post(
            url(orgs["a"], "texts/"),
            {"slug": "fahne", "title": "Fahne", "gallery": [a["id"]]},
            "application/json",
        )
        assert page.status_code == 400
        many = [
            c.post(url(orgs["a"], "images/"), {"file": png((20, 20))}).json()["id"]
            for _ in range(10)
        ]
        assert put([a["id"], *many]).status_code == 400  # höchstens 10
        assert put(many).status_code == 200

    def test_wechselzeit_je_karussell(self, orgs, editor, api, site):
        from django.test import Client

        site.state = "public"
        site.save()
        c = api(editor)
        pk = c.get(url(orgs["a"], "texts/")).json()["texts"][0]["id"]
        text = c.get(url(orgs["a"], f"texts/{pk}/")).json()
        assert text["gallery_interval"] == 7  # Standard wie bisher

        def put(value):
            return c.put(
                url(orgs["a"], f"texts/{pk}/"), {"gallery_interval": value}, "application/json"
            )

        assert put(2).status_code == 400
        assert put(31).status_code == 400
        resp = put(12)
        assert resp.status_code == 200 and resp.json()["gallery_interval"] == 12
        assert resp.json()["has_changes"] is True
        c.post(url(orgs["a"], f"texts/{pk}/publish/"))
        public = f"/api/public/site/v1/{site.public_key}/"
        assert Client().get(public).json()["greeting"]["gallery_interval"] == 12
        # Ältere Fassung zurückholen bringt auch ihre Wechselzeit zurück
        revision = WebsiteText.objects.get(pk=pk).revisions.first()
        put(5)
        c.post(url(orgs["a"], f"texts/{pk}/revisions/{revision.pk}/restore/"))
        assert WebsiteText.objects.get(pk=pk).gallery_interval == 12


class TestBildTrotzdemLoeschen:
    def test_stellen_genau_benannt(self, orgs, editor, api, site):
        c = api(editor)
        image = c.post(url(orgs["a"], "images/"), {"file": png((50, 50))}).json()
        pk = c.get(url(orgs["a"], "texts/")).json()["texts"][0]["id"]
        c.put(url(orgs["a"], f"texts/{pk}/"), {"gallery": [image["id"]]}, "application/json")
        c.post(url(orgs["a"], f"texts/{pk}/publish/"))
        # Aus dem Entwurf genommen, aber noch nicht wieder veröffentlicht
        c.put(url(orgs["a"], f"texts/{pk}/"), {"gallery": []}, "application/json")
        resp = c.delete(url(orgs["a"], f"images/{image['id']}/"))
        assert resp.status_code == 409
        assert resp.json()["places"] == [
            "Willkommen: Bilderkarussell (nur noch in der veröffentlichten Fassung)"
        ]

    def test_trotzdem_loeschen_entfernt_verweise(self, orgs, editor, api, site):
        c = api(editor)
        image = c.post(url(orgs["a"], "images/"), {"file": png((50, 50))}).json()
        other = c.post(url(orgs["a"], "images/"), {"file": png((50, 50))}).json()
        body = f"Vorher\n\n{image['markdown']}\n\n{other['markdown']} Nachher"
        pk = c.get(url(orgs["a"], "texts/")).json()["texts"][0]["id"]
        c.put(
            url(orgs["a"], f"texts/{pk}/"),
            {"body": body, "image": image["id"], "gallery": [other["id"], image["id"]]},
            "application/json",
        )
        c.post(url(orgs["a"], f"texts/{pk}/publish/"))
        resp = c.delete(url(orgs["a"], f"images/{image['id']}/?trotzdem=1"))
        assert resp.status_code == 204
        assert not WebsiteImage.objects.filter(pk=image["id"]).exists()
        t = WebsiteText.objects.get(pk=pk)
        assert f"bild:{image['key']}" not in t.body + t.published_body
        assert other["markdown"] in t.body and "Vorher" in t.body and "Nachher" in t.body
        assert t.image_id is None and t.published_image_id is None
        assert t.gallery == [other["id"]] and t.published_gallery == [other["id"]]
        revision = t.revisions.get()
        assert f"bild:{image['key']}" not in revision.body
        assert revision.gallery == [other["id"]]
        # Das andere Bild bleibt unberührt und ist weiter verwendet
        assert c.delete(url(orgs["a"], f"images/{other['id']}/")).status_code == 409

    def test_bildtext_mit_klammern(self):
        from website.content import _image_markdown

        text = '![Fahne \\] alt](bild:abc "Titel") Rest ![x](bild:abcd)'
        assert _image_markdown("abc").sub("", text) == " Rest ![x](bild:abcd)"
