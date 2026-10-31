"""Dokumentenablage: Ordner, Fassungen, Rechte, Freigaben, Papierkorb, Export."""

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from access.catalog import DEPT_DOCS_MANAGE, DEPT_MEMBERS_VIEW, DOCS_VIEW, MEMBERS_VIEW
from audit.models import AuditEntry
from documents import services
from documents.models import Document, DocumentVersion, Folder
from organizations.models import Department

from .factories import give_role, make_user
from .test_m12_events import dept_role, member_with_access

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture(autouse=True)
def private_root(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def setup(orgs):
    for org in orgs.values():
        org.member_portal_enabled = True
        org.department_access_enabled = True
        org.save()
    return orgs


@pytest.fixture
def board_fed(setup):
    user = make_user("vorstand-bund@example.org")
    give_role(user, setup["federation"])
    return user


@pytest.fixture
def zug(setup):
    return Department.objects.create(
        self_managed=True, organization=setup["a"], name="Jägerzug", founding_year=1950
    )


def pdf(name="protokoll.pdf", body=b"%PDF-1.4 erfundenes Protokoll"):
    return SimpleUploadedFile(name, body, content_type="application/pdf")


def base(org) -> str:
    return f"/api/orgs/{org.pk}/documents/"


def folder(client, b, name="Protokolle", visibility="board"):
    data = {"name": name, "visibility": visibility}
    resp = client.post(f"{b}folders/", data, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    return resp.json()


def upload(client, b, folder_id, title="Protokoll JHV", file=None, **extra):
    resp = client.post(
        f"{b}folders/{folder_id}/documents/",
        {"title": title, "file": file or pdf(), **extra},
    )
    assert resp.status_code == 201, resp.json()
    return resp.json()


def body(resp) -> bytes:
    return b"".join(resp.streaming_content)


def overview(client, b):
    resp = client.get(b)
    assert resp.status_code == 200, resp.content
    return resp.json()


class TestAblage:
    def test_ordner_dokument_fassungen(self, setup, board_a, api):
        c = api(board_a)
        b = base(setup["a"])
        f = folder(c, b)
        doc = upload(c, b, f["id"], date="2026-02-14", note="Entwurf")
        assert doc["current"]["name"] == "protokoll.pdf"
        assert doc["version_count"] == 1
        # neue Fassung
        resp = c.post(f"{b}{doc['id']}/versions/", {"file": pdf("v2.pdf", b"%PDF-1.7 neu")})
        assert resp.status_code == 201
        doc = resp.json()
        assert [v["name"] for v in doc["versions"]] == ["v2.pdf", "protokoll.pdf"]
        data = overview(c, b)
        assert data["can_manage"] is True
        assert data["folders"][0]["documents"][0]["title"] == "Protokoll JHV"
        assert data["used_bytes"] == len(b"%PDF-1.4 erfundenes Protokoll") + len(b"%PDF-1.7 neu")
        # Abruf mit Protokolleintrag
        resp = c.get(doc["versions"][1]["url"])
        assert resp.status_code == 200 and resp["Content-Type"] == "application/pdf"
        assert body(resp) == b"%PDF-1.4 erfundenes Protokoll"
        assert AuditEntry.objects.filter(organization=setup["a"], action="view").exists()
        # ältere Fassung löschen, die einzige nicht
        assert c.delete(doc["versions"][1]["url"]).status_code == 204
        resp = c.delete(doc["versions"][0]["url"])
        assert resp.status_code == 400

    def test_dateiarten(self, setup, board_a, api):
        c = api(board_a)
        b = base(setup["a"])
        f = folder(c, b)
        bad = c.post(
            f"{b}folders/{f['id']}/documents/",
            {"title": "x", "file": SimpleUploadedFile("x.exe", b"MZ\x90\x00")},
        )
        assert bad.status_code == 400
        fake = c.post(
            f"{b}folders/{f['id']}/documents/",
            {"title": "x", "file": SimpleUploadedFile("x.pdf", b"kein pdf")},
        )
        assert fake.status_code == 400
        docx = upload(
            c, b, f["id"], "Formular", file=SimpleUploadedFile("f.docx", b"PK\x03\x04rest")
        )
        assert docx["current"]["inline"] is False
        resp = c.get(docx["current"]["url"])
        assert "attachment" in resp["Content-Disposition"]
        assert Document.objects.count() == 1

    def test_rechte(self, setup, board_a, api):
        b = base(setup["a"])
        f = folder(api(board_a), b)
        reader = make_user("leser@example.org")
        give_role(reader, setup["a"], [DOCS_VIEW], name="Leser")
        c = api(reader)
        assert overview(c, b)["can_manage"] is False
        resp = c.post(f"{b}folders/{f['id']}/documents/", {"title": "x", "file": pdf()})
        assert resp.status_code == 403
        nobody = make_user("kassenpruefer@example.org")
        give_role(nobody, setup["a"], [MEMBERS_VIEW], name="Kassenprüfer")
        assert api(nobody).get(b).status_code == 403
        # fremder Verein sieht nichts
        assert api(make_user("x@example.org")).get(b).status_code == 404

    def test_umbenennen_verschieben_ordner_loeschen(self, setup, board_a, api):
        c = api(board_a)
        b = base(setup["a"])
        f1 = folder(c, b, "Protokolle")
        f2 = folder(c, b, "Archiv")
        doc = upload(c, b, f1["id"])
        resp = c.patch(f"{b}folders/{f1['id']}/", {"name": "Sitzungen"}, content_type=JSON)
        assert resp.json()["name"] == "Sitzungen"
        assert c.delete(f"{b}folders/{f1['id']}/").status_code == 400  # nicht leer
        resp = c.patch(f"{b}{doc['id']}/", {"folder": f2["id"], "title": "JHV"}, content_type=JSON)
        assert resp.json()["folder"] == f2["id"] and resp.json()["title"] == "JHV"
        assert c.delete(f"{b}folders/{f1['id']}/").status_code == 204

    def test_dachverband_hat_keine_mitgliederfreigabe(self, setup, board_fed, api):
        c = api(board_fed)
        resp = c.post(
            f"{base(setup['federation'])}folders/",
            {"name": "x", "visibility": "members"},
            content_type=JSON,
        )
        assert resp.status_code == 400


class TestPapierkorb:
    def test_loeschen_wiederherstellen_endgueltig(self, setup, board_a, api):
        c = api(board_a)
        b = base(setup["a"])
        f = folder(c, b)
        doc = upload(c, b, f["id"])
        assert c.delete(f"{b}{doc['id']}/").status_code == 204
        assert overview(c, b)["folders"][0]["documents"] == []
        assert overview(c, b)["trash_count"] == 1
        trash = c.get(f"{b}trash/").json()
        assert [d["title"] for d in trash] == ["Protokoll JHV"]
        # im Papierkorb nicht abrufbar
        assert c.get(doc["current"]["url"]).status_code == 404
        assert c.post(f"{b}{doc['id']}/restore/").status_code == 200
        assert len(overview(c, b)["folders"][0]["documents"]) == 1
        c.delete(f"{b}{doc['id']}/")
        assert c.delete(f"{b}{doc['id']}/?final=1").status_code == 204
        assert not Document.objects.exists()

    def test_rueckgaengig(self, setup, board_a, api):
        c = api(board_a)
        b = base(setup["a"])
        f = folder(c, b)
        doc = upload(c, b, f["id"])
        resp = c.delete(f"{b}{doc['id']}/")
        assert resp["X-Change-Undoable"] == "1"
        undo = c.post(
            f"/api/orgs/{setup['a'].pk}/changes/{resp['X-Change-Set']}/undo/",
            {},
            content_type=JSON,
        )
        assert undo.status_code == 200, undo.content
        assert Document.objects.get().deleted_at is None

    def test_aufraeumen(self, setup, board_a, api):
        c = api(board_a)
        b = base(setup["a"])
        f = folder(c, b)
        doc = upload(c, b, f["id"])
        c.post(f"{b}{doc['id']}/versions/", {"file": pdf("v2.pdf")})
        old = DocumentVersion.objects.get(name="protokoll.pdf")
        storage = old.file.storage
        path = old.file.name
        old.delete()  # z. B. Fassung gelöscht: Datei bleibt zunächst
        assert storage.exists(path)
        Document.objects.update(deleted_at=timezone.now() - datetime.timedelta(days=31))
        later = timezone.now() + datetime.timedelta(days=31)
        assert services.purge(later) >= 1
        assert not Document.objects.exists()
        assert not storage.exists(path)


class TestFreigaben:
    def test_dachverband_an_vereine(self, setup, board_fed, board_a, board_c, api):
        fb = base(setup["federation"])
        cf = api(board_fed)
        shared = folder(cf, fb, "Rundschreiben", "clubs")
        internal = folder(cf, fb, "Vorstand", "board")
        upload(cf, fb, shared["id"], "Meldebogen")
        upload(cf, fb, internal["id"], "Intern")
        data = overview(api(board_a), base(setup["a"]))
        assert [s["name"] for s in data["shared"]] == ["Rundschreiben"]
        assert data["shared"][0]["from"] == "Testbund"
        doc = data["shared"][0]["documents"][0]
        resp = api(board_a).get(doc["current"]["url"])
        assert resp.status_code == 200
        # Verein kann es nicht ändern
        assert api(board_a).delete(f"{base(setup['a'])}{doc['id']}/").status_code == 404
        # Verein ohne Dachverband sieht nichts
        assert overview(api(board_c), base(setup["c"]))["shared"] == []

    def test_abteilung(self, setup, board_a, zug, api):
        # Abteilungsbereich: lesen mit jeder Rolle, verwalten mit Recht
        m, user, _ = member_with_access(setup["a"], "Olaf", depts=[zug])
        dept_role(zug, m, [DEPT_MEMBERS_VIEW])
        d = api(user)
        db = f"/api/depts/{zug.pk}/documents/"
        m2, user2, _ = member_with_access(setup["a"], "Lea", depts=[zug])
        dept_role(zug, m2, [DEPT_MEMBERS_VIEW, DEPT_DOCS_MANAGE])
        d2 = api(user2)
        f = folder(d2, db, "Zugprotokolle")
        upload(d2, db, f["id"], "Zugversammlung")
        assert Folder.objects.get(pk=f["id"]).department == zug
        data = overview(d, db)
        assert data["can_manage"] is False
        assert data["share_up_label"].startswith("Für den Vorstand des Vereins")
        assert data["folders"][0]["documents"][0]["title"] == "Zugversammlung"
        assert d.post(f"{db}folders/", {"name": "x"}, content_type=JSON).status_code == 403

    def test_verein_sieht_abteilung_nur_mit_freigabe(self, setup, board_a, zug, api):
        m, user, _ = member_with_access(setup["a"], "Lea", depts=[zug])
        dept_role(zug, m, [DEPT_MEMBERS_VIEW, DEPT_DOCS_MANAGE])
        d = api(user)
        db = f"/api/depts/{zug.pk}/documents/"
        f = folder(d, db, "Zugprotokolle")
        doc = upload(d, db, f["id"], "Zugversammlung")
        c = api(board_a)
        b = base(setup["a"])
        data = overview(c, b)
        assert data["folders"] == [] and data["from_below"] == []
        assert c.get(doc["current"]["url"].replace(db, b)).status_code == 404
        # Vorstand kann Abteilungsordner nicht ändern
        assert (
            c.patch(f"{b}folders/{f['id']}/", {"name": "x"}, content_type=JSON).status_code == 404
        )
        assert c.delete(f"{b}{doc['id']}/").status_code == 404
        # Abteilung gibt nach oben frei
        resp = d.patch(f"{db}folders/{f['id']}/", {"shared_up": True}, content_type=JSON)
        assert resp.json()["shared_up"] is True
        data = overview(c, b)
        assert [x["name"] for x in data["from_below"]] == ["Zugprotokolle"]
        assert data["from_below"][0]["from"] == "Jägerzug"
        url = data["from_below"][0]["documents"][0]["current"]["url"]
        assert c.get(url).status_code == 200
        assert c.delete(f"{b}{doc['id']}/").status_code == 404
        # Freigabe zurücknehmen
        d.patch(f"{db}folders/{f['id']}/", {"shared_up": False}, content_type=JSON)
        assert overview(c, b)["from_below"] == []
        assert c.get(url).status_code == 404

    def test_dachverband_sieht_verein_nur_mit_freigabe(
        self, setup, board_a, board_c, board_fed, api
    ):
        b = base(setup["a"])
        c = api(board_a)
        assert overview(c, b)["share_up_label"].startswith("Für den Testbund")
        f = folder(c, b, "Meldungen")
        upload(c, b, f["id"], "Mitgliedermeldung")
        fb = base(setup["federation"])
        cf = api(board_fed)
        assert overview(cf, fb)["from_below"] == []
        c.patch(f"{b}folders/{f['id']}/", {"shared_up": True}, content_type=JSON)
        data = overview(cf, fb)
        assert data["from_below"][0]["from"] == "Verein A"
        assert cf.get(data["from_below"][0]["documents"][0]["current"]["url"]).status_code == 200
        # Dachverband selbst und Verein ohne Dachverband haben keine höhere Ebene
        assert overview(cf, fb)["share_up_label"] is None
        cc = api(board_c)
        assert overview(cc, base(setup["c"]))["share_up_label"] is None
        resp = cc.post(
            f"{base(setup['c'])}folders/", {"name": "x", "shared_up": True}, content_type=JSON
        )
        assert resp.json()["shared_up"] is False

    def test_mitgliederbereich(self, setup, board_a, zug, api):
        b = base(setup["a"])
        c = api(board_a)
        upload(c, b, folder(c, b, "Formulare", "members")["id"], "Antrag")
        upload(c, b, folder(c, b, "Intern", "board")["id"], "Geheim")
        mz, uz, _ = member_with_access(setup["a"], "Udo", depts=[zug])
        dept_role(zug, mz, [DEPT_MEMBERS_VIEW, DEPT_DOCS_MANAGE])
        db = f"/api/depts/{zug.pk}/documents/"
        upload(api(uz), db, folder(api(uz), db, "Zug", "members")["id"], "Zugformular")
        _, user, access = member_with_access(setup["a"], "Max")
        resp = api(user).get(f"/api/portal/{access.pk}/documents/")
        assert resp.status_code == 200
        titles = [d["title"] for f in resp.json()["folders"] for d in f["documents"]]
        assert titles == ["Antrag"]
        _, user2, access2 = member_with_access(setup["a"], "Zoe", depts=[zug])
        data = api(user2).get(f"/api/portal/{access2.pk}/documents/").json()
        titles = sorted(d["title"] for f in data["folders"] for d in f["documents"])
        assert titles == ["Antrag", "Zugformular"]
        url = data["folders"][0]["documents"][0]["current"]["url"]
        assert api(user2).get(url).status_code == 200
        secret = Document.objects.get(title="Geheim").versions.get()
        assert (
            api(user2).get(f"/api/portal/{access2.pk}/documents/versions/{secret.pk}/").status_code
            == 404
        )

    def test_oeffentlich(self, setup, board_a, api):
        b = base(setup["a"])
        c = api(board_a)
        f = folder(c, b, "Aufnahme", "public")
        doc = upload(c, b, f["id"], "Aufnahmeantrag")
        url = overview(c, b)["folders"][0]["public_url"]
        anon = Client()
        data = anon.get(url).json()
        assert data["documents"][0]["title"] == "Aufnahmeantrag"
        resp = anon.get(data["documents"][0]["url"])
        assert resp.status_code == 200 and body(resp).startswith(b"%PDF")
        # Sichtbarkeit zurücknehmen: Link sofort tot, Schlüssel bleibt
        c.patch(f"{b}folders/{f['id']}/", {"visibility": "members"}, content_type=JSON)
        assert anon.get(url).status_code == 404
        c.patch(f"{b}folders/{f['id']}/", {"visibility": "public"}, content_type=JSON)
        assert anon.get(url).status_code == 200
        c.delete(f"{b}{doc['id']}/")
        assert anon.get(url).json()["documents"] == []


def test_api_unter_rls(setup, board_a, board_b, board_fed, zug, api):
    """Ende-zu-Ende in der eingeschränkten Rolle: Vorstand, Dachverband, Abteilung, Mitglied."""
    from django.db import connection

    from core.rls import APP_ROLE
    from core.tenancy import set_rls

    if connection.vendor != "postgresql":
        pytest.skip("nur PostgreSQL")
    m, member, access = member_with_access(setup["a"], "Erika", depts=[zug])
    dept_role(zug, m, [DEPT_MEMBERS_VIEW, DEPT_DOCS_MANAGE])
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {APP_ROLE}")
    try:
        fb = base(setup["federation"])
        upload(api(board_fed), fb, folder(api(board_fed), fb, "Rundschreiben", "clubs")["id"])
        upload(api(board_fed), fb, folder(api(board_fed), fb, "Intern")["id"], "Intern")
        ab = base(setup["a"])
        upload(api(board_a), ab, folder(api(board_a), ab, "Formulare", "members")["id"], "Antrag")
        db = f"/api/depts/{zug.pk}/documents/"
        upload(api(member), db, folder(api(member), db, "Zug", "members")["id"], "Zugantrag")
        data = overview(api(board_a), ab)
        assert [f["name"] for f in data["folders"]] == ["Formulare"]
        assert [f["name"] for f in data["shared"]] == ["Rundschreiben"]
        shared_url = data["shared"][0]["documents"][0]["current"]["url"]
        assert api(board_a).get(shared_url).status_code == 200
        assert overview(api(board_b), base(setup["b"]))["folders"] == []
        # Freigabe nach oben: Dachverband liest nur freigegebene Vereinsordner
        assert overview(api(board_fed), fb)["from_below"] == []
        up = folder(api(board_a), ab, "Meldungen")
        upload(api(board_a), ab, up["id"], "Meldung")
        api(board_a).patch(f"{ab}folders/{up['id']}/", {"shared_up": True}, content_type=JSON)
        below = overview(api(board_fed), fb)["from_below"]
        assert [f["name"] for f in below] == ["Meldungen"]
        assert api(board_fed).get(below[0]["documents"][0]["current"]["url"]).status_code == 200
        assert overview(api(board_b), base(setup["b"]))["shared"][0]["name"] == "Rundschreiben"
        portal = api(member).get(f"/api/portal/{access.pk}/documents/").json()
        titles = sorted(d["title"] for f in portal["folders"] for d in f["documents"])
        assert titles == ["Antrag", "Zugantrag"]
        zug_doc = portal["folders"][1]["documents"][0]["id"]
        assert api(member).delete(f"{db}{zug_doc}/").status_code == 204
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
        set_rls(None, None, False)
