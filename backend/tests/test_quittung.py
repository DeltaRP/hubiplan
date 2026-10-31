"""Digitale Quittung mit Unterschrift (konzepte/digitale-quittung.md, Q1/Q2/Q5)."""
# ruff: noqa: F811  (Fixtures als Parameter)

import datetime
import hashlib
import uuid
from decimal import Decimal

import pytest
from django.utils import timezone

from billing.models import Invoice, Payment
from core.tenancy import tenant_context
from finance.models import Booking, CashReceipt, Receipt
from finance.signature import normalize
from finance.words import euro_words, number_words

from .factories import give_role, make_member
from .test_app_devices import app
from .test_app_verwaltung_b4 import ADMIN, unlocked
from .test_app_verwaltung_b5 import offen  # noqa: F401
from .test_m9_billing import JSON, base, c, club, members, setup, zug  # noqa: F401
from .test_m12_events import member_with_access

pytestmark = pytest.mark.django_db

LINE = {"width": 600, "height": 200, "strokes": [[[10, 100], [200, 40], [400, 160], [590, 90]]]}


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def q(club, setup, c):
    """Kasse mit einer Ausgabe-Kategorie; URL der Quittungen."""
    fin = f"/api/orgs/{club.pk}/finance"
    out = c.post(
        f"{fin}/categories/", {"name": "Auslagen", "kind": "expense"}, content_type=JSON
    ).json()["id"]
    return {"url": f"{fin}/cash-receipts/", "fin": fin, "out": out, **setup}


@pytest.fixture
def bestand(c, q):
    """500 € in der Barkasse (sonst fiele sie bei Auszahlungen unter null)."""
    resp = c.post(
        f"{q['fin']}/bookings/",
        {
            "date": "2025-01-02",
            "kind": "income",
            "amount": "500.00",
            "account": q["cash"],
            "category": q["cat"],
            "text": "Kassenbestand",
        },
        content_type=JSON,
    )
    assert resp.status_code == 201, resp.json()
    return resp.json()["id"]


def draft(c, q, **extra):
    data = {
        "direction": "out",
        "counterparty_name": "Max Muster",
        "amount": "120.50",
        "purpose": "Auslagen Kranzniederlegung",
        "account": q["cash"],
        "category": q["out"],
        **extra,
    }
    resp = c.post(q["url"], data, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    return resp.json()


def sign(c, q, rid, role, data=None):
    return c.put(f"{q['url']}{rid}/signatures/{role}/", data or LINE, content_type=JSON)


def finalize(c, q, rid, key=None, **data):
    return c.post(
        f"{q['url']}{rid}/finalize/",
        {"confirmed": True, **data},
        content_type=JSON,
        HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()),
    )


class TestWorte:
    @pytest.mark.parametrize(
        "n,text",
        [
            (0, "null"),
            (1, "eins"),
            (16, "sechzehn"),
            (21, "einundzwanzig"),
            (100, "einhundert"),
            (101, "einhunderteins"),
            (120, "einhundertzwanzig"),
            (1000, "eintausend"),
            (2371, "zweitausenddreihunderteinundsiebzig"),
            (1_000_000, "eine Million"),
        ],
    )
    def test_zahlen(self, n, text):
        assert number_words(n) == text

    def test_euro(self):
        assert euro_words(Decimal("120.50")) == "einhundertzwanzig Euro und 50 Cent"
        assert euro_words(Decimal("1")) == "ein Euro"


class TestUnterschrift:
    def test_nur_form_ganzzahlig(self):
        shape = normalize(LINE)
        assert shape["w"] == 1000 and shape["h"] == 333
        assert shape["s"][0][:2] == [17, 167]
        assert all(isinstance(v, int) for v in shape["s"][0])

    @pytest.mark.parametrize(
        "data",
        [
            None,
            {"width": 600, "height": 200, "strokes": []},
            {"width": 600, "height": 200, "strokes": [[[10, 10]]]},
            {"width": 600, "height": 200, "strokes": [[[10, 10], [12, 11]]]},
            {"width": 0, "height": 200, "strokes": LINE["strokes"]},
            {"width": 600, "height": 200, "strokes": [[[10, "x"], [300, 10]]]},
            {"width": 600, "height": 200, "strokes": [[[10, float("nan")], [300, 10]]]},
        ],
    )
    def test_leer_oder_ungueltig(self, data):
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            normalize(data)


class TestQuittung:
    def test_auszahlung_ablauf(self, club, c, q, board_a, bestand):
        r = draft(c, q)
        assert r["status"] == "draft" and r["number"] == ""
        assert set(r["missing"]) == {"Unterschrift des Kassierers", "Unterschrift des Empfängers"}
        assert "von" in r["confirmation_text"] and "120,50 €" in r["confirmation_text"]
        # Vorschau mit „Entwurf“
        prev = c.get(f"{q['url']}{r['id']}/pdf/")
        assert prev.status_code == 200 and prev.content.startswith(b"%PDF")
        # Abschluss ohne Unterschriften geht nicht
        resp = finalize(c, q, r["id"])
        assert resp.status_code == 400
        assert sign(c, q, r["id"], "treasurer").status_code == 200
        resp = sign(c, q, r["id"], "counterparty")
        assert resp.status_code == 200, resp.json()
        assert resp.json()["missing"] == []
        # Ohne Bestätigung nicht
        resp = finalize(c, q, r["id"], confirmed=False)
        assert resp.status_code == 400 and "confirmed" in resp.json()
        resp = finalize(c, q, r["id"])
        assert resp.status_code == 200, resp.json()
        done = resp.json()
        assert done["status"] == "final"
        booking = Booking.objects.get(pk=done["booking"])
        assert done["number"] == booking.display_number
        assert booking.kind == "expense" and booking.amount == Decimal("120.50")
        assert booking.account_id == q["cash"] and booking.counterparty == "Max Muster"
        # PDF als Beleg an der Buchung, Prüfsumme stimmt
        doc = Receipt.objects.get(booking=booking)
        content = doc.file.open("rb").read()
        assert hashlib.sha256(content).hexdigest() == done["pdf_sha256"]
        pdf = c.get(f"{q['url']}{r['id']}/pdf/")
        assert pdf.content == content
        # Danach unveränderlich
        assert (
            c.patch(f"{q['url']}{r['id']}/", {"amount": "1"}, content_type=JSON).status_code == 400
        )
        assert sign(c, q, r["id"], "counterparty").status_code == 400
        assert c.delete(f"{q['url']}{r['id']}/").status_code == 400
        # Buchung und Beleg geschützt
        b_url = f"{q['fin']}/bookings/{booking.pk}/"
        assert c.patch(b_url, {"amount": "5"}, content_type=JSON).status_code == 400
        assert c.patch(b_url, {"number": 99}, content_type=JSON).status_code == 400
        assert c.delete(b_url).status_code == 400
        assert c.delete(f"{q['fin']}/receipts/{doc.pk}/").status_code == 400
        # Neu nummerieren im Jahr gesperrt
        resp = c.post(f"{q['fin']}/bookings/renumber/", {"year": booking.year}, content_type=JSON)
        assert resp.status_code == 400

    def test_doppelt_abgeschlossen_nur_einmal(self, c, q, bestand):
        r = draft(c, q)
        sign(c, q, r["id"], "treasurer")
        sign(c, q, r["id"], "counterparty")
        key = str(uuid.uuid4())
        assert finalize(c, q, r["id"], key).status_code == 200
        again = finalize(c, q, r["id"], key)
        assert again.status_code == 200
        assert Booking.objects.count() == 2  # Bestand und Quittung
        # Ohne Schlüssel abgelehnt
        resp = c.post(f"{q['url']}{r['id']}/finalize/", {"confirmed": True}, content_type=JSON)
        assert resp.status_code == 400

    def test_aenderung_leert_unterschriften(self, c, q):
        r = draft(c, q)
        sign(c, q, r["id"], "treasurer")
        sign(c, q, r["id"], "counterparty")
        resp = c.patch(f"{q['url']}{r['id']}/", {"email": "max@example.org"}, content_type=JSON)
        assert resp.json()["counterparty_signature"] is not None
        resp = c.patch(f"{q['url']}{r['id']}/", {"amount": "99.00"}, content_type=JSON)
        body = resp.json()
        assert body["counterparty_signature"] is None and body["treasurer_signature"] is None

    def test_eingang_zahler_ohne_unterschrift(self, c, q):
        r = draft(c, q, direction="in", category=q["cat"], purpose="Spende Schießstand")
        url = f"{q['url']}{r['id']}/signatures/counterparty/"
        assert c.put(url, {"declined": ""}, content_type=JSON).status_code == 400
        resp = c.put(url, {"declined": "möchte nicht"}, content_type=JSON)
        assert resp.status_code == 200
        sign(c, q, r["id"], "treasurer")
        resp = finalize(c, q, r["id"])
        assert resp.status_code == 200, resp.json()
        assert Booking.objects.get(pk=resp.json()["booking"]).kind == "income"
        # Bei Auszahlung nicht erlaubt
        r2 = draft(c, q)
        resp = c.put(
            f"{q['url']}{r2['id']}/signatures/counterparty/",
            {"declined": "x y z"},
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_nur_barkasse_und_passende_kategorie(self, c, q):
        data = {
            "direction": "out",
            "counterparty_name": "Max",
            "amount": "5",
            "purpose": "x",
            "category": q["out"],
        }
        resp = c.post(q["url"], {**data, "account": q["bank"]}, content_type=JSON)
        assert resp.status_code == 400 and "account" in resp.json()
        resp = c.post(
            q["url"], {**data, "account": q["cash"], "category": q["cat"]}, content_type=JSON
        )
        assert resp.status_code == 400 and "category" in resp.json()

    def test_abschliessen_nur_wer_als_kassierer_unterschrieb(self, club, c, q, api):
        r = draft(c, q)
        sign(c, q, r["id"], "treasurer")
        sign(c, q, r["id"], "counterparty")
        _, other, _ = member_with_access(club, "Klara")
        give_role(other, club, ["finance.view", "finance.edit"], name="Kassiererin")
        resp = finalize(api(other), q, r["id"])
        assert resp.status_code == 400
        assert not Booking.objects.exists()

    def test_hinterlegte_unterschrift(self, c, q):
        r = draft(c, q)
        url = f"{q['url']}{r['id']}/signatures/treasurer/"
        assert c.put(url, {"use_stored": True}, content_type=JSON).status_code == 400
        assert c.get("/api/me/signature/").json()["signature"] is None
        resp = c.put("/api/me/signature/", LINE, content_type=JSON)
        assert resp.status_code == 200 and resp.json()["signature"]["w"] == 1000
        assert c.get(f"{q['url']}{r['id']}/").json()["has_stored_signature"] is True
        resp = c.put(url, {"use_stored": True}, content_type=JSON)
        assert resp.status_code == 200
        assert resp.json()["treasurer_signature"] == normalize(LINE)
        assert c.delete("/api/me/signature/").status_code == 204
        assert c.get("/api/me/signature/").json()["signature"] is None

    def test_storno(self, c, q, bestand):
        r = draft(c, q)
        sign(c, q, r["id"], "treasurer")
        sign(c, q, r["id"], "counterparty")
        done = finalize(c, q, r["id"]).json()
        resp = c.post(f"{q['url']}{r['id']}/cancel/", {"reason": ""}, content_type=JSON)
        assert resp.status_code == 400
        resp = c.post(
            f"{q['url']}{r['id']}/cancel/", {"reason": "doppelt erfasst"}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        body = resp.json()
        assert body["status"] == "cancelled" and body["cancel_number"]
        counter = Booking.objects.exclude(pk__in=[done["booking"], bestand]).get()
        assert counter.kind == "income" and counter.amount == Decimal("120.50")
        assert counter.reference == done["number"]
        # Original bleibt, PDF jetzt mit Vermerk
        assert Booking.objects.filter(pk=done["booking"]).exists()
        assert Receipt.objects.count() == 2
        pdf = c.get(f"{q['url']}{r['id']}/pdf/")
        assert pdf.status_code == 200 and "Storno" in pdf["Content-Disposition"]
        assert (
            c.post(
                f"{q['url']}{r['id']}/cancel/", {"reason": "nochmal"}, content_type=JSON
            ).status_code
            == 400
        )
        assert c.delete(f"{q['fin']}/bookings/{counter.pk}/").status_code == 400

    def test_versand(self, c, q, mailoutbox, bestand):
        r = draft(c, q, email="max@example.org")
        assert c.post(f"{q['url']}{r['id']}/send/").status_code == 400  # Entwurf
        sign(c, q, r["id"], "treasurer")
        sign(c, q, r["id"], "counterparty")
        finalize(c, q, r["id"])
        resp = c.post(f"{q['url']}{r['id']}/send/")
        assert resp.status_code == 200, resp.json()
        assert resp.json()["sent_at"]
        assert mailoutbox[-1].to == ["max@example.org"]
        assert mailoutbox[-1].attachments[0][0].startswith("Quittung-")

    def test_umsatzsteuer_bei_bedarf(self, c, q):
        r = draft(c, q, vat_rate="19")
        assert r["vat_rate"] == "19.0"
        assert (
            c.patch(f"{q['url']}{r['id']}/", {"vat_rate": "150"}, content_type=JSON).status_code
            == 400
        )

    def test_offline_unterschrieben(self, c, q, bestand):
        r = draft(c, q)
        sign(c, q, r["id"], "treasurer")
        when = (timezone.now() - datetime.timedelta(days=2)).isoformat()
        resp = sign(c, q, r["id"], "counterparty", {**LINE, "signed_at": when})
        assert resp.status_code == 200
        done = finalize(c, q, r["id"]).json()
        assert done["receipt_date"] == str(timezone.localdate() - datetime.timedelta(days=2))
        old = (timezone.now() - datetime.timedelta(days=40)).isoformat()
        r2 = draft(c, q)
        assert sign(c, q, r2["id"], "counterparty", {**LINE, "signed_at": old}).status_code == 400

    def test_nur_mit_recht(self, club, q, api):
        _, user, _ = member_with_access(club, "Peter")
        give_role(user, club, ["finance.view"], name="Kassenprüfer")
        pr = api(user)
        resp = pr.get(q["url"])
        assert resp.status_code == 200 and resp.json()["count"] == 0
        resp = pr.post(q["url"], {"direction": "out"}, content_type=JSON)
        assert resp.status_code == 403


class TestRechnung:
    def test_barzahlung_mit_unterschrift(self, club, c, q, offen):
        resp = c.post(
            f"{q['url']}from-invoice/{offen.pk}/", {"account": q["cash"]}, content_type=JSON
        )
        assert resp.status_code == 201, resp.json()
        r = resp.json()
        assert r["direction"] == "in" and r["amount"] == "60.00"
        assert r["invoice_number"] == offen.display_number
        assert (
            c.patch(f"{q['url']}{r['id']}/", {"amount": "10"}, content_type=JSON).status_code == 400
        )
        sign(c, q, r["id"], "treasurer")
        sign(c, q, r["id"], "counterparty")
        done = finalize(c, q, r["id"]).json()
        offen.refresh_from_db()
        assert offen.status == Invoice.Status.PAID
        payment = Payment.objects.get(invoice=offen)
        assert payment.booking_id == done["booking"] and payment.method == "cash"
        # Die B5-Quittung liefert jetzt das unterschriebene PDF
        pdf = c.get(f"/api/orgs/{club.pk}/billing/payments/{payment.pk}/receipt/")
        doc = Receipt.objects.get(booking_id=done["booking"])
        assert pdf.content == doc.file.open("rb").read()
        # Storno öffnet die Rechnung wieder, Buchung und Beleg bleiben
        resp = c.post(
            f"{q['url']}{r['id']}/cancel/", {"reason": "falsche Person"}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        offen.refresh_from_db()
        assert offen.status == Invoice.Status.OPEN and offen.outstanding == Decimal("60.00")
        assert Booking.objects.filter(pk=done["booking"]).exists()


class TestApp:
    def test_quittung_aus_der_app(self, club, q, api, bestand):
        _, user, _ = member_with_access(club, "Karl")
        give_role(user, club, ["finance.view", "finance.edit"], name="Kassierer")
        a = app(unlocked(api, user))
        url = f"{ADMIN}u/{club.pk}/finance/cash-receipts/"
        resp = a.post(
            url,
            {
                "direction": "out",
                "counterparty_name": "Max Muster",
                "amount": "12",
                "purpose": "Getränke",
                "account": q["cash"],
                "category": q["out"],
            },
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        rid = resp.json()["id"]
        assert resp.json()["source"].startswith("App (")
        assert a.put(f"{ADMIN}signature/", LINE, content_type=JSON).status_code == 200
        assert (
            a.put(
                f"{url}{rid}/signatures/treasurer/", {"use_stored": True}, content_type=JSON
            ).status_code
            == 200
        )
        assert (
            a.put(f"{url}{rid}/signatures/counterparty/", LINE, content_type=JSON).status_code
            == 200
        )
        resp = a.post(
            f"{url}{rid}/finalize/",
            {"confirmed": True},
            content_type=JSON,
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        assert resp.status_code == 200, resp.json()
        with tenant_context(club.pk):
            receipt = CashReceipt.objects.get(pk=rid)
        assert receipt.status == "final" and receipt.number
        pdf = a.get(f"{url}{rid}/pdf/")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


class TestBarkasseNieUnterNull:
    def test_ausgabe_ohne_bestand_abgelehnt(self, c, q):
        url = f"{q['fin']}/bookings/"
        out = {
            "date": "2026-03-01",
            "kind": "expense",
            "amount": "10.00",
            "account": q["cash"],
            "category": q["out"],
            "text": "Kerzen",
        }
        resp = c.post(url, out, content_type=JSON)
        assert resp.status_code == 400 and "unter null" in str(resp.json())
        inc = {
            **out,
            "kind": "income",
            "category": q["cat"],
            "date": "2026-02-01",
            "text": "Spende",
        }
        assert c.post(url, inc, content_type=JSON).status_code == 201
        assert c.post(url, out, content_type=JSON).status_code == 201
        # Die Einnahme davor löschen ginge jetzt ins Minus
        first = Booking.objects.get(text="Spende")
        assert c.delete(f"{url}{first.pk}/").status_code == 400
        # Ausgabe auf das Datum vor der Einnahme verschieben ebenso
        spent = Booking.objects.get(text="Kerzen")
        resp = c.patch(f"{url}{spent.pk}/", {"date": "2026-01-15"}, content_type=JSON)
        assert resp.status_code == 400
        # Bankkonto darf ins Minus
        bank = {**out, "account": q["bank"]}
        assert c.post(url, bank, content_type=JSON).status_code == 201

    def test_quittung_auszahlung_ohne_bestand(self, c, q):
        r = draft(c, q)
        sign(c, q, r["id"], "treasurer")
        sign(c, q, r["id"], "counterparty")
        resp = finalize(c, q, r["id"])
        assert resp.status_code == 400 and "unter null" in str(resp.json())
        assert not Booking.objects.exists()


def test_datenexport_fuer_pruefung(club, c, q, bestand):
    import io
    import zipfile

    r = draft(c, q)
    sign(c, q, r["id"], "treasurer")
    sign(c, q, r["id"], "counterparty")
    done = finalize(c, q, r["id"]).json()
    year = Booking.objects.get(pk=done["booking"]).year
    resp = c.get(f"{q['fin']}/export/?jahr={year}")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(b"".join(resp.streaming_content)))
    names = zf.namelist()
    assert {
        "buchungen.csv",
        "konten.csv",
        "quittungen.csv",
        "LIESMICH.txt",
        "pruefsummen.txt",
    } <= set(names)
    pdfs = [n for n in names if n.startswith("belege/")]
    assert len(pdfs) == 1
    assert hashlib.sha256(zf.read(pdfs[0])).hexdigest() == done["pdf_sha256"]
    quittungen = zf.read("quittungen.csv").decode("utf-8-sig")
    assert done["number"] in quittungen and done["pdf_sha256"] in quittungen
    assert "120,50" in zf.read("buchungen.csv").decode("utf-8-sig")


def test_anlegen_mit_schluessel_nur_einmal(c, q):
    data = {
        "direction": "out",
        "counterparty_name": "Max",
        "amount": "5",
        "purpose": "x",
        "account": q["cash"],
        "category": q["out"],
    }
    key = str(uuid.uuid4())
    first = c.post(q["url"], data, content_type=JSON, HTTP_IDEMPOTENCY_KEY=key)
    again = c.post(q["url"], data, content_type=JSON, HTTP_IDEMPOTENCY_KEY=key)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert CashReceipt.objects.count() == 1


def test_mitglied_uebernimmt_anschrift_aus_den_kontaktdaten(club, c, q):
    """Gesamtaudit 31.10.b, FIN-F01: Anschrift und E-Mail stehen in den Kontaktdaten."""
    m = make_member(club, "Erika", "Muster", "erika@example.org")
    r = draft(c, q, membership=m.pk, counterparty_name="Erika Muster")
    assert r["counterparty_address"] == "Lindenweg 4\n12345 Musterstadt"
    assert r["email"] == "erika@example.org"
