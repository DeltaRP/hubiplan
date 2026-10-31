"""Kontoauszüge im Format CAMT.053 (ISO 20022) lesen.

Die Banken liefern im Online-Banking eine XML-Datei je Auszug oder ein ZIP mit mehreren.
Gelesen werden alle Versionen (camt.053.001.02 bis .13); Namensräume werden ignoriert.
Nur gebuchte Umsätze (Status BOOK) zählen, vorgemerkte bleiben außen vor.

Sicherheit: keine DTD und keine Entitäten (sonst Abbruch), Größen- und Anzahlgrenzen
für ZIP-Dateien, damit ein präpariertes Archiv den Server nicht füllt.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import re
import xml.etree.ElementTree as ET  # noqa: S405 - DTD/Entitäten werden vorher abgewiesen
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

MAX_FILE = 10 * 1024 * 1024  # 10 MB je Upload
MAX_XML = 20 * 1024 * 1024  # 20 MB entpackt je Datei
MAX_FILES = 100  # Auszüge je ZIP


class CamtError(ValueError):
    pass


@dataclass
class Line:
    date: datetime.date
    value_date: datetime.date | None
    amount: Decimal  # immer positiv
    credit: bool  # Gutschrift (Geld kommt herein)
    name: str = ""
    iban: str = ""
    purpose: str = ""
    end_to_end: str = ""
    bank_ref: str = ""
    return_code: str = ""
    # mehrere Einzelumsätze in einer Sammelbuchung (z. B. Lastschrifteinzug)
    batch_count: int = 1
    # Einzelposten einer Sammelbuchung: je Posten Betrag, Name, IBAN, Zweck, Referenz
    details: list[dict] = field(default_factory=list)
    # n-tes gleiches Vorkommen ohne Bankreferenz im selben Auszug (Audit 31.10. FIN31-01)
    occurrence: int = 1

    def base_key(self, account_iban: str) -> str:
        return "|".join(
            [
                account_iban,
                self.date.isoformat(),
                f"{self.amount:.2f}",
                "C" if self.credit else "D",
                self.bank_ref or self.end_to_end or "",
                "" if (self.bank_ref or self.end_to_end) else f"{self.name}|{self.purpose}",
            ]
        )

    def fingerprint(self, account_iban: str) -> str:
        """Erkennt denselben Umsatz in einem zweiten Import (auch aus einer anderen Datei).

        Zwei gleiche Umsätze ohne Bankreferenz im selben Auszug (z. B. zweimal 25,00 € von
        derselben Person mit demselben Zweck) sind zwei Umsätze: das zweite Vorkommen bekommt
        eine eigene Kennung. Beim erneuten Einlesen derselben Datei entstehen dieselben
        Kennungen, die Dublettenerkennung bleibt also erhalten.
        """
        key = self.base_key(account_iban)
        if self.occurrence > 1:
            key += f"|#{self.occurrence}"
        return hashlib.sha256(key.encode()).hexdigest()


@dataclass
class Statement:
    iban: str
    ref: str = ""
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    opening: Decimal | None = None
    closing: Decimal | None = None
    currency: str = "EUR"
    lines: list[Line] = field(default_factory=list)

    def number_occurrences(self) -> None:
        """Gleiche Umsätze ohne Bankreferenz im Auszug fortlaufend zählen (FIN31-01)."""
        seen: dict[str, int] = {}
        for line in self.lines:
            key = line.base_key(self.iban)
            seen[key] = seen.get(key, 0) + 1
            line.occurrence = seen[key]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(el, name: str):
    return [c for c in el if _local(c.tag) == name]


def _find(el, *path: str):
    """Erstes Element entlang des Pfads (Namensräume egal), sonst None."""
    current = [el]
    for name in path:
        nxt = []
        for item in current:
            nxt += _children(item, name)
        if not nxt:
            return None
        current = nxt
    return current[0]


def _text(el, *path: str) -> str:
    found = _find(el, *path) if path else el
    if found is None or found.text is None:
        return ""
    return " ".join(found.text.split())


def _date(el, *path: str) -> datetime.date | None:
    node = _find(el, *path)
    if node is None:
        return None
    raw = _text(node, "Dt") or _text(node, "DtTm")[:10]
    try:
        return datetime.date.fromisoformat(raw[:10]) if raw else None
    except ValueError:
        return None


MAX_AMOUNT = Decimal("9999999999.99")  # passt in die Betragsfelder (12 Stellen, 2 nach dem Komma)


def _amount(raw: str, *, signed: bool = False) -> Decimal:
    """Betrag prüfen: endlich, höchstens zwei Nachkommastellen, in den Feldgrenzen (FIN31-R04)."""
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise CamtError(f"Ungültiger Betrag „{raw}“.") from None
    if not value.is_finite() or value != value.quantize(Decimal("0.01")) or abs(value) > MAX_AMOUNT:
        raise CamtError(f"Ungültiger Betrag „{raw}“.")
    if value < 0 and not signed:
        raise CamtError(f"Ungültiger Betrag „{raw}“ (Beträge stehen ohne Vorzeichen in der Datei).")
    return value


def _currency_ok(el, path: str = "Amt") -> None:
    node = _find(el, path)
    ccy = node.get("Ccy") if node is not None else None
    if ccy and ccy != "EUR":
        raise CamtError(f"Nur Beträge in Euro (Umsatz in {ccy}).")


def _balance(stmt, code: str) -> tuple[Decimal | None, datetime.date | None]:
    for bal in _children(stmt, "Bal"):
        if _text(bal, "Tp", "CdOrPrtry", "Cd") != code:
            continue
        value = _amount(_text(bal, "Amt") or "0", signed=True)
        if _text(bal, "CdtDbtInd") == "DBIT":
            value = -value
        return value, _date(bal, "Dt")
    return None, None


def _party(details, credit: bool) -> tuple[str, str]:
    """Name und IBAN der Gegenseite: bei Gutschriften der Zahler, sonst der Empfänger."""
    parties = _find(details, "RltdPties")
    if parties is None:
        return "", ""
    role = "Dbtr" if credit else "Cdtr"
    node = _find(parties, role)
    name = ""
    if node is not None:
        name = _text(node, "Nm") or _text(node, "Pty", "Nm")
    iban = _text(parties, f"{role}Acct", "Id", "IBAN")
    # Ultimativer Zahler (z. B. Eltern für das Kind) als Ergänzung
    ultimate = _text(parties, f"Ultmt{role}", "Nm") or _text(parties, f"Ultmt{role}", "Pty", "Nm")
    if ultimate and ultimate != name:
        name = f"{name} (für {ultimate})" if name else ultimate
    return name, iban.replace(" ", "").upper()


def _purpose(details) -> str:
    info = _find(details, "RmtInf")
    if info is None:
        return ""
    parts = [" ".join((u.text or "").split()) for u in _children(info, "Ustrd")]
    for strd in _children(info, "Strd"):
        ref = _text(strd, "CdtrRefInf", "Ref")
        if ref:
            parts.append(ref)
    return " ".join(p for p in parts if p)


def _parse_xml(data: bytes) -> list[Statement]:
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise CamtError("Die Datei enthält eine DTD und wird aus Sicherheitsgründen abgelehnt.")
    try:
        root = ET.fromstring(data)  # noqa: S314 - DTD/Entitäten oben abgewiesen
    except ET.ParseError:
        raise CamtError("Die Datei ist kein gültiges XML.") from None
    container = _find(root, "BkToCstmrStmt")
    if container is None:
        if _find(root, "BkToCstmrAcctRpt") is not None:
            raise CamtError(
                "Das ist ein Tagesumsatz (CAMT.052). Bitte den Kontoauszug als CAMT.053 laden."
            )
        raise CamtError("Keine CAMT.053-Datei (Kontoauszug) gefunden.")
    statements = []
    for stmt in _children(container, "Stmt"):
        iban = _text(stmt, "Acct", "Id", "IBAN").replace(" ", "").upper()
        currency = _text(stmt, "Acct", "Ccy") or "EUR"
        opening, open_date = _balance(stmt, "OPBD")
        if opening is None:
            opening, open_date = _balance(stmt, "PRCD")
        closing, close_date = _balance(stmt, "CLBD")
        st = Statement(
            iban=iban,
            ref=_text(stmt, "Id") or _text(stmt, "ElctrncSeqNb"),
            date_from=_date(stmt, "FrToDt", "FrDtTm") or open_date,
            date_to=_date(stmt, "FrToDt", "ToDtTm") or close_date,
            opening=opening,
            closing=closing,
            currency=currency,
        )
        for pos, entry in enumerate(_children(stmt, "Ntry"), start=1):
            status = _text(entry, "Sts", "Cd") or _text(entry, "Sts")
            if status and status != "BOOK":
                continue
            raw_amount = _text(entry, "Amt")
            if not raw_amount:
                raise CamtError(f"Umsatz Nr. {pos} im Auszug {iban} hat keinen Betrag.")
            amount = _amount(raw_amount)
            _currency_ok(entry)
            credit = _text(entry, "CdtDbtInd") == "CRDT"
            reversal = _text(entry, "RvslInd").lower() == "true"
            booked = _date(entry, "BookgDt") or _date(entry, "ValDt")
            if booked is None:
                # Nicht still auslassen (Audit 31.10. FIN31-04): sonst fehlt ein Umsatz,
                # obwohl der Import als erfolgreich gemeldet wird
                raise CamtError(
                    f"Umsatz Nr. {pos} im Auszug {iban} ({raw_amount} €) hat kein gültiges "
                    "Buchungsdatum. Bitte den Auszug bei der Bank neu herunterladen; eingelesen "
                    "wurde nichts."
                )
            all_details = []
            for ntry_dtls in _children(entry, "NtryDtls"):
                all_details += _children(ntry_dtls, "TxDtls")
            details = all_details[0] if all_details else None
            name = iban_other = purpose = e2e = ret = ""
            if details is not None:
                name, iban_other = _party(details, credit)
                purpose = _purpose(details)
                e2e = _text(details, "Refs", "EndToEndId")
                if e2e == "NOTPROVIDED":
                    e2e = ""
                ret = _text(details, "RtrInf", "Rsn", "Cd")
            if not purpose:
                purpose = _text(entry, "AddtlNtryInf")
            batch: list[dict] = []
            if len(all_details) > 1:
                # Sammelbuchung (Audit 31.10. FIN31-02): Zweck, IBAN und Referenz des ersten
                # Postens gelten nicht für die ganze Summe. Die Einzelposten bleiben vollständig
                # erhalten; eine Zuordnung zu einer einzelnen Rechnung gibt es nicht.
                for d in all_details:
                    d_name, d_iban = _party(d, credit)
                    d_raw = _text(d, "AmtDtls", "TxAmt", "Amt") or _text(d, "Amt")
                    d_ref = _text(d, "Refs", "EndToEndId")
                    batch.append(
                        {
                            "amount": str(_amount(d_raw)) if d_raw else "",
                            "name": d_name[:200],
                            "iban": d_iban[:34],
                            "purpose": _purpose(d)[:500],
                            "end_to_end": "" if d_ref == "NOTPROVIDED" else d_ref[:35],
                        }
                    )
                name = name if len({b["name"] for b in batch}) == 1 else ""
                iban_other = ""
                e2e = ""
                ret = ""
                purpose = _text(entry, "AddtlNtryInf") or f"Sammelbuchung mit {len(batch)} Posten"
            line = Line(
                date=booked,
                value_date=_date(entry, "ValDt"),
                amount=abs(amount),
                credit=credit,
                name=name[:200],
                iban=iban_other[:34],
                purpose=purpose[:500],
                end_to_end=e2e[:35],
                bank_ref=(_text(entry, "AcctSvcrRef") or _text(entry, "NtryRef"))[:100],
                return_code=(ret or ("REVERSAL" if reversal else ""))[:10],
                batch_count=max(len(all_details), 1),
                details=batch,
            )
            st.lines.append(line)
        st.number_occurrences()
        statements.append(st)
    if not statements:
        raise CamtError("Die Datei enthält keinen Kontoauszug.")
    return statements


def parse(data: bytes) -> list[Statement]:
    """XML- oder ZIP-Datei lesen; liefert alle Auszüge darin."""
    if len(data) > MAX_FILE:
        raise CamtError("Die Datei ist größer als 10 MB.")
    if data[:2] == b"PK":
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise CamtError("Das ZIP-Archiv ist beschädigt.") from None
        names = [i for i in archive.infolist() if i.filename.lower().endswith(".xml")]
        if not names:
            raise CamtError("Im ZIP-Archiv ist keine XML-Datei.")
        if len(names) > MAX_FILES:
            raise CamtError(f"Höchstens {MAX_FILES} Auszüge je ZIP-Archiv.")
        result = []
        for info in sorted(names, key=lambda i: i.filename):
            if info.file_size > MAX_XML:
                raise CamtError(f"{info.filename} ist entpackt zu groß.")
            with archive.open(info) as fh:
                content = fh.read(MAX_XML + 1)
            if len(content) > MAX_XML:
                raise CamtError(f"{info.filename} ist entpackt zu groß.")
            result += _parse_xml(content)
        return result
    return _parse_xml(data)


# Rechnungsnummern wie R2026-0007 oder R2025/26-0012 im Verwendungszweck (auch mit Leerzeichen)
INVOICE_RE = re.compile(r"R\s?(\d{4})(?:\s?/\s?(\d{2}))?\s?-\s?(\d{1,6})", re.IGNORECASE)


def invoice_numbers(text: str) -> list[tuple[int, int]]:
    """(Jahr, Nummer) aller Rechnungsnummern im Text."""
    return [(int(m.group(1)), int(m.group(3))) for m in INVOICE_RE.finditer(text or "")]
