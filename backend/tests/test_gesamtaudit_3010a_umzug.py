# ruff: noqa: F811  (Fixtures aus anderen Testmodulen)
"""Gesamtaudit 30.10. (B-F01): Quittungen kommen beim vollständigen Umzug mit."""

import hashlib
import io
import uuid
import zipfile

import pytest

from core.tenancy import rls_bypass
from datatransfer import dump, load
from datatransfer.tables import IdMap, check_cash_receipts, dump_tables, load_tables
from finance.models import Booking, CashReceipt

from .factories import make_org
from .test_m9_billing import JSON, base, c, club, setup, zug  # noqa: F401
from .test_quittung import _private, bestand, draft, q, sign  # noqa: F401

pytestmark = pytest.mark.django_db


def final_receipt(c, q):
    r = draft(c, q)
    sign(c, q, r["id"], "treasurer")
    sign(c, q, r["id"], "counterparty")
    resp = c.post(
        f"{q['url']}{r['id']}/finalize/",
        {"confirmed": True},
        content_type=JSON,
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert resp.status_code == 200, resp.json()
    return r["id"]


def roundtrip(org):
    packer = dump.Packer(with_files=True)
    with rls_bypass():
        # Nur die Kasse: Mitglieder und Beiträge brauchen den übrigen Export
        tables = {k: v for k, v in dump_tables(org, packer).items() if k.startswith("finance.")}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, fieldfile in packer.files:
            with fieldfile.open("rb") as handle:
                zf.writestr(path, handle.read())
    buf.seek(0)
    target = make_org("Umzug")
    with rls_bypass():
        load_tables(tables, target, IdMap(), load.Files(zipfile.ZipFile(buf)))
    return tables, target


def test_quittung_kommt_mit(c, q, club, bestand):
    rid = final_receipt(c, q)
    resp = c.post(
        f"{q['url']}{final_receipt(c, q)}/cancel/", {"reason": "Irrtum"}, content_type=JSON
    )
    assert resp.status_code == 200, resp.json()
    tables, target = roundtrip(club)
    assert len(tables["finance.cashreceipt"]) == 2
    with rls_bypass():
        source = CashReceipt.objects.get(pk=rid)
        copied = CashReceipt.objects.filter(organization=target).order_by("pk")
        assert copied.count() == 2
        first = copied.get(number=source.number)
        assert first.status == CashReceipt.Status.FINAL
        assert first.treasurer_signature == source.treasurer_signature
        assert first.counterparty_signature == source.counterparty_signature
        assert first.booking.organization == target
        assert first.booking.amount == source.booking.amount
        assert first.account.organization == target
        # PDF unverändert, Prüfsumme passt
        with first.document.file.open("rb") as handle:
            assert hashlib.sha256(handle.read()).hexdigest() == first.pdf_sha256
        cancelled = copied.get(status=CashReceipt.Status.CANCELLED)
        assert cancelled.cancel_booking.organization == target
        assert cancelled.cancel_document is not None
        # Schutz der Buchung gilt auch nach dem Umzug
        from finance.views import _quittung_of

        assert _quittung_of(first.booking) == first
        assert Booking.objects.filter(organization=target).count() == 4


def test_alter_export_ohne_quittungen_warnt():
    seen = []
    check_cash_receipts({"finance.booking": [{"id": 1, "reference": "Quittung"}]}, seen.append)
    assert "keine Quittungen" in seen[0]
    seen.clear()
    check_cash_receipts(
        {"finance.booking": [{"id": 1, "reference": "Quittung"}], "finance.cashreceipt": [{}]},
        seen.append,
    )
    assert not seen


def test_jobgrenze(club, c):
    # B-V03: höchstens zwei laufende vollständige Exporte/Importe je Organisation
    from rest_framework.exceptions import Throttled

    from datatransfer.models import TransferJob
    from datatransfer.views import start_export

    with rls_bypass():
        for _ in range(2):
            TransferJob.objects.create(
                organization=club,
                direction=TransferJob.Direction.EXPORT,
                kind="organization",
                status=TransferJob.Status.RUNNING,
            )
        with pytest.raises(Throttled):
            start_export(club, None, kind="organization", with_files=False)


def test_bestaende_in_einer_abfrage(c, q, club, bestand):
    # B-P01: gleiche Bestände wie die Einzelberechnung, auch mit Umbuchung
    from finance import services
    from finance.models import Account

    for data in (
        {"kind": "expense", "amount": "20.00", "account": q["cash"], "category": q["out"]},
        {"kind": "transfer", "amount": "100.00", "account": q["bank"], "to_account": q["cash"]},
    ):
        resp = c.post(
            f"{q['fin']}/bookings/",
            {"date": "2025-03-01", "text": "Test", **data},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
    with rls_bypass():
        expected = {a.pk: services.balance(a) for a in Account.objects.filter(organization=club)}
        assert services.balances(club.pk) == expected
        assert expected[q["cash"]] == 580
