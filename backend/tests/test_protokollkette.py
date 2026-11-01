"""Finanzamt-Prüfung C3: verkettetes Änderungsprotokoll (erfundene Daten)."""
# ruff: noqa: F811  (Fixtures als Parameter)

import pytest

from audit.chain import seal, verify
from audit.models import AuditCheck, AuditEntry
from audit.tasks import check_chains
from core.tenancy import rls_bypass

from .test_m9_billing import JSON, base, c, club, setup, zug  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def fin(club):
    return f"/api/orgs/{club.pk}/finance"


def buchen(c, fin, setup, text):
    resp = c.post(
        f"{fin}/bookings/",
        {
            "date": "2025-06-01",
            "kind": "income",
            "amount": "10",
            "account": setup["cash"],
            "category": setup["cat"],
            "text": text,
        },
        content_type=JSON,
    )
    assert resp.status_code == 201, resp.json()


def eintraege(club):
    with rls_bypass():
        return list(AuditEntry.objects.filter(organization=club).order_by("seq"))


def test_kette_wird_gebildet_und_ist_unveraendert(c, fin, club, setup):
    buchen(c, fin, setup, "Spende Grillfest")
    buchen(c, fin, setup, "Spende Kuchenbasar")
    seal(club.pk)
    entries = eintraege(club)
    assert [e.seq for e in entries] == list(range(1, len(entries) + 1))
    assert entries[0].prev_hash == "0" * 64
    for prev, entry in zip(entries, entries[1:], strict=False):
        assert entry.prev_hash == prev.hash
    result = verify(club.pk)
    assert result["ok"] and result["entries"] == len(entries)
    # Erneutes Versiegeln ändert nichts
    assert seal(club.pk) == 0


def test_aenderung_und_loeschung_fallen_auf(c, fin, club, setup):
    for i in range(3):
        buchen(c, fin, setup, f"Buchung {i}")
    seal(club.pk)
    entries = eintraege(club)
    with rls_bypass():
        AuditEntry.objects.filter(pk=entries[1].pk).update(user_email="jemand@example.org")
        # Wer die Datenbank ändert, kann einen gültig verschlüsselten Inhalt einsetzen
        original = entries[2].changes
        entries[2].changes = {"Betrag": ["1", "2"]}
        entries[2].save(update_fields=["changes"])
    result = verify(club.pk)
    assert not result["ok"]
    assert any("Angaben wurden nachträglich geändert" in p for p in result["problems"])
    assert any("Inhalt wurde nachträglich geändert" in p for p in result["problems"])

    with rls_bypass():
        AuditEntry.objects.filter(pk=entries[1].pk).update(user_email=entries[1].user_email)
        entries[2].changes = original
        entries[2].save(update_fields=["changes"])
    assert verify(club.pk)["ok"]
    with rls_bypass():
        AuditEntry.objects.filter(pk=entries[1].pk).delete()
    result = verify(club.pk)
    assert not result["ok"]
    assert any("fehlen (gelöscht)" in p for p in result["problems"])


def test_datenschutz_leeren_bricht_die_kette_nicht(c, fin, club, setup):
    buchen(c, fin, setup, "Beitrag Erika Musterfrau")
    seal(club.pk)
    entry = eintraege(club)[-1]
    with rls_bypass():
        AuditEntry.objects.filter(pk=entry.pk).update(changes={}, cleared=True)
    result = verify(club.pk)
    assert result["ok"]
    assert result["cleared"] == 1


def test_taegliche_pruefung_meldet_einmal(c, fin, club, setup, monkeypatch):
    sent = []
    monkeypatch.setattr("core.alarm.send_alert", lambda subject, lines: sent.append(subject))
    buchen(c, fin, setup, "Buchung")
    check_chains()
    with rls_bypass():
        assert AuditCheck.objects.get(organization=club).ok
        AuditEntry.objects.filter(organization=club).order_by("seq").first().delete()
    assert sent == []
    check_chains()
    with rls_bypass():
        assert not AuditCheck.objects.get(organization=club).ok
    assert sent == ["Änderungsprotokoll wurde verändert"]
    check_chains()  # schon gemeldet: keine zweite Mail
    assert len(sent) == 1


def test_api_und_export(c, fin, club, setup):
    buchen(c, fin, setup, "Buchung")
    url = f"/api/orgs/{club.pk}/audit/kette/"
    assert c.get(url).json() == {"check": None}
    check = c.post(url, {}, content_type=JSON).json()["check"]
    assert check["ok"] and check["entries"] >= 1 and len(check["head_hash"]) == 64
    assert c.get(url).json()["check"]["ok"]

    import io
    import zipfile

    resp = c.get(f"{fin}/export/?jahr=2025")
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(b"".join(resp.streaming_content)))
    report = zf.read("protokollpruefung.txt").decode()
    assert "Ergebnis: unverändert" in report
    header = zf.read("protokoll.csv").decode("utf-8-sig").splitlines()[0]
    assert "Prüfsumme Vorgänger" in header


def test_jede_einheit_nur_einmal(c, fin, club, setup):
    """Die Standardsortierung darf nicht ins DISTINCT geraten: sonst käme jede Einheit
    einmal je Eintrag dran (Migration audit 0006 lief so auf Dogado stundenlang)."""
    import importlib

    from django.apps import apps
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    for i in range(5):
        buchen(c, fin, setup, f"Spende {i}")
    with rls_bypass():
        orgs = set(AuditEntry.objects.order_by().values_list("organization_id", flat=True))
        AuditEntry.objects.update(seq=None, prev_hash="", hash="", changes_hash="")
    assert check_chains() == len(orgs)

    with rls_bypass():
        AuditEntry.objects.update(seq=None, prev_hash="", hash="", changes_hash="")
    migration = importlib.import_module("audit.migrations.0006_protokollkette")

    class Editor:
        def __init__(self):
            self.connection = connection

        def execute(self, sql):
            with connection.cursor() as cur:
                cur.execute(sql)

    with rls_bypass(), CaptureQueriesContext(connection) as ctx:
        migration.versiegeln(apps, Editor())
    updates = [q for q in ctx.captured_queries if q["sql"].startswith("UPDATE")]
    assert len(updates) == len(orgs)
    assert verify(club.pk)["ok"]
