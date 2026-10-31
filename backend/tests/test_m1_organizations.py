"""Meilenstein 1: Organisationen, Rollen, Rechte, Erscheinungsbild, Protokoll."""

import datetime
import io

import pytest
from PIL import Image

from access.catalog import MEMBERS_VIEW, ORG_EDIT, ROLES_MANAGE
from access.models import Role, RoleAssignment
from audit.models import AuditEntry
from organizations.models import Department, Organization, PlatformSettings
from organizations.theme import check_accent, check_primary, contrast, text_color_on

from .factories import give_role, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"


def png_file(name="logo.png"):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(buf, "PNG")
    buf.seek(0)
    buf.name = name
    return buf


class TestOrganisationsbaum:
    def test_plattform_existiert_genau_einmal(self):
        assert Organization.objects.filter(type="platform").count() == 1
        assert Organization.platform().type == "platform"

    def test_verein_im_dachverband(self, orgs):
        assert orgs["a"].federation == orgs["federation"]
        assert orgs["c"].federation is None
        assert orgs["c"].parent == Organization.platform()

    def test_kette_bis_zur_plattform(self, orgs):
        names = [o.name for o in orgs["a"].ancestors()]
        assert names == ["Verein A", "Testbund", "HUBIplan"]


class TestMeineOrganisationen:
    def test_liste_und_rechte(self, api, orgs, board_a):
        give_role(board_a, orgs["federation"], [ORG_EDIT], name="Beisitzer")
        data = api(board_a).get("/api/me/organizations/").json()
        assert [o["name"] for o in data] == ["Testbund", "Verein A"]
        verein = data[1]
        assert ROLES_MANAGE in verein["permissions"]
        assert verein["modules"] == ["members"]
        assert verein["theme"]["primary"].startswith("#")
        assert data[0]["permissions"] == [ORG_EDIT]

    def test_abgelaufene_rolle_zaehlt_nicht(self, api, orgs):
        user = make_user("ex@example.org")
        give_role(user, orgs["a"], valid_until=datetime.date(2021, 1, 1))
        assert api(user).get("/api/me/organizations/").json() == []

    def test_kuenftige_rolle_zaehlt_noch_nicht(self, api, orgs):
        user = make_user("bald@example.org")
        give_role(user, orgs["a"], valid_from=datetime.date.today() + datetime.timedelta(days=3))
        assert api(user).get("/api/me/organizations/").json() == []

    def test_superuser_hat_plattform(self, api, db, django_user_model):
        admin = django_user_model.objects.create_superuser(email="root@example.org", password="x")
        data = api(admin).get("/api/me/organizations/").json()
        assert data[0]["type"] == "platform"
        assert "platform.manage" in data[0]["permissions"]


class TestMandantentrennungApi:
    """Verein A darf nichts von Verein B sehen oder ändern."""

    def test_fremde_organisation_unsichtbar(self, api, orgs, board_a):
        c = api(board_a)
        assert c.get(f"/api/orgs/{orgs['a'].pk}/").status_code == 200
        assert c.get(f"/api/orgs/{orgs['b'].pk}/").status_code == 404
        assert c.get(f"/api/orgs/{orgs['b'].pk}/roles/").status_code == 404
        assert c.get(f"/api/orgs/{orgs['b'].pk}/departments/").status_code == 404
        resp = c.patch(f"/api/orgs/{orgs['b'].pk}/", {"name": "gekapert"}, content_type=JSON)
        assert resp.status_code == 404
        orgs["b"].refresh_from_db()
        assert orgs["b"].name == "Verein B"

    def test_listen_nur_eigene_daten(self, api, orgs, board_a, board_b):
        Department.objects.create(organization=orgs["a"], name="Turnen", founding_year=1950)
        Department.objects.create(organization=orgs["b"], name="Fußball", founding_year=1960)
        deps = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/departments/").json()
        assert [d["name"] for d in deps] == ["Turnen"]
        roles = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/roles/").json()
        assert all(r["name"] == "Vorstand" for r in roles) and len(roles) == 1
        assignments = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/assignments/").json()
        assert [a["user_email"] for a in assignments] == ["vorstand-a@example.org"]

    def test_fremde_rolle_nicht_zuweisbar(self, api, orgs, board_a, board_b):
        role_b = Role.objects.get(organization=orgs["b"])
        resp = api(board_a).post(
            f"/api/orgs/{orgs['a'].pk}/assignments/",
            {"email": "x@example.org", "role": role_b.pk},
            content_type=JSON,
        )
        assert resp.status_code == 400
        assert not RoleAssignment.objects.filter(role=role_b, user__email="x@example.org").exists()

    def test_fremde_abteilung_nicht_nutzbar(self, api, orgs, board_a):
        dep_b = Department.objects.create(organization=orgs["b"], name="Schach", founding_year=1990)
        resp = api(board_a).post(
            f"/api/orgs/{orgs['a'].pk}/department-roles/",
            {"department": dep_b.pk, "name": "Leitung"},
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_dachverband_sieht_vereinsrollen_nicht(self, api, orgs, board_a):
        fed_user = make_user("verband@example.org")
        give_role(fed_user, orgs["federation"])
        assert api(fed_user).get(f"/api/orgs/{orgs['a'].pk}/roles/").status_code == 404


class TestBerechtigungen:
    def test_ohne_recht_kein_schreiben(self, api, orgs):
        user = make_user("leser@example.org")
        give_role(user, orgs["a"], [MEMBERS_VIEW], name="Leser")
        c = api(user)
        assert c.get(f"/api/orgs/{orgs['a'].pk}/").status_code == 200
        resp = c.patch(f"/api/orgs/{orgs['a'].pk}/", {"name": "neu"}, content_type=JSON)
        assert resp.status_code == 403
        assert c.get(f"/api/orgs/{orgs['a'].pk}/roles/").status_code == 403
        assert c.get(f"/api/orgs/{orgs['a'].pk}/audit/").status_code == 403

    def test_rolle_mit_unbekannter_berechtigung(self, api, orgs, board_a):
        resp = api(board_a).post(
            f"/api/orgs/{orgs['a'].pk}/roles/",
            {"name": "Admin", "permissions": ["platform.manage"]},
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_rolle_anlegen_und_zuordnen(self, api, orgs, board_a):
        c = api(board_a)
        role = c.post(
            f"/api/orgs/{orgs['a'].pk}/roles/",
            {"name": "Kassierer", "permissions": [MEMBERS_VIEW, "export.run"]},
            content_type=JSON,
        ).json()
        resp = c.post(
            f"/api/orgs/{orgs['a'].pk}/assignments/",
            {"email": "Neu@Example.org", "role": role["id"], "valid_from": "2024-01-01"},
            content_type=JSON,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["user_email"] == "neu@example.org"
        # Neues Konto ohne Startpasswort: Einladung per Mail (Gesamtaudit 31.10.b, Frage 2)
        assert data["new_account"] is True and "initial_password" not in data
        assert not RoleAssignment.objects.get(pk=data["id"]).user.has_usable_password()
        # Neues Konto kann sich anmelden und sieht den Verein
        new_user = RoleAssignment.objects.get(pk=data["id"]).user
        orgs_seen = api(new_user).get("/api/me/organizations/").json()
        assert orgs_seen[0]["permissions"] == ["export.run", MEMBERS_VIEW]

    def test_bestehendes_konto_kein_neues_passwort(self, api, orgs, board_a, board_b):
        role = Role.objects.get(organization=orgs["a"])
        resp = api(board_a).post(
            f"/api/orgs/{orgs['a'].pk}/assignments/",
            {"email": "vorstand-b@example.org", "role": role.pk},
            content_type=JSON,
        )
        assert resp.json()["new_account"] is False

    def test_rollenzeitraum_beenden(self, api, orgs, board_a):
        other = make_user("zweiter@example.org")
        assignment = give_role(other, orgs["a"])
        resp = api(board_a).patch(
            f"/api/orgs/{orgs['a'].pk}/assignments/{assignment.pk}/",
            {"valid_until": "2021-12-31"},
            content_type=JSON,
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        assert api(other).get("/api/me/organizations/").json() == []

    def test_vergebene_rolle_loeschen_entzieht_sie(self, api, orgs, board_a):
        other = make_user("kassierer@example.org")
        assignment = give_role(other, orgs["a"], permissions=[MEMBERS_VIEW], name="Kassierer")
        role = assignment.role
        resp = api(board_a).delete(f"/api/orgs/{orgs['a'].pk}/roles/{role.pk}/")
        assert resp.status_code == 204
        assert not Role.objects.filter(pk=role.pk).exists()
        assert not RoleAssignment.objects.filter(pk=assignment.pk).exists()
        assert api(other).get("/api/me/organizations/").json() == []
        entry = AuditEntry.objects.get(object_type="Rollenzuordnung", action="delete")
        assert entry.object_id == str(assignment.pk)

    def test_eigene_rollenverwaltung_nicht_loeschbar(self, api, orgs, board_a):
        role = Role.objects.get(organization=orgs["a"])
        resp = api(board_a).delete(f"/api/orgs/{orgs['a'].pk}/roles/{role.pk}/")
        assert resp.status_code == 400
        assert "selbst" in str(resp.json())
        assert Role.objects.filter(pk=role.pk).exists()

    def test_eigene_rolle_loeschbar_wenn_recht_anderweitig(self, api, orgs, board_a):
        extra = give_role(board_a, orgs["a"], name="Zweitvorstand")
        resp = api(board_a).delete(f"/api/orgs/{orgs['a'].pk}/roles/{extra.role.pk}/")
        assert resp.status_code == 204


class TestOrganisationsdaten:
    def test_pflichtfelder(self, api, orgs, board_a):
        resp = api(board_a).patch(f"/api/orgs/{orgs['a'].pk}/", {"city": ""}, content_type=JSON)
        assert resp.status_code == 400
        assert "city" in resp.json()

    def test_kontakt_von_rolle(self, api, orgs, board_a):
        role = Role.objects.get(organization=orgs["a"])
        resp = api(board_a).patch(
            f"/api/orgs/{orgs['a'].pk}/",
            {"contact_source": "role", "contact_role": role.pk},
            content_type=JSON,
        )
        assert resp.status_code == 200
        contact = resp.json()["contact_effective"]
        assert contact["source"] == "role"
        assert contact["email"] == "vorstand-a@example.org"

    def test_kontakt_rolle_aus_fremdem_verein(self, api, orgs, board_a, board_b):
        role_b = Role.objects.get(organization=orgs["b"])
        resp = api(board_a).patch(
            f"/api/orgs/{orgs['a'].pk}/",
            {"contact_source": "role", "contact_role": role_b.pk},
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_abteilungen_mit_eigener_bezeichnung(self, api, orgs, board_a):
        c = api(board_a)
        c.patch(
            f"/api/orgs/{orgs['a'].pk}/",
            {
                "department_label": "Sparte",
                "department_label_plural": "Sparten",
                "allow_multiple_departments": False,
            },
            content_type=JSON,
        )
        dep = c.post(
            f"/api/orgs/{orgs['a'].pk}/departments/",
            {"name": "Leichtathletik", "founding_year": 1975},
            content_type=JSON,
        ).json()
        c.post(
            f"/api/orgs/{orgs['a'].pk}/department-roles/",
            {"department": dep["id"], "name": "Spartenleiter"},
            content_type=JSON,
        )
        deps = c.get(f"/api/orgs/{orgs['a'].pk}/departments/").json()
        assert deps[0]["roles"][0]["name"] == "Spartenleiter"
        me = c.get("/api/me/organizations/").json()[0]
        assert me["department_label_plural"] == "Sparten"

    def test_dachverband_hat_keine_abteilungen(self, api, orgs):
        user = make_user("verband@example.org")
        give_role(user, orgs["federation"])
        assert api(user).get(f"/api/orgs/{orgs['federation'].pk}/departments/").status_code == 404


class TestErscheinungsbild:
    def test_kontrast(self):
        assert contrast("#ffffff", "#000000") == pytest.approx(21, rel=0.01)
        assert text_color_on("#1f6f5c") == "#ffffff"
        assert text_color_on("#f5d90a") == "#1d2421"
        assert check_primary("#1f6f5c") == []
        assert check_primary("#ffff66")  # zu hell für Links auf Weiß
        assert check_accent("#e0a526") == []

    def test_vererbung(self, api, orgs, board_a):
        orgs["federation"].primary_color = "#7a1f1f"
        orgs["federation"].save()
        theme = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/theme/").json()
        assert theme["primary_color"] == ""
        assert theme["effective"]["primary"] == "#7a1f1f"
        assert theme["effective"]["inherited_from"]["colors"] == "Testbund"

    def test_eigene_farbe_und_pruefung(self, api, orgs, board_a):
        c = api(board_a)
        url = f"/api/orgs/{orgs['a'].pk}/theme/"
        assert c.patch(url, {"primary_color": "#FFFF66"}, content_type=JSON).status_code == 400
        resp = c.patch(url, {"primary_color": "#123E7A"}, content_type=JSON)
        assert resp.status_code == 200
        assert resp.json()["effective"]["primary"] == "#123e7a"
        assert resp.json()["effective"]["on_primary"] == "#ffffff"

    def test_logo_hochladen_und_entfernen(self, api, orgs, board_a):
        c = api(board_a)
        url = f"/api/orgs/{orgs['a'].pk}/logo/"
        resp = c.post(url, {"logo": png_file()})
        assert resp.status_code == 200
        assert resp.json()["logo_url"].startswith("/media/logos/")
        me = c.get("/api/me/organizations/").json()[0]
        assert me["theme"]["logo_url"] == resp.json()["logo_url"]
        assert c.delete(url).status_code == 204
        orgs["a"].refresh_from_db()
        assert not orgs["a"].logo

    def test_logo_nur_bilder(self, api, orgs, board_a):
        fake = io.BytesIO(b"<svg onload=alert(1)>")
        fake.name = "logo.svg"
        resp = api(board_a).post(f"/api/orgs/{orgs['a'].pk}/logo/", {"logo": fake})
        assert resp.status_code == 400


class TestPlattform:
    @pytest.fixture
    def platform_admin(self, db, django_user_model):
        return django_user_model.objects.create_superuser(email="admin@example.org", password="x")

    def test_nur_fuer_plattform(self, api, orgs, board_a):
        assert api(board_a).get("/api/platform/orgs/").status_code == 403

    def test_verein_anlegen_mit_vorstandsrolle(self, api, orgs, platform_admin):
        c = api(platform_admin)
        resp = c.post(
            "/api/platform/orgs/",
            {
                "type": "club",
                "federation": orgs["federation"].pk,
                "name": "Neuer Verein",
                "founding_year": 2001,
                "street": "Weg 2",
                "postal_code": "54321",
                "city": "Neustadt",
            },
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        new = Organization.objects.get(name="Neuer Verein")
        assert new.parent == orgs["federation"]
        assert set(new.enabled_modules) == {"members", "finance", "billing", "events"}
        assert Role.objects.filter(organization=new, name="Vorstand").exists()

        resp = c.post(
            f"/api/platform/orgs/{new.pk}/board/", {"email": "chef@example.org"}, content_type=JSON
        )
        assert resp.status_code == 201
        assert resp.json()["new_account"] is True
        chef = RoleAssignment.objects.get(user__email="chef@example.org").user
        assert api(chef).get(f"/api/orgs/{new.pk}/roles/").status_code == 200

    def test_verein_ohne_dachverband(self, api, platform_admin, db):
        resp = api(platform_admin).post(
            "/api/platform/orgs/",
            {
                "type": "club",
                "name": "Freier Verein",
                "founding_year": 1999,
                "street": "Weg 3",
                "postal_code": "11111",
                "city": "Dorf",
            },
            content_type=JSON,
        )
        assert resp.status_code == 201
        assert resp.json()["federation"] is None
        assert Organization.objects.get(name="Freier Verein").parent.type == "platform"

    def test_schalter_je_dachverband(self, api, orgs, platform_admin):
        resp = api(platform_admin).patch(
            f"/api/platform/orgs/{orgs['federation'].pk}/",
            {"federation_member_access": "read", "federation_show_former_memberships": True},
            content_type=JSON,
        )
        assert resp.status_code == 200
        orgs["federation"].refresh_from_db()
        assert orgs["federation"].federation_member_access == "read"

    def test_module_schaltbar(self, api, orgs, platform_admin):
        c = api(platform_admin)
        url = f"/api/platform/orgs/{orgs['a'].pk}/"
        assert c.patch(url, {"enabled_modules": ["kasse"]}, content_type=JSON).status_code == 400
        assert c.patch(url, {"enabled_modules": []}, content_type=JSON).status_code == 200

    def test_globale_einstellungen(self, api, platform_admin):
        resp = api(platform_admin).patch(
            "/api/platform/settings/",
            {"person_data_mode": "per_club", "deletion_period_months": 36},
            content_type=JSON,
        )
        assert resp.status_code == 200
        assert PlatformSettings.load().deletion_period_months == 36


class TestProtokoll:
    def test_aenderungen_werden_protokolliert(self, api, orgs, board_a):
        c = api(board_a)
        c.patch(f"/api/orgs/{orgs['a'].pk}/", {"name": "Verein A 1900"}, content_type=JSON)
        c.post(f"/api/orgs/{orgs['a'].pk}/roles/", {"name": "Kassierer"}, content_type=JSON)
        entries = c.get(f"/api/orgs/{orgs['a'].pk}/audit/").json()["results"]
        assert entries[0]["object_type"] == "Rolle"
        assert entries[0]["action"] == "create"
        assert entries[1]["changes"]["Name"] == ["Verein A", "Verein A 1900"]
        assert entries[1]["user_email"] == "vorstand-a@example.org"
        # Protokoll von Verein B bleibt leer
        assert not AuditEntry.objects.filter(organization=orgs["b"]).exists()


def test_rollen_in_gezogener_reihenfolge(api, orgs, board_a):
    org = orgs["a"]
    Role.objects.create(organization=org, name="Zeugwart")
    Role.objects.create(organization=org, name="2. Vorsitzender", on_website=True)
    names = [r["name"] for r in api(board_a).get(f"/api/orgs/{org.pk}/roles/").json()]
    # Neue Rollen hinten angestellt
    assert names[-2:] == ["Zeugwart", "2. Vorsitzender"]
