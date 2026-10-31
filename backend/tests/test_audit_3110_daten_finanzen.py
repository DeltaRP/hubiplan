"""Audit Datenspeicherung und Berechnungen 31.10.: Zuwendungen, Quittungs-USt, Rückgängig."""
# ruff: noqa: F811  (Fixtures als Parameter)

from decimal import Decimal

import pytest

from audit.models import AuditEntry
from billing.services import included_vat
from core.tenancy import tenant_context
from finance.models import Donation

from .test_m9_billing import JSON, base, c, club, setup, zug  # noqa: F401
from .test_zuwendungen import _private, donate, ev, ready  # noqa: F401

pytestmark = pytest.mark.django_db


class TestFIN3105ProtokollDerAenderung:
    def test_betragsaenderung_steht_im_protokoll(self, ev, c, club):
        d = donate(c, ev)
        resp = c.patch(f"{ev}/donations/{d['id']}/", {"amount": "50.00"}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        with tenant_context(club.pk):
            entry = AuditEntry.objects.filter(
                action="update", object_id=str(d["id"]), object_type="donation"
            ).get()
            assert Donation.objects.get(pk=d["id"]).amount == Decimal("50.00")
        assert entry.changes["Betrag bzw. Wert"] == ["100.00", "50.00"]


class TestFIN3107RueckgaengigNachBestaetigung:
    def test_altes_aenderungspaket_aendert_bestaetigte_zuwendung_nicht(self, ready, c, club):
        d = donate(c, ready)
        change = c.patch(f"{ready}/donations/{d['id']}/", {"amount": "50.00"}, content_type=JSON)
        set_id = change["X-Change-Set"]
        issued = c.post(
            f"{ready}/donation-statements/", {"donations": [d["id"]]}, content_type=JSON
        )
        assert issued.status_code == 201, issued.json()
        org = ready.removesuffix("/finance")
        undo = c.post(f"{org}/changes/{set_id}/undo/", {"force": True}, content_type=JSON)
        assert undo.status_code == 409
        assert "bestätigt" in " ".join(undo.json()["problems"])
        with tenant_context(club.pk):
            assert Donation.objects.get(pk=d["id"]).amount == Decimal("50.00")


class TestFIN31R04Hoechstbetrag:
    def test_betrag_ab_einer_milliarde_abgelehnt(self, ev, c):
        resp = c.post(
            f"{ev}/donations/",
            {"date": "2026-01-15", "amount": "1000000000.00", "donor_name": "Max Muster"},
            content_type=JSON,
        )
        assert resp.status_code == 400 and "amount" in resp.json()


class TestFIN3106Rundung:
    @pytest.mark.parametrize(
        ("gross", "rate", "vat"),
        [("0.03", "20", "0.01"), ("119.00", "19", "19.00"), ("1.07", "7", "0.07")],
    )
    def test_halber_cent_wird_aufgerundet(self, gross, rate, vat):
        assert included_vat(Decimal(gross), Decimal(rate)) == Decimal(vat)
