"""Android-App, Schritt B5: offene Rechnungen suchen, bar kassieren, Quittung als PDF."""
# ruff: noqa: F811  (Fixtures als Parameter)

import uuid
from decimal import Decimal

import pytest

from audit.models import AuditEntry
from billing.models import Invoice, Payment
from core.tenancy import tenant_context
from finance.models import Booking

from .factories import give_role
from .test_app_devices import app
from .test_app_verwaltung_b4 import ADMIN, unlocked
from .test_m9_billing import JSON, base, c, club, members, setup, start_run, zug  # noqa: F401
from .test_m12_events import member_with_access

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def offen(c, base, members):
    """Festgeschriebener Beitragslauf: offene Rechnungen."""
    run = start_run(c, base).json()
    assert c.post(f"{base}/runs/{run['id']}/finalize/").status_code == 200
    return Invoice.objects.get(membership=members["erika"])


@pytest.fixture
def kassierer(club, api):
    _, user, _ = member_with_access(club, "Karl")
    give_role(user, club, ["billing.view", "billing.edit"], name="Kassierer")
    return {"c": app(unlocked(api, user)), "base": f"{ADMIN}u/{club.pk}/billing/", "user": user}


def bar(k, invoice, key=None, **data):
    return k["c"].post(
        f"{k['base']}invoices/{invoice.pk}/cash/",
        data,
        content_type=JSON,
        HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
    )


class TestBarzahlung:
    def test_offene_rechnungen_suchen(self, kassierer, offen):
        resp = kassierer["c"].get(f"{kassierer['base']}invoices/", {"offen": "1", "suche": "Erika"})
        assert resp.status_code == 200, resp.json()
        rows = resp.json()["results"]
        assert [r["id"] for r in rows] == [offen.pk]
        assert rows[0]["outstanding"] == "60.00"
        detail = kassierer["c"].get(f"{kassierer['base']}invoices/{offen.pk}/").json()
        assert detail["lines"] and detail["payments"] == []
        # Barkassen für die Auswahl
        settings = kassierer["c"].get(f"{kassierer['base']}settings/").json()
        assert "cash" in {a["kind"] for a in settings["accounts"]}

    def test_rechnungen_nur_lesen(self, kassierer, offen):
        url = f"{kassierer['base']}invoices/{offen.pk}/"
        assert kassierer["c"].patch(url, {"note": "x"}, content_type=JSON).status_code == 405
        assert kassierer["c"].delete(url).status_code == 405
        assert kassierer["c"].post(f"{url}cancel/").status_code in (403, 405)
        assert (
            kassierer["c"].patch(f"{kassierer['base']}settings/", {}, content_type=JSON).status_code
            == 405
        )

    def test_bar_kassieren_und_quittung(self, kassierer, offen, setup):
        resp = bar(kassierer, offen, amount="20.00", account=setup["cash"], date="2026-06-13")
        assert resp.status_code == 201, resp.json()
        body = resp.json()
        assert body["invoice"]["outstanding"] == "40.00"
        payment = Payment.objects.get(pk=body["payment"])
        assert payment.method == "cash"
        assert payment.booking.account_id == setup["cash"]
        assert payment.booking.amount == Decimal("20.00")
        with tenant_context(offen.organization_id):
            entry = AuditEntry.objects.filter(organization=offen.organization).latest("id")
        assert "Zahlung" in entry.changes and entry.via.startswith("App (")
        pdf = kassierer["c"].get(f"{kassierer['base']}payments/{payment.pk}/receipt/")
        assert pdf.status_code == 200
        assert pdf["Content-Type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF")
        assert "Quittung" in pdf["Content-Disposition"]
        # Ohne Betrag: der offene Rest, danach bezahlt
        resp = bar(kassierer, offen, account=setup["cash"])
        assert resp.status_code == 201, resp.json()
        assert resp.json()["invoice"]["status"] == "paid"

    def test_doppelt_gesendet_nur_einmal(self, kassierer, offen, setup):
        key = str(uuid.uuid4())
        first = bar(kassierer, offen, key, amount="10", account=setup["cash"])
        again = bar(kassierer, offen, key, amount="10", account=setup["cash"])
        assert first.status_code == 201
        assert again.status_code == 200
        assert again.json()["payment"] == first.json()["payment"]
        assert Payment.objects.count() == 1

    def test_ohne_schluessel_abgelehnt(self, kassierer, offen, setup):
        resp = kassierer["c"].post(
            f"{kassierer['base']}invoices/{offen.pk}/cash/",
            {"account": setup["cash"]},
            content_type=JSON,
        )
        assert resp.status_code == 400
        assert not Payment.objects.exists()

    def test_nur_in_die_barkasse(self, kassierer, offen, setup):
        resp = bar(kassierer, offen, account=setup["bank"])
        assert resp.status_code == 400
        assert "account" in resp.json()
        assert not Booking.objects.exists()

    def test_ueberzahlung_abgelehnt(self, kassierer, offen, setup):
        resp = bar(kassierer, offen, amount="61", account=setup["cash"])
        assert resp.status_code == 400
        assert not Payment.objects.exists()

    def test_entwurf_nicht_kassierbar(self, kassierer, c, base, members, setup):
        run = start_run(c, base).json()
        draft = Invoice.objects.filter(run_id=run["id"]).first()
        assert draft.status == "draft"
        assert bar(kassierer, draft, account=setup["cash"]).status_code == 400

    def test_ohne_schreibrecht(self, club, api, offen, setup):
        _, user, _ = member_with_access(club, "Lena")
        give_role(user, club, ["billing.view"], name="Prüfer")
        k = {"c": app(unlocked(api, user)), "base": f"{ADMIN}u/{club.pk}/billing/"}
        assert k["c"].get(f"{k['base']}invoices/").status_code == 200
        assert bar(k, offen, account=setup["cash"]).status_code == 403
        # Quittung lesen geht mit Leserecht
        assert not Payment.objects.exists()

    def test_andere_einheit(self, orgs, kassierer, offen, setup):
        other = f"{ADMIN}u/{orgs['b'].pk}/billing/"
        assert kassierer["c"].get(f"{other}invoices/").status_code in (403, 404)


def test_quittung_im_browser(c, base, offen, setup):
    resp = c.post(
        f"{base}/invoices/{offen.pk}/payments/",
        {"date": "2026-06-13", "method": "cash", "account": setup["cash"]},
        content_type=JSON,
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert resp.status_code == 200, resp.json()
    payment = Payment.objects.get()
    pdf = c.get(f"{base}/payments/{payment.pk}/receipt/?download=1")
    assert pdf.status_code == 200
    assert pdf["Content-Disposition"].startswith("attachment")
