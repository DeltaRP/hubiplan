"""Android-App, Schritt B2: Mitglieder bearbeiten, Freigaben und Ausweis prüfen in der App."""
# ruff: noqa: F811  (Fixtures als Parameter)

import datetime

import pytest

from audit.models import AuditEntry
from cards.models import MemberCard
from core.tenancy import tenant_context
from devices.admin_members import _mask, card_token
from members.models import MemberType
from portal.models import ChangeRequest

from .factories import give_role, make_member
from .test_app_devices import APP, app
from .test_app_verwaltung import admin_token, board  # noqa: F401
from .test_m12_events import JSON, cal, zug, zug2  # noqa: F401

pytestmark = pytest.mark.django_db
ADMIN = f"{APP}admin/u/"


@pytest.fixture
def base(cal):
    return f"{ADMIN}{cal['a'].pk}/"


@pytest.fixture
def anna(cal, zug):
    return make_member(cal["a"], "Anna", "Beispiel", departments=[zug])


class TestMitglieder:
    def test_liste_und_akte(self, admin_token, base, anna):
        c = app(admin_token)
        resp = c.get(f"{base}members/?suche=Anna")
        assert resp.status_code == 200, resp.json()
        assert any(row["id"] == anna.pk for row in resp.json()["results"])
        detail = c.get(f"{base}members/{anna.pk}/").json()
        assert detail["first_name"] == "Anna"

    def test_aendern_mit_protokoll_und_rueckgaengig(self, admin_token, base, anna, cal):
        c = app(admin_token)
        resp = c.patch(f"{base}members/{anna.pk}/", {"city": "Neustadt"}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["contact"]["city"] == "Neustadt"
        with tenant_context(cal["a"].pk):
            entry = AuditEntry.objects.filter(organization=cal["a"]).latest("id")
        assert entry.via == "App (Pixel 8)"
        set_id = resp["X-Change-Set"]
        assert resp["X-Change-Undoable"] == "1"
        undo = c.post(f"{base}changes/{set_id}/undo/", {}, content_type=JSON)
        assert undo.status_code == 200, undo.json()
        assert c.get(f"{base}members/{anna.pk}/").json()["contact"]["city"] == "Musterstadt"

    def test_browser_herkunft_bleibt_leer(self, board, anna, cal, api):
        resp = api(board["user"]).patch(
            f"/api/orgs/{cal['a'].pk}/members/{anna.pk}/", {"city": "Altdorf"}, content_type=JSON
        )
        assert resp.status_code == 200
        with tenant_context(cal["a"].pk):
            assert AuditEntry.objects.filter(organization=cal["a"]).latest("id").via == ""

    def test_nur_mit_vorstandsschluessel(self, board, base, anna, api):
        assert app(board["token"]).get(f"{base}members/").status_code == 401
        assert api(board["user"]).get(f"{base}members/").status_code == 401

    def test_fremde_einheit_und_fehlendes_recht(self, admin_token, cal, anna):
        c = app(admin_token)
        assert c.get(f"{ADMIN}{cal['b'].pk}/members/").status_code == 404
        # Foto freigeben braucht photos.manage
        resp = c.post(
            f"{ADMIN}{cal['a'].pk}/members/{anna.pk}/photo/approve/", {}, content_type=JSON
        )
        assert resp.status_code == 403

    def test_auswahllisten_nur_lesen(self, admin_token, base):
        c = app(admin_token)
        assert c.get(f"{base}member-types/").status_code == 200
        assert c.get(f"{base}departments/").status_code == 200
        resp = c.post(f"{base}member-types/", {"name": "neu"}, content_type=JSON)
        assert resp.status_code in (403, 405)


class TestFolgen:
    def test_mitgliedsart_vorschau_aendert_nichts(self, admin_token, base, anna, cal):
        with tenant_context(cal["a"].pk):
            passive = MemberType.objects.create(
                organization=cal["a"], name="passiv", active=False, reported=False
            )
        resp = app(admin_token).post(
            f"{base}members/{anna.pk}/preview/",
            {"action": "change_type", "member_type": passive.pk, "valid_from": "2027-01-01"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        items = resp.json()["consequences"]
        assert items[0] == "Ab 01.01.2027: aktiv → passiv"
        assert "Wird passives Mitglied." in items
        assert "Wird nicht mehr an Testbund gemeldet." in items
        with tenant_context(cal["a"].pk):
            assert anna.current_type(datetime.date(2027, 1, 2)).member_type.name == "aktiv"

    def test_austritt_vorschau(self, admin_token, base, anna, zug):
        resp = app(admin_token).post(
            f"{base}members/{anna.pk}/preview/",
            {"action": "exit", "exit_date": "2026-12-31", "exit_reason": "exit"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        items = resp.json()["consequences"]
        assert items[0].startswith("Austritt zum 31.12.2026")
        assert f"Zugehörigkeit zu {zug.display_name} endet." in items

    def test_wechsel_in_einem_schritt(self, admin_token, base, anna, zug, zug2):
        c = app(admin_token)
        preview = c.post(
            f"{base}members/{anna.pk}/preview/",
            {"action": "move", "department": zug2.pk, "valid_from": "2026-11-01"},
            content_type=JSON,
        ).json()
        assert preview["consequences"][0] == "Ab 01.11.2026: Jägerzug → Grenadiere"
        resp = c.post(
            f"{base}members/{anna.pk}/move/",
            {"department": zug2.pk, "valid_from": "2026-11-01"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        rows = {d["department_name"]: d for d in resp.json()["departments"]}
        assert rows["Jägerzug"]["valid_until"] == "2026-10-31"
        assert rows["Grenadiere"]["valid_from"] == "2026-11-01"
        # ein Rückgängig nimmt beides zurück
        undo = c.post(f"{base}changes/{resp['X-Change-Set']}/undo/", {}, content_type=JSON)
        assert undo.status_code == 200, undo.json()
        rows = c.get(f"{base}members/{anna.pk}/").json()["departments"]
        assert [(d["department_name"], d["valid_until"]) for d in rows] == [("Jägerzug", None)]

    def test_wechsel_in_dieselbe(self, admin_token, base, anna, zug):
        resp = app(admin_token).post(
            f"{base}members/{anna.pk}/move/",
            {"department": zug.pk, "valid_from": "2026-11-01"},
            content_type=JSON,
        )
        assert resp.status_code == 400


class TestFreigaben:
    def test_aenderungsmeldung_entscheiden(self, admin_token, base, board, cal):
        with tenant_context(cal["a"].pk):
            cr = ChangeRequest.objects.create(
                organization=cal["a"], membership=board["membership"], data={"city": "Neustadt"}
            )
        c = app(admin_token)
        tasks = c.get(f"{base}tasks/").json()["items"]
        assert tasks[0]["ref"] == cr.pk and tasks[0]["membership"] == board["membership"].pk
        listed = c.get(f"{base}change-requests/").json()
        assert listed[0]["id"] == cr.pk
        resp = c.post(f"{base}change-requests/{cr.pk}/decide/", {"accept": True}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        cr.refresh_from_db()
        assert cr.status == ChangeRequest.Status.ACCEPTED

    def test_foto_mit_recht(self, admin_token, base, anna, board, cal):
        give_role(board["user"], cal["a"], ["members.view", "photos.manage"], name="Fotos")
        resp = app(admin_token).post(
            f"{base}members/{anna.pk}/photo/approve/", {"decision": "reject"}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()


class TestAusweis:
    def test_pruefen(self, admin_token, base, anna, cal):
        with tenant_context(cal["a"].pk):
            card = MemberCard.objects.create(organization=cal["a"], membership=anna)
        c = app(admin_token)
        resp = c.post(
            f"{base}cards/check/",
            {"code": f"https://verein.example.org/ausweis/{card.token}"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        data = resp.json()
        assert data["status"] == "active" and data["membership"] == anna.pk
        assert data["first_name"] == "Anna" and "imprint_key" not in data

    def test_fremder_und_unbekannter_ausweis(self, admin_token, base, cal):
        other = make_member(cal["b"], "Bert", "Anders")
        with tenant_context(cal["b"].pk):
            card = MemberCard.objects.create(organization=cal["b"], membership=other)
        c = app(admin_token)
        data = c.post(f"{base}cards/check/", {"code": card.token}, content_type=JSON).json()
        assert data["status"] == "active" and data["membership"] is None
        data = c.post(f"{base}cards/check/", {"code": "gibtsnicht"}, content_type=JSON).json()
        assert data["status"] == "unknown"

    def test_schluessel_aus_adresse(self):
        assert card_token("https://x.de/ausweis/abc123?v=1#oben") == "abc123"
        assert card_token(" abc123 ") == "abc123"


def test_iban_gekuerzt():
    row = {"id": 1, "iban": "DE02120300000000202051", "iban_masked": "DE02 •••• 2051"}
    assert _mask([row])[0]["iban"] is None
    assert _mask({"count": 1, "results": [row]})["results"][0]["iban"] is None
    assert _mask(row)["iban_masked"] == "DE02 •••• 2051"


class TestAllesBearbeitbar:
    """B2b: Ehrungen, Zusatzfelder, Bankverbindung, Wiedereintritt, Aufnahme."""

    def test_aufnahme_mit_dublettenpruefung(self, admin_token, base, anna, cal):
        c = app(admin_token)
        dup = c.get(f"{base}members/duplicates/?name=Beispiel&vorname=Anna&geburtsdatum=1980-05-17")
        assert dup.status_code == 200, dup.json()
        assert dup.json()[0]["already_member_here"] is True
        with tenant_context(cal["a"].pk):
            aktiv = MemberType.objects.get(organization=cal["a"], name="aktiv")
        payload = {
            "first_name": "Max",
            "last_name": "Neu",
            "birth_date": "1990-01-02",
            "member_type": aktiv.pk,
            "entry_date": "2026-11-01",
            "street": "Weg 1",
            "postal_code": "12345",
            "city": "Musterstadt",
        }
        key = "2b0f2a4e-8d3e-4a3b-9a55-0c4b2f1e7a11"
        resp = c.post(f"{base}members/admit/", payload, content_type=JSON, HTTP_IDEMPOTENCY_KEY=key)
        assert resp.status_code == 201, resp.json()
        again = c.post(
            f"{base}members/admit/", payload, content_type=JSON, HTTP_IDEMPOTENCY_KEY=key
        )
        assert again.status_code == 200 and again.json()["id"] == resp.json()["id"]

    def test_ehrung_und_zusatzfeld(self, admin_token, base, anna, cal):
        from customfields.models import FieldDefinition
        from members.models import HonoraryTitle

        with tenant_context(cal["a"].pk):
            title = HonoraryTitle.objects.create(organization=cal["a"], name="Ehrenmitglied")
            field = FieldDefinition.objects.create(
                organization=cal["a"], label="Schuhgröße", key="schuh", field_type="number"
            )
        c = app(admin_token)
        assert c.get(f"{base}honorary-titles/").status_code == 200
        resp = c.post(
            f"{base}members/{anna.pk}/honorary-titles/",
            {"title": title.pk, "valid_from": "2026-10-01"},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        resp = c.put(
            f"{base}members/{anna.pk}/fields/",
            {"values": {str(field.pk): "43"}},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()[0]["value"] == 43

    def test_wiedereintritt(self, admin_token, base, anna, cal):
        c = app(admin_token)
        resp = c.post(
            f"{base}members/{anna.pk}/exit/",
            {"exit_date": "2026-01-31", "exit_reason": "exit"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        with tenant_context(cal["a"].pk):
            aktiv = MemberType.objects.get(organization=cal["a"], name="aktiv")
        resp = c.post(
            f"{base}members/{anna.pk}/reentry/",
            {"entry_date": "2026-10-01", "member_type": aktiv.pk},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["status"] == "active"

    def test_bankverbindung(self, admin_token, base, anna, board, cal):
        from billing import services as billing_services

        cal["a"].enabled_modules = ["members", "events", "billing"]
        cal["a"].save()
        with tenant_context(cal["a"].pk):
            cfg = billing_services.settings_for(cal["a"])
            cfg.sepa_enabled = True
            cfg.creditor_id = "DE98ZZZ09999999999"
            cfg.save()
        give_role(board["user"], cal["a"], ["billing.view", "billing.edit"], name="Kasse")
        c = app(admin_token)
        new = {
            "membership": anna.pk,
            "holder": "Anna Beispiel",
            "iban": "DE89370400440532013000",
            "signed_on": "2026-10-01",
        }
        first = c.post(f"{base}billing/mandates/", new, content_type=JSON)
        assert first.status_code == 201, first.json()
        assert first.json()["iban"] is None and first.json()["iban_masked"]
        preview = c.post(
            f"{base}members/{anna.pk}/preview/", {"action": "bank"}, content_type=JSON
        ).json()
        assert any("widerrufen" in item for item in preview["consequences"])
        second = c.post(
            f"{base}billing/mandates/",
            {**new, "iban": "DE02120300000000202051"},
            content_type=JSON,
        )
        assert second.status_code == 201, second.json()
        rows = c.get(f"{base}billing/mandates/?mitglied={anna.pk}").json()["results"]
        assert {r["status"] for r in rows} == {"active", "revoked"}
        assert all(r["iban"] is None for r in rows)
        full = c.get(f"{base}billing/mandates/?mitglied={anna.pk}&voll=1").json()["results"]
        assert {r["iban"] for r in full} == {"DE89370400440532013000", "DE02120300000000202051"}
