"""Audit Datenspeicherung und Berechnungen 31.10.: Kontoauszug (CAMT.053)."""
# ruff: noqa: F811  (Fixtures als Parameter)

import pytest

from finance import camt

from .test_app_verwaltung_b5 import offen  # noqa: F401
from .test_kontoauszug import IBAN, camt_xml, entry, fin, lines, upload  # noqa: F401
from .test_m9_billing import JSON, base, c, club, members, setup, zug  # noqa: F401

pytestmark = pytest.mark.django_db


def sammel(details, *, total, date="2025-03-03"):
    """Ein Ntry mit mehreren TxDtls (Sammelgutschrift)."""
    parts = "".join(
        f"""<TxDtls>
          <Refs><EndToEndId>{e2e}</EndToEndId></Refs>
          <AmtDtls><TxAmt><Amt Ccy="EUR">{amount}</Amt></TxAmt></AmtDtls>
          <RltdPties><Dbtr><Nm>{name}</Nm></Dbtr></RltdPties>
          <RmtInf><Ustrd>{purpose}</Ustrd></RmtInf>
        </TxDtls>"""
        for amount, name, purpose, e2e in details
    )
    return f"""
      <Ntry>
        <Amt Ccy="EUR">{total}</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd>
        <Sts><Cd>BOOK</Cd></Sts>
        <BookgDt><Dt>{date}</Dt></BookgDt>
        <NtryDtls>{parts}</NtryDtls>
      </Ntry>"""


class TestFIN3101GleicheUmsaetze:
    def test_zwei_gleiche_umsaetze_ohne_referenz_bleiben_zwei(self, c, fin):
        data = camt_xml([entry("25.00", purpose="Spende"), entry("25.00", purpose="Spende")])
        resp = upload(c, fin, data)
        assert resp.status_code == 201, resp.json()
        assert resp.json()["lines"] == 2 and resp.json()["duplicates"] == 0
        # dieselbe Datei noch einmal: beide erkannt
        again = upload(c, fin, data).json()
        assert again["lines"] == 0 and again["duplicates"] == 2

    def test_erstes_vorkommen_behaelt_die_alte_kennung(self):
        st = camt.parse(camt_xml([entry("25.00"), entry("25.00")]))[0]
        a, b = st.lines
        assert a.fingerprint(IBAN) != b.fingerprint(IBAN)
        a.occurrence = 1
        import hashlib

        assert a.fingerprint(IBAN) == hashlib.sha256(a.base_key(IBAN).encode()).hexdigest()


class TestFIN3102Sammelbuchung:
    def test_einzelposten_bleiben_erhalten_und_keine_rechnung(self, c, fin, offen):
        number = offen.display_number
        data = camt_xml(
            [
                sammel(
                    [
                        ("50.00", "Erika Muster", f"Beitrag {number}", "E1"),
                        ("50.00", "Anna Beispiel", "Beitrag R2025-0099", "E2"),
                    ],
                    total="100.00",
                )
            ]
        )
        assert upload(c, fin, data).status_code == 201
        row = lines(c, fin)[0]
        assert row["batch_count"] == 2 and row["amount"] == "100.00"
        assert [d["amount"] for d in row["details"]] == ["50.00", "50.00"]
        assert row["details"][1]["name"] == "Anna Beispiel"
        # Zweck/IBAN/Referenz stammen nicht vom ersten Posten
        assert number not in row["purpose"] and row["iban"] == ""
        assert row["suggestion"] == ""
        resp = c.post(
            f"{fin}/bank-lines/{row['id']}/assign/",
            {"action": "invoice", "invoice": offen.pk},
            content_type=JSON,
        )
        assert resp.status_code == 400
        assert "Sammelbuchung" in str(resp.json())


class TestFIN3103SchonGebucht:
    def _booking(self, c, fin, setup, amount, **extra):
        return c.post(
            f"{fin}/bookings/",
            {
                "date": "2025-03-02",
                "kind": "income",
                "amount": amount,
                "account": setup["bank"],
                "category": setup["cat"],
                "text": "Einnahme",
                **extra,
            },
            content_type=JSON,
        ).json()

    def test_rechnungsnummer_vor_betragstreffer(self, c, fin, setup, offen):
        self._booking(c, fin, setup, "60.00", counterparty="Kuchenverkauf")
        upload(
            c, fin, camt_xml([entry("60.00", purpose=f"Beitrag {offen.display_number}", ref="X1")])
        )
        row = lines(c, fin)[0]
        assert row["suggestion"] == "invoice" and row["suggestion_sure"] is True

    def test_nur_betrag_und_datum_ist_unsicher(self, c, fin, setup):
        b = self._booking(c, fin, setup, "25.00", counterparty="Kuchenverkauf")
        upload(c, fin, camt_xml([entry("25.00", ref="X2")]))
        row = lines(c, fin)[0]
        assert row["suggestion"] == "booked" and row["suggestion_sure"] is False
        # „Alle übernehmen“ lässt ihn offen
        result = c.post(f"{fin}/bank-lines/apply-suggestions/", {}, content_type=JSON).json()
        assert result == {"done": 0, "failed": []}
        # einzeln übernehmen geht weiter
        resp = c.post(
            f"{fin}/bank-lines/{row['id']}/assign/", {"action": "suggestion"}, content_type=JSON
        )
        assert resp.status_code == 200 and resp.json()["booking"] == b["id"]

    def test_mehrere_kandidaten_kein_vorschlag(self, c, fin, setup):
        self._booking(c, fin, setup, "25.00")
        self._booking(c, fin, setup, "25.00")
        upload(c, fin, camt_xml([entry("25.00", ref="X3")]))
        assert lines(c, fin)[0]["suggestion"] == ""

    def test_zuordnen_prueft_betrag(self, c, fin, setup):
        b = self._booking(c, fin, setup, "30.00")
        upload(c, fin, camt_xml([entry("25.00", ref="X4")]))
        row = lines(c, fin)[0]
        resp = c.post(
            f"{fin}/bank-lines/{row['id']}/assign/",
            {"action": "link", "link": b["id"]},
            content_type=JSON,
        )
        assert resp.status_code == 400


class TestFIN3104UngueltigesDatum:
    def test_ungueltiges_buchungsdatum_bricht_ab(self, c, fin):
        bad = entry("10.00", ref="Y1").replace("2025-03-03", "2025-02-31")
        resp = upload(c, fin, camt_xml([entry("5.00", ref="Y0"), bad]))
        assert resp.status_code == 400
        assert "Buchungsdatum" in str(resp.json())
        assert lines(c, fin) == []


class TestFIN31R04Betraege:
    @pytest.mark.parametrize("amount", ["1.234", "NaN", "Infinity", "-5.00", "99999999999.00"])
    def test_ungueltige_betraege(self, amount):
        with pytest.raises(camt.CamtError):
            camt.parse(camt_xml([entry(amount)]))

    def test_fremdwaehrung(self):
        data = camt_xml([entry("5.00").replace('Ccy="EUR"', 'Ccy="USD"')])
        with pytest.raises(camt.CamtError, match="Euro"):
            camt.parse(data)


class TestZuordnungBleibtStimmig:
    """FIN31-R03: Zugeordnete Buchung ändern/löschen hält den Kontoumsatz stimmig."""

    def _verknuepft(self, c, fin, setup):
        b = c.post(
            f"{fin}/bookings/",
            {
                "date": "2025-03-02",
                "kind": "income",
                "amount": "25.00",
                "account": setup["bank"],
                "category": setup["cat"],
                "text": "Spende",
                "counterparty": "Erika Muster",
            },
            content_type=JSON,
        ).json()
        upload(c, fin, camt_xml([entry("25.00", ref="R3")]))
        c.post(f"{fin}/bank-lines/apply-suggestions/", {}, content_type=JSON)
        row = lines(c, fin)[0]
        assert row["booking"] == b["id"]
        return b, row

    def test_betrag_aendern_gesperrt(self, c, fin, setup):
        b, _ = self._verknuepft(c, fin, setup)
        r = c.patch(f"{fin}/bookings/{b['id']}/", {"amount": "30.00"}, content_type=JSON)
        assert r.status_code == 400
        assert "Kontoumsatz" in str(r.json())
        ok = c.patch(f"{fin}/bookings/{b['id']}/", {"text": "Spende Sommerfest"}, content_type=JSON)
        assert ok.status_code == 200

    def test_loeschen_oeffnet_umsatz(self, c, fin, setup):
        b, row = self._verknuepft(c, fin, setup)
        assert c.delete(f"{fin}/bookings/{b['id']}/").status_code == 204
        row = lines(c, fin)[0]
        assert row["status"] == "open" and row["booking"] is None
