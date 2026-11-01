"""Bilderverwaltung der Webseite (Ralf 01.11.): Original und Ausschnitt, neu zuschneiden,
ersetzen, kopieren, Zuordnung zu Untereinheiten, aktueller Alternativtext (alles erfunden)."""

import io
import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from organizations.models import Department
from website import content
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
    return Website.objects.create(organization=org, public_key=Website.new_key(), state="public")


@pytest.fixture
def editor(orgs):
    user = make_user("bilder@example.org")
    give_role(user, orgs["a"], permissions=["website.content"], name="Schriftführer")
    return user


def url(org, rest=""):
    return f"/api/orgs/{org.pk}/website/{rest}"


def jpg(size=(600, 400), color="red", name="foto.jpg"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


CROP = {"x": 10, "y": 0, "width": 50, "height": 100, "rotation": 0, "aspect": "1"}


def upload(c, org, **extra):
    data = {"file": jpg((300, 300)), "original": jpg((6000, 4000)), "crop": json.dumps(CROP)}
    data.update(extra)
    resp = c.post(url(org, "images/"), data)
    assert resp.status_code == 201, resp.content
    return resp.json()


def size_of(field) -> tuple[int, int]:
    with field.open("rb") as f:
        return Image.open(f).size


class TestOriginalUndAusschnitt:
    def test_original_wird_aufbewahrt(self, orgs, editor, api, site):
        data = upload(api(editor), orgs["a"])
        image = WebsiteImage.objects.get(pk=data["id"])
        assert size_of(image.original) == (4000, 2667)  # höchstens 4000 px
        assert size_of(image.file) == (300, 300)
        assert data["crop"] == CROP and data["version"] == 0 and data["used"] is False
        orig = api(editor).get(data["original_url"])
        assert orig.status_code == 200 and orig["Content-Type"] == "image/jpeg"

    def test_unveraendert_ist_zugleich_original(self, orgs, editor, api, site):
        resp = api(editor).post(url(orgs["a"], "images/"), {"file": jpg((500, 300))})
        image = WebsiteImage.objects.get(pk=resp.json()["id"])
        assert size_of(image.original) == (500, 300) and image.crop == {}

    def test_ausschnitt_wird_geprueft(self, orgs, editor, api, site):
        c = api(editor)
        for bad in ("kein json", json.dumps({"x": 1}), json.dumps({**CROP, "width": 150})):
            resp = c.post(
                url(orgs["a"], "images/"),
                {"file": jpg(), "original": jpg(), "crop": bad},
            )
            assert resp.status_code == 400, bad
        resp = c.post(
            url(orgs["a"], "images/"),
            {"file": jpg(), "original": jpg(), "crop": json.dumps({**CROP, "rotation": 45})},
        )
        assert resp.status_code == 400

    def test_neu_zuschneiden(self, orgs, editor, api, site):
        c = api(editor)
        data = upload(c, orgs["a"])
        image = WebsiteImage.objects.get(pk=data["id"])
        old_file, original = image.file.name, image.original.name
        new_crop = {"x": 0, "y": 0, "width": 100, "height": 50, "rotation": 90}
        resp = c.post(
            url(orgs["a"], f"images/{data['id']}/crop/"),
            {"file": jpg((800, 200)), "crop": json.dumps(new_crop)},
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["version"] == 1 and resp.json()["crop"] == new_crop
        assert resp.json()["width"] == 800 and resp.json()["key"] == data["key"]
        image.refresh_from_db()
        assert image.original.name == original and image.file.name != old_file
        assert not image.file.storage.exists(old_file)

    def test_altes_bild_ohne_original(self, orgs, editor, api, site):
        c = api(editor)
        data = upload(c, orgs["a"])
        image = WebsiteImage.objects.get(pk=data["id"])
        image.original.delete(save=False)
        image.original = ""
        image.save()
        resp = c.post(
            url(orgs["a"], f"images/{data['id']}/crop/"),
            {"file": jpg((100, 100)), "crop": json.dumps(CROP)},
        )
        assert resp.status_code == 200
        image.refresh_from_db()
        # Das bisherige Bild wurde zum Original
        assert size_of(image.original) == (300, 300)

    def test_ersetzen_behaelt_stellen(self, orgs, editor, api, site):
        c = api(editor)
        data = upload(c, orgs["a"], alt_text="Gruppenbild")
        pk = c.get(url(orgs["a"], "texts/")).json()["texts"][0]["id"]
        c.put(url(orgs["a"], f"texts/{pk}/"), {"image": data["id"]}, "application/json")
        resp = c.post(url(orgs["a"], f"images/{data['id']}/replace/"), {"file": jpg((700, 500))})
        assert resp.status_code == 200
        body = resp.json()
        assert body["alt_text"] == "Gruppenbild" and body["version"] == 1 and body["crop"] == {}
        assert body["used"] is True
        assert WebsiteText.objects.get(pk=pk).image_id == data["id"]
        image = WebsiteImage.objects.get(pk=data["id"])
        assert size_of(image.original) == (700, 500)

    def test_kopie_aus_demselben_original(self, orgs, editor, api, site):
        c = api(editor)
        unit = Department.objects.create(organization=orgs["a"], name="Zug Eichenlaub")
        data = upload(c, orgs["a"], caption="Fahne", department=unit.pk)
        resp = c.post(
            url(orgs["a"], f"images/{data['id']}/copy/"),
            {"file": jpg((160, 90)), "crop": json.dumps({**CROP, "aspect": "16:9"})},
        )
        assert resp.status_code == 201, resp.content
        copy = resp.json()
        assert copy["id"] != data["id"] and copy["key"] != data["key"]
        assert copy["caption"] == "Fahne" and copy["department"] == unit.pk
        assert copy["crop"]["aspect"] == "16:9"
        assert size_of(WebsiteImage.objects.get(pk=copy["id"]).original) == (4000, 2667)

    def test_loeschen_entfernt_original(self, orgs, editor, api, site):
        c = api(editor)
        data = upload(c, orgs["a"])
        image = WebsiteImage.objects.get(pk=data["id"])
        name = image.original.name
        assert c.delete(url(orgs["a"], f"images/{data['id']}/")).status_code == 204
        assert not image.original.storage.exists(name)


class TestZuordnung:
    def test_gehoert_zu_untereinheit(self, orgs, editor, api, site):
        c = api(editor)
        unit = Department.objects.create(organization=orgs["a"], name="Zug Eichenlaub")
        data = upload(c, orgs["a"], department=unit.pk)
        assert data["department"] == unit.pk and data["department_name"] == "Zug Eichenlaub"
        listed = c.get(url(orgs["a"], "images/")).json()
        assert listed[0]["department"] == unit.pk
        # Zurück auf „Verein allgemein“
        resp = c.put(
            url(orgs["a"], f"images/{data['id']}/"), {"department": None}, "application/json"
        )
        assert resp.status_code == 200 and resp.json()["department"] is None

    def test_fremde_untereinheit_abgelehnt(self, orgs, editor, api, site):
        other = Department.objects.create(organization=orgs["b"], name="Fremder Zug")
        resp = api(editor).post(url(orgs["a"], "images/"), {"file": jpg(), "department": other.pk})
        assert resp.status_code == 400

    def test_angaben_aendern_ohne_zuordnung(self, orgs, editor, api, site):
        c = api(editor)
        unit = Department.objects.create(organization=orgs["a"], name="Zug Eichenlaub")
        data = upload(c, orgs["a"], department=unit.pk)
        resp = c.put(
            url(orgs["a"], f"images/{data['id']}/"),
            {"caption": "Neu", "alt_text": "Neu beschrieben"},
            "application/json",
        )
        assert resp.json()["caption"] == "Neu" and resp.json()["department"] == unit.pk

    def test_stellen_im_detail(self, orgs, editor, api, site):
        c = api(editor)
        data = upload(c, orgs["a"])
        text = c.post(
            url(orgs["a"], "texts/"),
            {"slug": "fahne", "title": "Fahne", "body": data["markdown"]},
            "application/json",
        ).json()
        detail = c.get(url(orgs["a"], f"images/{data['id']}/")).json()
        assert detail["used"] is True
        assert detail["usage"] == [{"text": text["id"], "label": "Fahne", "places": ["im Text"]}]


class TestWebseite:
    def test_aktueller_alternativtext_und_fassung(self, orgs, editor, api, site):
        c = api(editor)
        data = upload(c, orgs["a"], alt_text="Alt")
        pk = c.get(url(orgs["a"], "texts/")).json()["texts"][0]["id"]
        c.put(
            url(orgs["a"], f"texts/{pk}/"),
            {"body": f"Vorher ![Alt](bild:{data['key']}) nachher", "image": data["id"]},
            "application/json",
        )
        c.post(url(orgs["a"], f"texts/{pk}/publish/"))
        c.put(
            url(orgs["a"], f"images/{data['id']}/"),
            {"alt_text": "Fahne [neu]"},
            "application/json",
        )
        c.post(
            url(orgs["a"], f"images/{data['id']}/crop/"),
            {"file": jpg((100, 100)), "crop": json.dumps(CROP)},
        )
        public = f"/api/public/site/v1/{site.public_key}/"
        greeting = Client().get(public).json()["greeting"]
        key = f"{data['key']}-v1"
        assert greeting["text"] == f"Vorher ![Fahne \\[neu\\]](bild:{key}) nachher"
        assert greeting["image"]["url"].endswith(f"images/{key}/")
        assert Client().get(f"{public}images/{key}/").status_code == 200
        # Ältere Adressen zeigen das aktuelle Bild
        assert Client().get(f"{public}images/{data['key']}/").status_code == 200
        assert Client().get(f"{public}images/{data['key']}-v7/").status_code == 200
        assert Client().get(f"{public}images/{data['key']}-vx/").status_code == 404

    def test_nur_schmuck_ohne_beschreibung(self, site):
        image = WebsiteImage.objects.create(
            organization=site.organization,
            website=site,
            key="SchmuckBild1",
            alt_text="Ranke",
            decorative=True,
        )
        body = f'![Ranke](bild:{image.key} "Titel")'
        assert content.public_body(body, site) == f'![](bild:{image.key} "Titel")'
        assert content.public_body("![x](bild:Unbekannt1)", site) == "![x](bild:Unbekannt1)"


class TestMigration:
    def test_zuordnung_bestehender_bilder(self, orgs, site):
        from importlib import import_module

        from django.apps import apps

        unit = Department.objects.create(organization=orgs["a"], name="Zug Eichenlaub")
        only_unit = WebsiteImage.objects.create(
            organization=orgs["a"], website=site, key="NurZug00001"
        )
        both = WebsiteImage.objects.create(organization=orgs["a"], website=site, key="Beides00001")
        WebsiteText.objects.create(
            organization=orgs["a"],
            website=site,
            kind="unit",
            department=unit,
            gallery=[only_unit.pk, both.pk],
        )
        WebsiteText.objects.create(
            organization=orgs["a"],
            website=site,
            kind="page",
            slug="x",
            body="![](bild:Beides00001)",
        )
        migration = import_module("website.migrations.0023_bilderverwaltung")
        migration.assign_units(apps, None)
        only_unit.refresh_from_db()
        both.refresh_from_db()
        assert only_unit.department_id == unit.pk and both.department_id is None
