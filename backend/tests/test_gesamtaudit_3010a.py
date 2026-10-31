# ruff: noqa: F811  (Fixtures aus anderen Testmodulen)
"""Gesamtaudit vom 30.10.2026: Finanzen unter Nebenläufigkeit (B-S01, B-S02, B-V01).

Zwei echte PostgreSQL-Verbindungen (Threads). Ein Ablauf hält seine Transaktion an einer
bestimmten Stelle offen; geprüft wird, dass der andere wartet und danach den neuen Stand
sieht."""

import threading
import time
from decimal import Decimal

import pytest
from django.db import connection

from core.tenancy import tenant_context
from finance import quittung, services
from finance.models import Booking, CashReceipt, YearClosing

from .test_gesamtaudit_nebenlaeufig import WAIT, hold_then
from .test_m9_billing import JSON, base, c, club, setup, zug  # noqa: F401
from .test_quittung import _private, bestand, draft, q, sign  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


def thread(name, func):
    result: dict = {}

    def run():
        try:
            result["value"] = func()
        except Exception as exc:  # noqa: BLE001 - Ergebnis wird im Test geprüft
            result["error"] = exc
        finally:
            connection.close()

    t = threading.Thread(target=run, name=name)
    t.start()
    return t, result


def pause_in(monkeypatch, module, name, thread_name):
    """``module.name`` hält im Thread ``thread_name`` nach dem Aufruf an, bis ``go`` kommt."""
    reached, go = threading.Event(), threading.Event()
    original = getattr(module, name)

    def wrapped(*args, **kwargs):
        value = original(*args, **kwargs)
        if threading.current_thread().name == thread_name:
            reached.set()
            go.wait(WAIT)
        return value

    monkeypatch.setattr(module, name, wrapped)
    return reached, go


def ready_receipt(c, q, club):
    r = draft(c, q)
    assert sign(c, q, r["id"], "treasurer").status_code == 200
    assert sign(c, q, r["id"], "counterparty").status_code == 200
    with tenant_context(club.pk):
        receipt = CashReceipt.objects.get(pk=r["id"])
        return receipt, receipt.treasurer_user


class TestQuittung:
    """B-S01: Ändern/Löschen, das vor dem Abschluss begann, scheitert danach."""

    def _finalize(self, club, receipt, user):
        def run():
            with tenant_context(club.pk):
                quittung.finalize(CashReceipt.objects.get(pk=receipt.pk), user, confirmed=True)

        return run

    def test_aenderung_wartet_und_scheitert(self, c, q, club, bestand):
        receipt, user = ready_receipt(c, q, club)
        url = f"{q['url']}{receipt.pk}/"
        waited, second = hold_then(
            self._finalize(club, receipt, user),
            lambda: c.patch(url, {"amount": "99.00"}, content_type=JSON),
        )
        assert waited
        assert second["value"].status_code == 400, second["value"].json()
        with tenant_context(club.pk):
            receipt.refresh_from_db()
        assert receipt.status == CashReceipt.Status.FINAL
        assert receipt.amount == Decimal("120.50")
        assert receipt.treasurer_signature and receipt.counterparty_signature

    def test_loeschen_wartet_und_scheitert(self, c, q, club, bestand):
        receipt, user = ready_receipt(c, q, club)
        waited, second = hold_then(
            self._finalize(club, receipt, user),
            lambda: c.delete(f"{q['url']}{receipt.pk}/"),
        )
        assert waited
        assert second["value"].status_code == 400
        with tenant_context(club.pk):
            assert CashReceipt.objects.filter(pk=receipt.pk, status="final").exists()


class TestJahresabschluss:
    """B-S02: Die Jahressperre einer Buchungsänderung hält bis zum Schreiben."""

    def test_abschluss_wartet_auf_laufende_aenderung(self, c, q, club, bestand, monkeypatch):
        reached, go = pause_in(monkeypatch, services, "is_closed", "aendern")
        patch, patched = thread(
            "aendern",
            lambda: c.patch(
                f"{q['fin']}/bookings/{bestand}/", {"text": "Kassenbestand neu"}, content_type=JSON
            ),
        )
        assert reached.wait(WAIT)
        close, closed = thread(
            "abschluss", lambda: c.post(f"{q['fin']}/closings/", {"year": 2025}, content_type=JSON)
        )
        time.sleep(0.5)
        waited = close.is_alive()
        go.set()
        patch.join(WAIT)
        close.join(WAIT)
        assert waited, "der Abschluss hat nicht auf die laufende Änderung gewartet"
        assert patched["value"].status_code == 200, patched["value"].json()
        assert closed["value"].status_code in (200, 201), closed["value"].json()
        # Danach ist keine Änderung mehr möglich
        resp = c.patch(f"{q['fin']}/bookings/{bestand}/", {"text": "zu spät"}, content_type=JSON)
        assert resp.status_code == 400
        with tenant_context(club.pk):
            assert YearClosing.objects.filter(year=2025).exists()
            assert Booking.objects.get(pk=bestand).text == "Kassenbestand neu"

    def test_ohne_transaktion_verboten(self, club):
        with pytest.raises(RuntimeError):
            services.ensure_open(club, year=2025)


class TestBarkasse:
    """B-V01: Zwei Änderungen verschiedener Ausgaben prüfen die Kasse nacheinander."""

    def test_zwei_ausgaben_zusammen_nicht_unter_null(self, c, q, club, bestand, monkeypatch):
        ids = []
        for _ in range(2):
            resp = c.post(
                f"{q['fin']}/bookings/",
                {
                    "date": "2025-02-01",
                    "kind": "expense",
                    "amount": "200.00",
                    "account": q["cash"],
                    "category": q["out"],
                    "text": "Auslage",
                },
                content_type=JSON,
            )
            assert resp.status_code == 201, resp.json()
            ids.append(resp.json()["id"])
        reached, go = pause_in(monkeypatch, services, "ensure_cash_ok", "erste")

        def raise_to_300(pk):
            return lambda: c.patch(
                f"{q['fin']}/bookings/{pk}/", {"amount": "300.00"}, content_type=JSON
            )

        first, r1 = thread("erste", raise_to_300(ids[0]))
        assert reached.wait(WAIT)
        second, r2 = thread("zweite", raise_to_300(ids[1]))
        time.sleep(0.5)
        waited = second.is_alive()
        go.set()
        first.join(WAIT)
        second.join(WAIT)
        assert waited, "die zweite Änderung hat nicht auf die erste gewartet"
        assert r1["value"].status_code == 200
        assert r2["value"].status_code == 400
        assert "unter null" in str(r2["value"].json())


class TestDokumentfassungen:
    """B-F03: Zwei gleichzeitige Löschungen lassen mindestens eine Fassung übrig."""

    def test_letzte_fassung_bleibt(self, orgs, board_a, api, settings, tmp_path):
        from documents.models import Document, DocumentVersion

        from .test_documents import base as doc_base
        from .test_documents import folder, pdf, upload

        settings.PRIVATE_ROOT = tmp_path / "private"
        org = orgs["a"]
        org.member_portal_enabled = True
        org.save()
        c = api(board_a)
        b = doc_base(org)
        doc = upload(c, b, folder(c, b)["id"])
        doc = c.post(f"{b}{doc['id']}/versions/", {"file": pdf("v2.pdf", b"%PDF-1.7")}).json()
        first, second = doc["versions"]

        def delete_first():
            with tenant_context(org.pk):
                Document.objects.select_for_update().get(pk=doc["id"])
                DocumentVersion.objects.filter(pk=first["id"]).delete()

        waited, result = hold_then(delete_first, lambda: c.delete(second["url"]))
        assert waited
        assert result["value"].status_code in (400, 404)
        with tenant_context(org.pk):
            assert DocumentVersion.objects.filter(document_id=doc["id"]).count() == 1
