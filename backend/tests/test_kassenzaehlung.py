"""Finanzamt-Prüfung B2: Zählprotokoll und Kassenbericht für Feste (erfundene Daten)."""
# ruff: noqa: F811  (Fixtures als Parameter)

import hashlib
from decimal import Decimal

import pytest

from finance.models import Booking, CashCount, Receipt

from .test_m9_billing import JSON, base, c, club, setup, zug  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def fin(club):
    return f"/api/orgs/{club.pk}/finance"


@pytest.fixture
def kasse(c, fin, setup):
    """Barkasse mit 100 € Bestand, Kategorien für Differenz und Fest."""
    assert c.patch(f"{fin}/settings/", {"cash_counts_enabled": True}, content_type=JSON).json()[
        "cash_counts_enabled"
    ]
    cat = {}
    for name, kind in [
        ("Kassendifferenz", "both"),
        ("Getränkeverkauf", "income"),
        ("Eintritt", "income"),
    ]:
        resp = c.post(f"{fin}/categories/", {"name": name, "kind": kind}, content_type=JSON)
        cat[name] = resp.json()["id"]
    resp = c.post(
        f"{fin}/bookings/",
        {
            "date": "2025-06-01",
            "kind": "income",
            "amount": "100",
            "account": setup["cash"],
            "category": setup["cat"],
            "text": "Bareinzahlung",
        },
        content_type=JSON,
    )
    assert resp.status_code == 201, resp.json()
    return {"cash": setup["cash"], "bank": setup["bank"], **cat}


def zaehlung(c, fin, kasse, **extra):
    data = {
        "kind": "count",
        "account": kasse["cash"],
        "date": "2025-06-30",
        "denominations": {"5000": 1, "2000": 2, "100": 5},  # 95 €
        "counted_by": "Karla Kasse",
        "witness": "Paul Prüfer",
        **extra,
    }
    return c.post(f"{fin}/cash-counts/", data, content_type=JSON)


def test_ausgeschaltet(c, fin, setup):
    resp = c.post(f"{fin}/cash-counts/", {"kind": "count"}, content_type=JSON)
    assert resp.status_code == 400
    assert "nicht eingeschaltet" in str(resp.json())


def test_zaehlprotokoll_ohne_differenz(c, fin, kasse):
    resp = zaehlung(c, fin, kasse, denominations={"5000": 2})
    assert resp.status_code == 201, resp.json()
    data = resp.json()
    assert data["counted"] == "100.00" and data["expected"] == "100.00"
    assert data["difference"] == "0.00" and data["bookings"] == []
    item = CashCount.objects.get()
    with item.pdf.open("rb") as fh:
        assert hashlib.sha256(fh.read()).hexdigest() == item.pdf_sha256
    pdf = c.get(f"{fin}/cash-counts/{item.pk}/pdf/")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf"


def test_differenz_nur_mit_grund_und_wird_gebucht(c, fin, kasse):
    assert zaehlung(c, fin, kasse).status_code == 400  # ohne Grund
    assert not CashCount.objects.exists()
    resp = zaehlung(c, fin, kasse, note="Wechselgeld falsch herausgegeben")
    assert resp.status_code == 400 and "category" in resp.json()
    resp = zaehlung(
        c,
        fin,
        kasse,
        note="Wechselgeld falsch herausgegeben",
        category=kasse["Kassendifferenz"],
    )
    assert resp.status_code == 201, resp.json()
    assert resp.json()["difference"] == "-5.00"
    booking = Booking.objects.get(pk=resp.json()["bookings"][0]["id"])
    assert booking.kind == "expense" and booking.amount == Decimal("5.00")
    assert Receipt.objects.filter(booking=booking).count() == 1


def test_kassenbericht_fest(c, fin, kasse):
    data = {
        "kind": "event",
        "account": kasse["cash"],
        "date": "2025-07-12",
        "title": "Schützenfest Getränkezelt",
        "denominations": {"10000": 3, "5000": 1},  # 350 € Endbestand
        "opening": "100",  # Wechselgeld
        "expenses": "20",  # Eis bar bezahlt
        "withdrawals": "50",  # zwischendurch abgeschöpft
        "counted_by": "Karla Kasse",
        "lines": [
            {"category": kasse["Getränkeverkauf"], "amount": "250"},
            {"category": kasse["Eintritt"], "amount": "60"},
        ],
    }
    resp = c.post(f"{fin}/cash-counts/", data, content_type=JSON)
    assert resp.status_code == 400  # 310 statt 320
    assert "320,00" in str(resp.json())
    data["lines"][1]["amount"] = "70"
    resp = c.post(f"{fin}/cash-counts/", data, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    assert resp.json()["takings"] == "320.00"
    numbers = resp.json()["bookings"]
    assert len(numbers) == 2
    amounts = sorted(
        Booking.objects.filter(pk__in=[b["id"] for b in numbers]).values_list("amount", flat=True)
    )
    assert amounts == [Decimal("70.00"), Decimal("250.00")]


def test_nur_barkasse(c, fin, kasse):
    resp = zaehlung(c, fin, kasse, account=kasse["bank"], denominations={"5000": 2})
    assert resp.status_code == 400 and "account" in resp.json()


def test_im_pruefexport(c, fin, kasse):
    import io
    import zipfile

    assert zaehlung(c, fin, kasse, denominations={"5000": 2}).status_code == 201
    resp = c.get(f"{fin}/export/?jahr=2025")
    zf = zipfile.ZipFile(io.BytesIO(b"".join(resp.streaming_content)))
    pdfs = [n for n in zf.namelist() if n.startswith("kassenzaehlungen/")]
    assert len(pdfs) == 1
    item = CashCount.objects.get()
    assert hashlib.sha256(zf.read(pdfs[0])).hexdigest() == item.pdf_sha256
    assert "Karla Kasse" in zf.read("kassenzaehlungen.csv").decode("utf-8-sig")
