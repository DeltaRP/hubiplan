"""Android-App, Schritt B4: Kasse mit Belegfoto und Verwaltung für Untereinheiten."""
# ruff: noqa: F811  (Fixtures als Parameter)

import uuid

import pytest
from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret
from django.core.files.uploadedfile import SimpleUploadedFile

from audit.models import AuditEntry
from core.tenancy import tenant_context
from finance.models import Booking

from .factories import PASSWORD, give_role, make_member
from .test_app_devices import APP, app, pair, pairing_code
from .test_app_verwaltung import fresh_code
from .test_m12_events import JSON, cal, dept_role, member_with_access, zug  # noqa: F401
from .test_m13_rsvp import soon

pytestmark = pytest.mark.django_db
ADMIN = f"{APP}admin/"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


def unlocked(api, user) -> str:
    """Gerät verbinden, 2FA einrichten, Verwaltung freischalten: Vorstandsschlüssel."""
    from django.core.cache import cache

    cache.clear()
    secret = generate_totp_secret()
    TOTP.activate(user, secret)
    token = pair(pairing_code(api(user))).json()["token"]
    resp = app(token).post(
        f"{ADMIN}unlock/", {"password": PASSWORD, "code": fresh_code(secret)}, content_type=JSON
    )
    assert resp.status_code == 201, resp.json()
    return resp.json()["token"]


@pytest.fixture
def kasse(cal, api):
    club = cal["a"]
    club.enabled_modules = ["members", "events", "finance"]
    club.save()
    _, user, _ = member_with_access(club, "Karl")
    give_role(user, club, ["finance.view", "finance.edit"], name="Kassierer")
    c = app(unlocked(api, user))
    base = f"{ADMIN}u/{club.pk}/finance/"
    # Konten und Kategorien richtet der Kassierer im Browser ein
    web = api(user)
    org = f"/api/orgs/{club.pk}/finance/"
    cash = web.post(
        f"{org}accounts/",
        {"name": "Barkasse", "kind": "cash", "opening_balance": "50", "opening_date": "2025-01-01"},
        content_type=JSON,
    ).json()["id"]
    fest = web.post(f"{org}categories/", {"name": "Schützenfest"}, content_type=JSON).json()["id"]
    return {"c": c, "base": base, "cash": cash, "fest": fest, "club": club, "user": user}


def buchen(k, key=None, **extra):
    key = key or str(uuid.uuid4())
    data = {
        "date": "2026-06-13",
        "kind": "expense",
        "amount": "23.40",
        "account": k["cash"],
        "category": k["fest"],
        "text": "Getränke",
        "file": SimpleUploadedFile("beleg.jpg", JPEG, content_type="image/jpeg"),
        **extra,
    }
    return k["c"].post(f"{k['base']}app-booking/", data, HTTP_IDEMPOTENCY_KEY=key)


class TestKasse:
    def test_lesen(self, kasse):
        c, base = kasse["c"], kasse["base"]
        accounts = c.get(f"{base}accounts/").json()
        assert [a["name"] for a in accounts] == ["Barkasse"]
        assert c.get(f"{base}categories/").status_code == 200
        assert c.get(f"{base}overview/").status_code == 200
        assert c.get(f"{base}bookings/").json()["count"] == 0

    def test_buchung_mit_beleg(self, kasse):
        resp = buchen(kasse)
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["display_number"] and data["receipts"][0]["name"] == "beleg.jpg"
        # Belege sind Dateien: wie im Browser kein „Rückgängig“ (Storno im Browser)
        assert resp["X-Change-Undoable"] == "0"
        with tenant_context(kasse["club"].pk):
            entry = AuditEntry.objects.filter(organization=kasse["club"]).latest("id")
        assert entry.via.startswith("App (")
        rid = data["receipts"][0]["id"]
        img = kasse["c"].get(f"{kasse['base']}receipts/{rid}/")
        assert img.status_code == 200
        assert b"".join(img.streaming_content).startswith(b"\xff\xd8")

    def test_entwurf_doppelt_gesendet_nur_einmal(self, kasse):
        key = str(uuid.uuid4())
        first = buchen(kasse, key=key)
        # gleicher Entwurf, neu geöffnete Datei
        again = buchen(kasse, key=key)
        assert first.status_code == again.status_code == 201
        assert first.json()["id"] == again.json()["id"]
        with tenant_context(kasse["club"].pk):
            assert Booking.objects.count() == 1

    def test_nur_mit_beleg_und_schluessel(self, kasse):
        resp = buchen(kasse, file="")
        assert resp.status_code == 400
        no_key = kasse["c"].post(
            f"{kasse['base']}app-booking/",
            {"date": "2026-06-13", "kind": "expense", "amount": "1", "account": kasse["cash"]},
        )
        assert no_key.status_code == 400

    def test_kein_aendern_oder_loeschen(self, kasse):
        pk = buchen(kasse).json()["id"]
        c, base = kasse["c"], kasse["base"]
        assert c.delete(f"{base}bookings/{pk}/").status_code == 405
        assert c.patch(f"{base}bookings/{pk}/", {}, content_type=JSON).status_code == 405
        assert c.post(f"{base}accounts/", {}, content_type=JSON).status_code == 405

    def test_beleg_nachreichen(self, kasse, api):
        browser = api(kasse["user"])
        org = f"/api/orgs/{kasse['club'].pk}/finance/"
        made = browser.post(
            f"{org}bookings/",
            {
                "date": "2026-06-13",
                "kind": "expense",
                "amount": "5",
                "account": kasse["cash"],
                "text": "Porto",
                "category": kasse["fest"],
            },
            content_type=JSON,
        )
        assert made.status_code == 201, made.json()
        pk = made.json()["id"]
        resp = kasse["c"].post(
            f"{kasse['base']}bookings/{pk}/receipts/",
            {"file": SimpleUploadedFile("nach.jpg", JPEG, content_type="image/jpeg")},
        )
        assert resp.status_code == 201, resp.json()
        open_ = kasse["c"].get(f"{kasse['base']}bookings/?ohne_beleg=1").json()
        assert open_["count"] == 0

    def test_kassenpruefer_nur_lesen(self, kasse, api):
        _, user, _ = member_with_access(kasse["club"], "Petra")
        give_role(user, kasse["club"], ["finance.view"], name="Kassenprüfer")
        c = app(unlocked(api, user))
        assert c.get(f"{kasse['base']}bookings/").status_code == 200
        kasse["c"] = c
        assert buchen(kasse).status_code == 403


class TestUntereinheit:
    @pytest.fixture
    def zugfuehrer(self, cal, zug, api):
        m, user, _ = member_with_access(cal["a"], "Zora", depts=[zug])
        dept_role(zug, m, ["dept.members.view", "dept.members.edit", "dept.events.manage"])
        return user

    def test_ueberblick_und_freischalten(self, zugfuehrer, zug, api):
        token = pair(pairing_code(api(zugfuehrer))).json()["token"]
        data = app(token).get(ADMIN).json()
        assert data["units"] == []
        assert [d["id"] for d in data["departments"]] == [zug.pk]
        assert "dept.events.manage" in data["departments"][0]["permissions"]
        assert unlocked(api, zugfuehrer).startswith("hpa_")

    def test_mitglieder_und_termine(self, zugfuehrer, zug, cal, api):
        anna = make_member(cal["a"], "Anna", "Beispiel", departments=[zug])
        make_member(cal["a"], "Fritz", "Fremd")  # nicht im Zug
        c = app(unlocked(api, zugfuehrer))
        base = f"{ADMIN}d/{zug.pk}/"
        assert c.get(base).json()["id"] == zug.pk
        names = [r["first_name"] for r in c.get(f"{base}members/").json()["results"]]
        assert "Anna" in names and "Fritz" not in names
        resp = c.patch(f"{base}members/{anna.pk}/", {"city": "Zugdorf"}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        undo = c.post(f"{base}changes/{resp['X-Change-Set']}/undo/", {}, content_type=JSON)
        assert undo.status_code == 200, undo.json()
        event = c.post(
            f"{base}events/",
            {"title": "Zugabend", "starts_at": soon(19), "rsvp_enabled": True},
            content_type=JSON,
        )
        assert event.status_code == 201, event.json()
        url = f"{base}events/{event.json()['id']}/responses/"
        put = c.put(url, {"membership_id": anna.pk, "status": "yes"}, content_type=JSON)
        assert put.status_code == 200, put.json()
        assert c.get(url).json()["summary"]["yes"] == 1

    def test_fremde_untereinheit_und_vereinspfad(self, zugfuehrer, cal, api):
        from organizations.models import Department

        other = Department.objects.create(
            self_managed=True, organization=cal["a"], name="Andere", founding_year=1
        )
        c = app(unlocked(api, zugfuehrer))
        assert c.get(f"{ADMIN}d/{other.pk}/members/").status_code == 404
        assert c.get(f"{ADMIN}u/{cal['a'].pk}/members/").status_code in (403, 404)
