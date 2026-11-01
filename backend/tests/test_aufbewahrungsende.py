"""Finanzamt-Prüfung C6: Belege nach 8, Bücher nach 10 Jahren bereinigen (erfundene Daten)."""
# ruff: noqa: F811  (Fixtures als Parameter)

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from audit.chain import seal, verify
from audit.models import AuditEntry
from core.tenancy import rls_bypass
from finance import retention
from finance.models import Booking, Receipt

from .test_e_rechnung import UBL
from .test_m9_billing import JSON, base, c, club, setup, zug  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def fin(club):
    return f"/api/orgs/{club.pk}/finance"


def heute(monkeypatch, day):
    monkeypatch.setattr(retention, "_today", lambda: day)


@pytest.fixture
def jahr2025(c, fin, setup):
    resp = c.post(
        f"{fin}/bookings/",
        {
            "date": "2025-03-01",
            "kind": "income",
            "amount": "25",
            "account": setup["bank"],
            "category": setup["cat"],
            "text": "Spende Erika Musterfrau",
            "counterparty": "Erika Musterfrau",
            "reference": "RE-4711",
        },
        content_type=JSON,
    )
    assert resp.status_code == 201, resp.json()
    booking = resp.json()["id"]
    up = c.post(
        f"{fin}/bookings/{booking}/receipts/",
        {"file": SimpleUploadedFile("rechnung.xml", UBL, content_type="text/xml")},
    )
    assert up.status_code == 201, up.json()
    assert c.post(f"{fin}/closings/", {"year": 2025}, content_type=JSON).status_code == 201
    return booking


def retention_of(c, fin, year=2025):
    years = {y["year"]: y for y in c.get(f"{fin}/closings/").json()["years"]}
    return years[year]["retention"]


def test_frist_laeuft_noch(c, fin, jahr2025, monkeypatch):
    info = retention_of(c, fin)
    assert info["documents_from"] == "2034-01-01"
    assert info["records_from"] == "2036-01-01"
    assert not info["documents_due"] and not info["records_due"]
    resp = c.post(f"{fin}/closings/aufbewahrung/", {"year": 2025}, content_type=JSON)
    assert resp.status_code == 400
    assert "läuft noch" in str(resp.json())


def test_belege_nach_acht_jahren(
    c, fin, club, jahr2025, monkeypatch, django_capture_on_commit_callbacks
):
    heute(monkeypatch, datetime.date(2034, 1, 1))
    info = retention_of(c, fin)
    assert info["documents_due"] and not info["records_due"]
    receipt = Receipt.objects.get()
    path = receipt.file.path
    with django_capture_on_commit_callbacks(execute=True):
        resp = c.post(f"{fin}/closings/aufbewahrung/", {"year": 2025}, content_type=JSON)
    assert resp.status_code == 200, resp.json()
    assert resp.json()["counts"]["Belege"] == 1
    assert not Receipt.objects.exists()
    import os

    assert not os.path.exists(path)
    # Bücher bleiben bis zum 11. Jahr unverändert
    b = Booking.objects.get(pk=jahr2025)
    assert b.counterparty == "Erika Musterfrau"
    info = retention_of(c, fin)
    assert info["documents_purged_at"] and not info["documents_due"]
    # Abschluss lässt sich nicht mehr aufheben
    resp = c.delete(f"{fin}/closings/?jahr=2025", {"reason": "Korrektur"}, content_type=JSON)
    assert resp.status_code == 400


def test_buecher_nach_zehn_jahren_anonymisiert(c, fin, club, jahr2025, monkeypatch):
    heute(monkeypatch, datetime.date(2036, 1, 1))
    seal(club.pk)
    resp = c.post(f"{fin}/closings/aufbewahrung/", {"year": 2025}, content_type=JSON)
    assert resp.status_code == 200, resp.json()
    b = Booking.objects.get(pk=jahr2025)
    assert (b.text, b.counterparty, b.reference) == ("anonymisiert", "", "")
    assert b.amount == 25  # Beträge bleiben, Bestände stimmen weiter
    with rls_bypass():
        entries = AuditEntry.objects.filter(
            organization=club, object_type="Buchung", object_id=str(jahr2025)
        )
        assert entries.exists()
        assert all(e.cleared and e.changes == {} for e in entries)
    seal(club.pk)
    result = verify(club.pk)
    assert result["ok"] and result["cleared"] >= 1
    info = retention_of(c, fin)
    assert info["records_purged_at"] and info["documents_purged_at"]
    # Nichts mehr fällig
    resp = c.post(f"{fin}/closings/aufbewahrung/", {"year": 2025}, content_type=JSON)
    assert resp.status_code == 400


def test_nur_vorstand_und_nur_abgeschlossen(c, fin, setup, monkeypatch):
    heute(monkeypatch, datetime.date(2036, 1, 1))
    resp = c.post(f"{fin}/closings/aufbewahrung/", {"year": 2025}, content_type=JSON)
    assert resp.status_code == 400
    assert "abgeschlossene" in str(resp.json())


def test_rollback_behaelt_belege(c, fin, club, jahr2025, monkeypatch):
    """Gesamtaudit 01.11., GA-F07: Dateien erst nach dem Commit löschen."""
    import os

    from django.db import transaction

    from accounts.models import User

    heute(monkeypatch, datetime.date(2034, 1, 1))
    path = Receipt.objects.get().file.path

    def kaputt(*args, **kwargs):
        raise RuntimeError("Fehler nach dem Löschen")

    monkeypatch.setattr("audit.log.record", kaputt)
    user = User.objects.filter(role_assignments__organization=club).first()
    with pytest.raises(RuntimeError), transaction.atomic():
        retention.purge(club, 2025, user)
    assert Receipt.objects.exists()
    assert os.path.exists(path)
