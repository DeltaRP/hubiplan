"""Satzungen: Fassungen, Rechte, öffentlicher Abruf, Aufräumen."""

import io
import os

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client

from audit.models import AuditEntry
from organizations.models import Department
from statutes.models import StatutePublication, StatuteVersion

from .factories import give_role, make_user

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def private_root(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


def pdf(name="satzung.pdf", body=b"%PDF-1.4 erfundene Satzung"):
    return SimpleUploadedFile(name, body, content_type="application/pdf")


def upload(client, org, valid_from="2020-05-01", department=None, file=None, note=""):
    data = {"file": file or pdf(), "valid_from": valid_from, "note": note}
    if department:
        data["department"] = department.pk
    return client.post(f"/api/orgs/{org.pk}/statutes/", data)


def body(resp) -> bytes:
    return b"".join(resp.streaming_content)


class TestFassungen:
    def test_hochladen_liste_aktuell(self, orgs, board_a, api):
        c = api(board_a)
        assert upload(c, orgs["a"], "2001-01-01", note="Neufassung").status_code == 201
        resp = upload(c, orgs["a"], "2019-11-08", file=pdf(body=b"%PDF-1.7 neu"))
        assert resp.status_code == 201
        data = c.get(f"/api/orgs/{orgs['a'].pk}/statutes/").json()
        assert [v["valid_from"] for v in data["versions"]] == ["2019-11-08", "2001-01-01"]
        assert [v["is_current"] for v in data["versions"]] == [True, False]
        assert data["publication"]["is_public"] is False
        assert data["can_manage"] is True
        # Download
        resp = c.get(data["versions"][1]["url"])
        assert resp.status_code == 200 and resp["Content-Type"] == "application/pdf"
        assert body(resp) == b"%PDF-1.4 erfundene Satzung"
        # Protokoll
        assert AuditEntry.objects.filter(organization=orgs["a"], action="create").exists()

    def test_nur_pdf_und_groesse(self, orgs, board_a, api, monkeypatch):
        c = api(board_a)
        resp = upload(c, orgs["a"], file=pdf("satzung.pdf", b"kein pdf"))
        assert resp.status_code == 400 and "PDF" in str(resp.json())
        monkeypatch.setattr("statutes.services.MAX_STATUTE_BYTES", 10)
        assert upload(c, orgs["a"]).status_code == 400
        assert not StatuteVersion.objects.exists()

    def test_loeschen_entfernt_datei(self, orgs, board_a, api):
        c = api(board_a)
        upload(c, orgs["a"])
        version = StatuteVersion.objects.get()
        path = version.file.path
        assert os.path.exists(path)
        assert c.delete(f"/api/orgs/{orgs['a'].pk}/statutes/{version.pk}/").status_code == 204
        assert not StatuteVersion.objects.exists()
        assert not os.path.exists(path)

    def test_abteilung_getrennt(self, orgs, board_a, api):
        c = api(board_a)
        zug = Department.objects.create(organization=orgs["a"], name="1. Zug", founding_year=1990)
        upload(c, orgs["a"], "2010-01-01")
        upload(c, orgs["a"], "2015-01-01", department=zug)
        org_list = c.get(f"/api/orgs/{orgs['a'].pk}/statutes/").json()["versions"]
        dep_list = c.get(f"/api/orgs/{orgs['a'].pk}/statutes/?department={zug.pk}").json()
        assert [v["valid_from"] for v in org_list] == ["2010-01-01"]
        assert [v["valid_from"] for v in dep_list["versions"]] == ["2015-01-01"]

    def test_fremde_abteilung_abgelehnt(self, orgs, board_a, api):
        fremd = Department.objects.create(organization=orgs["b"], name="X", founding_year=1990)
        resp = upload(api(board_a), orgs["a"], department=fremd)
        assert resp.status_code == 404

    def test_dachverband(self, orgs, api):
        user = make_user("verband@example.org")
        give_role(user, orgs["federation"])
        assert upload(api(user), orgs["federation"]).status_code == 201


class TestRechte:
    def test_lesen_ohne_bearbeitungsrecht(self, orgs, board_a, api):
        upload(api(board_a), orgs["a"])
        leser = make_user("kasse@example.org")
        give_role(leser, orgs["a"], permissions=["members.view"], name="Kassierer")
        c = api(leser)
        data = c.get(f"/api/orgs/{orgs['a'].pk}/statutes/").json()
        assert len(data["versions"]) == 1 and data["can_manage"] is False
        assert c.get(data["versions"][0]["url"]).status_code == 200
        assert upload(c, orgs["a"]).status_code == 403
        version = StatuteVersion.objects.get()
        assert c.delete(f"/api/orgs/{orgs['a'].pk}/statutes/{version.pk}/").status_code == 403
        resp = c.put(
            f"/api/orgs/{orgs['a'].pk}/statutes/publication/",
            {"is_public": True},
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_fremde_organisation_unsichtbar(self, orgs, board_a, board_b, api):
        upload(api(board_a), orgs["a"])
        version = StatuteVersion.objects.get()
        c = api(board_b)
        assert c.get(f"/api/orgs/{orgs['a'].pk}/statutes/").status_code == 404
        assert c.get(f"/api/orgs/{orgs['b'].pk}/statutes/{version.pk}/").status_code == 404


class TestOeffentlich:
    def publish(self, client, org, on=True, department=None):
        data = {"is_public": on}
        if department:
            data["department"] = department.pk
        return client.put(
            f"/api/orgs/{org.pk}/statutes/publication/", data, content_type="application/json"
        )

    def test_standard_aus_dann_stabiler_link(self, orgs, board_a, api):
        c = api(board_a)
        upload(c, orgs["a"], "2001-01-01")
        resp = self.publish(c, orgs["a"])
        assert resp.status_code == 200
        urls = resp.json()
        pdf_path = urls["pdf_url"].split("testserver", 1)[1]
        anon = Client()
        resp = anon.get(pdf_path)
        assert resp.status_code == 200
        assert resp["Access-Control-Allow-Origin"] == "*"
        assert body(resp) == b"%PDF-1.4 erfundene Satzung"
        # Neue Fassung: derselbe Link liefert die neue
        upload(c, orgs["a"], "2020-01-01", file=pdf(body=b"%PDF-1.7 neu"))
        assert body(anon.get(pdf_path)) == b"%PDF-1.7 neu"
        info = anon.get(urls["info_url"].split("testserver", 1)[1]).json()
        assert info["name"] == "Verein A"
        assert [v["valid_from"] for v in info["versions"]] == ["2020-01-01", "2001-01-01"]
        old = info["versions"][1]["url"].split("testserver", 1)[1]
        assert body(anon.get(old)) == b"%PDF-1.4 erfundene Satzung"
        # Ausschalten: Link liefert nichts mehr, beim Wiedereinschalten derselbe Link
        self.publish(c, orgs["a"], on=False)
        assert anon.get(pdf_path).status_code == 404
        assert self.publish(c, orgs["a"]).json()["pdf_url"] == urls["pdf_url"]
        assert anon.get(pdf_path).status_code == 200

    def test_nicht_veroeffentlicht_oder_unbekannt(self, orgs, board_a, api):
        c = api(board_a)
        upload(c, orgs["a"])
        anon = Client()
        assert anon.get("/api/public/statutes/gibt-es-nicht/").status_code == 404
        pub = StatutePublication.objects.create(
            organization=orgs["a"], public_key="k" * 24, is_public=False
        )
        assert anon.get(f"/api/public/statutes/{pub.public_key}/").status_code == 404

    def test_fassung_anderer_organisation_nicht_ueber_fremden_link(
        self, orgs, board_a, board_b, api
    ):
        upload(api(board_a), orgs["a"])
        upload(api(board_b), orgs["b"])
        url = self.publish(api(board_a), orgs["a"]).json()["pdf_url"].split("testserver", 1)[1]
        other = StatuteVersion.objects.get(organization=orgs["b"])
        assert Client().get(f"{url}{other.pk}/").status_code == 404

    def test_abteilung_eigener_link(self, orgs, board_a, api):
        c = api(board_a)
        zug = Department.objects.create(organization=orgs["a"], name="1. Zug", founding_year=1990)
        upload(c, orgs["a"], department=zug)
        urls = self.publish(c, orgs["a"], department=zug).json()
        info = Client().get(urls["info_url"].split("testserver", 1)[1]).json()
        assert info["department"] == "1. Zug"
        # Satzung der Organisation selbst bleibt nicht öffentlich
        assert not StatutePublication.objects.filter(department=None).exists()


@pytest.mark.skipif(connection.vendor != "postgresql", reason="nur PostgreSQL")
def test_rls_trennt_organisationen(orgs, board_a, board_b, api):
    from core.rls import APP_ROLE
    from core.tenancy import set_rls

    upload(api(board_a), orgs["a"])
    upload(api(board_b), orgs["b"])
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {APP_ROLE}")
    try:
        set_rls(orgs["a"].pk, board_a.pk, False)
        assert list(StatuteVersion.objects.values_list("organization_id", flat=True)) == [
            orgs["a"].pk
        ]
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
        set_rls(None, None, False)


@pytest.mark.langsam
def test_demo_satzungen_und_aufraeumen():
    from django.core.management import call_command

    from organizations.models import Organization

    call_command("seed_testdata", password="Test-Passwort-123", stdout=io.StringIO())
    club = Organization.objects.get(type="club", name__startswith="Hubertus")
    fed = Organization.objects.get(name__startswith="Bürger-Schützenverein")
    assert StatuteVersion.objects.filter(organization=club).count() == 2
    assert StatuteVersion.objects.filter(organization=fed).count() == 1
    assert StatutePublication.objects.get(organization=club).is_public is True
    assert StatutePublication.objects.get(organization=fed).is_public is False
    v = StatuteVersion.objects.filter(organization=club).first()
    assert v.file.open("rb").read(5) == b"%PDF-"
    # wiederholbar
    call_command("seed_testdata", password="Test-Passwort-123", stdout=io.StringIO())
    assert StatuteVersion.objects.count() == 3
