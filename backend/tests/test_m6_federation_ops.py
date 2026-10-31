"""Meilenstein 6: Dachverbandszugriff, frühere Mitgliedschaften, E-Mail."""

import re

import pytest
from django.core import mail

from access.models import Role
from audit.models import AuditEntry
from members.models import Membership

from .conftest import csrf_headers
from .factories import give_role, make_user
from .test_m2_members import admit, make_types

pytestmark = pytest.mark.django_db
JSON = "application/json"
AUTH = "/_allauth/browser/v1"


@pytest.fixture(autouse=True)
def _eager(settings, tmp_path):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def types(orgs):
    return {key: make_types(orgs[key]) for key in ("a", "b", "c")}


@pytest.fixture
def board_fed(orgs):
    user = make_user("verband@example.org")
    give_role(user, orgs["federation"])
    return user


@pytest.fixture
def members(api, orgs, types, board_a, board_b, board_c):
    a = admit(api(board_a), orgs["a"], types["a"]["aktiv"], last_name="Adler").json()
    admit(api(board_b), orgs["b"], types["b"]["passiv"], last_name="Berg", birth_date="1970-01-01")
    admit(api(board_c), orgs["c"], types["c"]["aktiv"], last_name="Christ", birth_date="1960-01-01")
    return a


def set_access(orgs, value):
    orgs["federation"].federation_member_access = value
    orgs["federation"].save()


class TestDachverbandszugriff:
    url = "/api/orgs/{}/federation/members/"

    def test_ohne_freigabe_kein_zugriff(self, api, orgs, members, board_fed):
        set_access(orgs, "none")
        resp = api(board_fed).get(self.url.format(orgs["federation"].pk))
        assert resp.status_code == 403

    def test_lesen_alle_vereine_mit_spalte_verein(self, api, orgs, members, board_fed):
        set_access(orgs, "read")
        data = api(board_fed).get(self.url.format(orgs["federation"].pk)).json()
        rows = [(r["last_name"], r["club"]) for r in data["results"]]
        assert rows == [("Adler", "Verein A"), ("Berg", "Verein B")]  # nicht Verein C
        assert data["results"][0]["email"] == "erika@example.org"
        # Zugriff protokolliert
        assert AuditEntry.objects.filter(organization=orgs["federation"], action="view").exists()

    def test_filter_nach_verein_und_kennzeichen(self, api, orgs, members, board_fed):
        set_access(orgs, "read")
        c = api(board_fed)
        url = self.url.format(orgs["federation"].pk)
        assert c.get(url, {"verein": orgs["b"].pk}).json()["count"] == 1
        assert [r["last_name"] for r in c.get(url, {"aktiv": "1"}).json()["results"]] == ["Adler"]

    def test_einzelansicht_protokolliert_im_verein(self, api, orgs, members, board_fed):
        set_access(orgs, "read")
        detail = api(board_fed).get(f"{self.url.format(orgs['federation'].pk)}{members['id']}/")
        assert detail.status_code == 200
        assert detail.json()["club"] == "Verein A"
        assert detail.json()["readonly"] is True
        entry = AuditEntry.objects.get(organization=orgs["a"], action="view")
        assert entry.changes["Zugriff durch Dachverband"][1] == "Testbund"

    def test_nur_lesen_kein_aendern(self, api, orgs, members, board_fed):
        set_access(orgs, "read")
        resp = api(board_fed).patch(
            f"{self.url.format(orgs['federation'].pk)}{members['id']}/",
            {"city": "Verbandsstadt"},
            content_type=JSON,
        )
        assert resp.status_code == 403

    def test_lesen_und_aendern(self, api, orgs, members, board_fed):
        set_access(orgs, "write")
        resp = api(board_fed).patch(
            f"{self.url.format(orgs['federation'].pk)}{members['id']}/",
            {"city": "Verbandsstadt"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["contact"]["city"] == "Verbandsstadt"
        assert AuditEntry.objects.filter(organization=orgs["a"], action="update").exists()

    def test_aenderung_rueckgaengig(self, api, orgs, members, board_fed):
        set_access(orgs, "write")
        c = api(board_fed)
        url = f"{self.url.format(orgs['federation'].pk)}{members['id']}/"
        resp = c.patch(url, {"city": "Verbandsstadt"}, content_type=JSON)
        assert resp["X-Change-Undoable"] == "1"
        resp = c.post(
            f"/api/orgs/{orgs['federation'].pk}/changes/{resp['X-Change-Set']}/undo/",
            {},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        assert c.get(url).json()["contact"]["city"] == members["contact"]["city"]

    def test_fremder_verband_kein_zugriff(self, api, orgs, members, board_c):
        # Verein C hat keinen Zugriff auf die Dachverbandsansicht
        resp = api(board_c).get(self.url.format(orgs["federation"].pk))
        assert resp.status_code == 404

    def test_export_mit_spalte_verein(self, api, orgs, members, board_fed):
        set_access(orgs, "read")
        c = api(board_fed)
        base = f"/api/orgs/{orgs['federation'].pk}"
        resp = c.post(
            f"{base}/exports/",
            {
                "kind": "federation_members",
                "file_format": "xlsx",
                "columns": ["club", "last_name", "member_number"],
                "filters": {"status": "alle"},
            },
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        job = c.get(f"{base}/exports/{resp.json()['id']}/").json()
        assert job["status"] == "done", job
        assert job["row_count"] == 2
        none = c.post(
            f"{base}/exports/", {"kind": "members", "file_format": "xlsx"}, content_type=JSON
        )
        assert none.status_code == 400


class TestFruehereMitgliedschaften:
    def test_nur_mit_freigabe(self, api, orgs, types, members, board_a, board_b):
        b = (
            api(board_b)
            .post(
                f"/api/orgs/{orgs['b'].pk}/members/admit/",
                {
                    "person": members["person_id"],
                    "member_type": types["b"]["passiv"].pk,
                    "entry_date": "2020-01-01",
                    "email": "e@example.org",
                    "street": "x",
                    "postal_code": "1",
                    "city": "y",
                },
                content_type=JSON,
            )
            .json()
        )
        assert b["other_memberships"] is None
        orgs["federation"].federation_show_former_memberships = True
        orgs["federation"].save()
        data = api(board_b).get(f"/api/orgs/{orgs['b'].pk}/members/{b['id']}/").json()
        assert data["other_memberships"] == [
            {"club": "Verein A", "entry_date": "2015-03-01", "exit_date": None}
        ]


class TestEmail:
    def test_einladung_fuer_neues_konto(self, api, orgs, board_a):
        role = Role.objects.get(organization=orgs["a"])
        resp = api(board_a).post(
            f"/api/orgs/{orgs['a'].pk}/assignments/",
            {"email": "neu@example.org", "role": role.pk},
            content_type=JSON,
        )
        assert resp.json()["invited"] is True
        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == ["neu@example.org"]
        assert "Verein A" in message.subject
        assert "/passwort-zuruecksetzen/" in message.body

    def test_passwort_vergessen_und_setzen(self, client, user, password):
        resp = client.post(
            f"{AUTH}/auth/password/request",
            {"email": "kassenwart@example.org"},
            content_type=JSON,
            headers=csrf_headers(client),
        )
        assert resp.status_code == 200, resp.content
        assert len(mail.outbox) == 1
        key = re.search(r"/passwort-zuruecksetzen/(\S+)", mail.outbox[0].body).group(1)
        resp = client.post(
            f"{AUTH}/auth/password/reset",
            {"key": key, "password": "Ganz-Neues-Passwort-42"},
            content_type=JSON,
            headers=csrf_headers(client),
        )
        assert resp.status_code in (200, 401), resp.content
        user.refresh_from_db()
        assert user.check_password("Ganz-Neues-Passwort-42")

    def test_einladungslink_setzt_passwort(self, client, db, django_user_model):
        from accounts.invitations import password_link

        new = django_user_model.objects.create_user(email="eingeladen@example.org", password=None)
        key = password_link(new).rsplit("/", 1)[1]
        resp = client.post(
            f"{AUTH}/auth/password/reset",
            {"key": key, "password": "Mein-Erstes-Passwort-7"},
            content_type=JSON,
            headers=csrf_headers(client),
        )
        assert resp.status_code in (200, 401), resp.content
        new.refresh_from_db()
        assert new.check_password("Mein-Erstes-Passwort-7")


def test_mitgliedschaften_unveraendert(members):
    assert Membership.objects.count() == 3


class TestSicherheit:
    def test_admin_anmeldung_fuehrt_zur_2fa_anmeldung(self, client, db):
        resp = client.get("/admin/login/")
        assert resp.status_code in (301, 302)
        assert resp["Location"] == "/anmelden"
        # Passwort-Login am Admin vorbei ist nicht möglich
        assert client.post("/admin/login/", {"username": "x", "password": "y"}).status_code in (
            301,
            302,
            403,
            405,
        )

    def test_excel_formeln_werden_entschaerft(self):
        from exchange.export import safe_cell

        formula = '=HYPERLINK("http://boese.example")'
        assert safe_cell(formula) == "'" + formula
        assert safe_cell("+49 123") == "'+49 123"
        assert safe_cell("Muster") == "Muster"
        assert safe_cell(42) == 42

    def test_pdf_mit_sonderzeichen(self, api, orgs, types, board_a):
        admit(api(board_a), orgs["a"], types["a"]["aktiv"], last_name="<b>Böse</b> & Co")
        c = api(board_a)
        resp = c.post(
            f"/api/orgs/{orgs['a'].pk}/exports/",
            {
                "kind": "members",
                "file_format": "pdf",
                "columns": ["last_name"],
                "filters": {"status": "alle"},
            },
            content_type=JSON,
        )
        job = c.get(f"/api/orgs/{orgs['a'].pk}/exports/{resp.json()['id']}/").json()
        assert job["status"] == "done", job
