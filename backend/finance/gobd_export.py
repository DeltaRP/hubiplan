"""Datenexport der Kasse für eine Prüfung (Finanzamt, Kassenprüfer): ZIP je Geschäftsjahr.

Inhalt (Tabellen als CSV mit Semikolon, UTF-8 mit BOM, Dezimalkomma; Aufbau in ``index.xml``
nach dem Beschreibungsstandard der Finanzverwaltung, Prüfung 31.10. A4):

- Kasse: ``buchungen.csv``, ``konten.csv``, ``quittungen.csv``, ``belege/``
- Beiträge: ``rechnungen.csv``, ``rechnungsposten.csv``, ``zahlungen.csv``, ``mahnungen.csv``,
  ``lastschriften.csv``, ``lastschriftposten.csv``, ``rechnungen/`` (ausgegebene PDFs),
  ``lastschriften/`` (SEPA-Dateien)
- Spenden: ``zuwendungen.csv``, ``zuwendungsbestaetigungen.csv``,
  ``zuwendungsbestaetigungen/`` (Doppel)
- Bank: ``kontoauszuege.csv``, ``kontoumsaetze.csv``, ``kontoauszuege/`` (Originaldateien)
- Barkasse: ``kassenzaehlungen.csv``, ``kassenzaehlungen/`` (Zählprotokolle, Kassenberichte)
- Rücklagen: ``ruecklagen.csv`` (wenn geführt)
- ``protokoll.csv``: Änderungsprotokoll der Finanzdaten ab Beginn des Geschäftsjahres
- ``protokollpruefung.txt``: Ergebnis der Kettenprüfung des Änderungsprotokolls
- ``abschluss.json``: Stand beim Jahresabschluss (falls abgeschlossen)
- ``LIESMICH.txt``, ``pruefsummen.txt``

So lassen sich die Daten maschinell auswerten (Datenträgerüberlassung nach § 147 Abs. 6 AO).
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from django.utils import timezone

from . import services
from .models import Account, Booking, CashReceipt, TaxArea

TAX_AREA_LABELS = dict(TaxArea.choices)

README = """Kassendaten {org} – Geschäftsjahr {label}
Erstellt am {now} mit HUBIplan.

index.xml       Aufbau aller Tabellen (Beschreibungsstandard der Finanzverwaltung,
                gdpdu-01-09-2004.dtd) für den Import in Prüfsoftware.
buchungen.csv   Alle Buchungen des Geschäftsjahres. Beträge immer positiv, die Art
                (Einnahme, Ausgabe, Umbuchung) sagt die Richtung. Spalte „Belege“
                nennt die Dateien im Ordner belege/ (ausgeblendete Belege mit Grund).
                Fehler werden nicht gelöscht, sondern storniert: Die Gegenbuchung
                verweist in „storniert Buchung“ auf die ursprüngliche Buchung.
                „festgeschrieben“: Buchung lässt sich nicht mehr ändern.
konten.csv      Konten mit Anfangsbestand und Bestand am Ende des Geschäftsjahres.
quittungen.csv  Quittungen mit Unterschrift auf dem Bildschirm. Die Prüfsumme (SHA-256)
                des PDF wurde beim Abschluss gespeichert; sie muss zur Datei passen.
rechnungen.csv  Festgeschriebene Rechnungen mit Rechnungsdatum im Geschäftsjahr, dazu
                rechnungsposten.csv, zahlungen.csv und mahnungen.csv. Die PDFs in
                rechnungen/ sind die ausgegebene Fassung (Prüfsumme in der Tabelle).
lastschriften   lastschriften.csv, lastschriftposten.csv und die erzeugten
                SEPA-Dateien (pain.008) in lastschriften/.
zuwendungen     zuwendungen.csv (alle erfassten Zuwendungen) und
                zuwendungsbestaetigungen.csv mit den Doppeln in zuwendungsbestaetigungen/.
kontoauszüge    kontoauszuege.csv, kontoumsaetze.csv und die eingelesenen Dateien
                unverändert in kontoauszuege/ (Prüfsumme in der Tabelle).
kassenzählung   kassenzaehlungen.csv mit Zählprotokollen und Kassenberichten (Feste),
                die PDFs in kassenzaehlungen/ (Prüfsumme in der Tabelle).
rücklagen       ruecklagen.csv (wenn geführt): Stand zu Beginn, Zuführungen,
                Auflösungen und Stand am Ende je Rücklage.
protokoll.csv   Änderungsprotokoll der Finanzdaten (wer, wann, was, vorher/nachher)
                ab Beginn des Geschäftsjahres bis zur Erstellung dieses Exports,
                verkettet über Prüfsummen (laufende Nummer, Vorgänger, eigene).
protokollpruefung.txt  Ergebnis der Prüfung der ganzen Protokollkette.
abschluss.json  Stand beim Jahresabschluss (nur bei abgeschlossenem Jahr).
pruefsummen.txt SHA-256 jeder Datei in diesem Archiv.
belege/         Belegdateien, benannt nach Buchungsnummer.

Dateien: Semikolon als Trennzeichen, UTF-8, Dezimalkomma, Datum TT.MM.JJJJ.
"""


def _money(value) -> str:
    return f"{value:.2f}".replace(".", ",")


# Texte, die ein Tabellenprogramm als Formel liest, bekommen ein Hochkomma davor
# (Gesamtaudit 31.10.b, FIN-S03). Beträge wie „-12,50“ bleiben Zahlen.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"-?\d[\d.]*(,\d+)?")


def _cell(value):
    if isinstance(value, str) and value.startswith(_FORMULA_START) and not _NUMBER.fullmatch(value):
        return "'" + value
    return value


def _csv(rows: list[list]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerows([_cell(v) for v in row] for row in rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _safe(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in ".-_" else "_" for c in name)
    return keep[-100:] or "beleg"


def _has_cancellation(b: Booking) -> bool:
    try:
        b.cancellation  # noqa: B018
    except Booking.DoesNotExist:
        return False
    return True


def _date(value) -> str:
    return f"{value:%d.%m.%Y}" if value else ""


def _stamp(value) -> str:
    return f"{timezone.localtime(value):%d.%m.%Y %H:%M}" if value else ""


@dataclass
class Table:
    """Eine CSV-Tabelle mit Spaltenarten für index.xml (text, num, date)."""

    url: str
    name: str
    description: str
    columns: list[tuple[str, str]]
    rows: list[list] = field(default_factory=list)

    def add(self, *values) -> None:
        self.rows.append(list(values))

    def content(self) -> bytes:
        return _csv([[c for c, _ in self.columns], *self.rows])


def _columns(*names: str, num: tuple[str, ...] = (), date: tuple[str, ...] = ()):
    return [(n, "num" if n in num else "date" if n in date else "text") for n in names]


def index_xml(org, label: str, start, end, tables: list[Table]) -> bytes:
    """Beschreibung der Tabellen nach dem Beschreibungsstandard (GDPdU, DTD 01-09-2004)."""
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE DataSet SYSTEM "gdpdu-01-09-2004.dtd">',
        "<DataSet>",
        "  <Version>1.0</Version>",
        "  <DataSupplier>",
        f"    <Name>{escape(org.name)}</Name>",
        f"    <Location>{escape(' '.join(x for x in (org.postal_code, org.city) if x))}</Location>",
        f"    <Comment>Kassendaten Geschäftsjahr {escape(label)}, erstellt mit HUBIplan</Comment>",
        "  </DataSupplier>",
        "  <Media>",
        "    <Name>HUBIplan-Export</Name>",
    ]
    for t in tables:
        out += [
            "    <Table>",
            f"      <URL>{escape(t.url)}</URL>",
            f"      <Name>{escape(t.name)}</Name>",
            f"      <Description>{escape(t.description)}</Description>",
            "      <Validity>",
            f"        <Range><From>{_date(start)}</From><To>{_date(end)}</To></Range>",
            "        <Format>DD.MM.YYYY</Format>",
            "      </Validity>",
            "      <UTF8/>",
            "      <DecimalSymbol>,</DecimalSymbol>",
            "      <DigitGroupingSymbol>.</DigitGroupingSymbol>",
            "      <Range><From>2</From></Range>",
            "      <VariableLength>",
            "        <ColumnDelimiter>;</ColumnDelimiter>",
            "        <RecordDelimiter>&amp;#13;&amp;#10;</RecordDelimiter>",
            "        <TextEncapsulator>&quot;</TextEncapsulator>",
        ]
        for name, kind in t.columns:
            if kind == "num":
                typ = "<Numeric><Accuracy>2</Accuracy></Numeric>"
            elif kind == "date":
                typ = "<Date><Format>DD.MM.YYYY</Format></Date>"
            else:
                typ = "<AlphaNumeric/>"
            out.append(f"        <VariableColumn><Name>{escape(name)}</Name>{typ}</VariableColumn>")
        out += ["      </VariableLength>", "    </Table>"]
    out += ["  </Media>", "</DataSet>", ""]
    return "\n".join(out).encode("utf-8")


def build(org, year: int):
    """ZIP als temporäre Datei (Belege können groß sein); Rückgabe: offene Datei."""
    start, end = org.fiscal_range(year)
    label = org.fiscal_label(year)
    bookings = list(
        Booking.objects.filter(organization=org, year=year)
        .select_related(
            "account",
            "to_account",
            "category",
            "project",
            "organization",
            "cancels__organization",
            "cancellation__organization",
        )
        .prefetch_related("receipts")
        .order_by("number")
    )
    closed = services.is_closed(org, year)
    out = tempfile.TemporaryFile()
    sums: list[tuple[str, str]] = []
    tables: list[Table] = []

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:

        def add(path: str, content: bytes):
            zf.writestr(path, content)
            sums.append((hashlib.sha256(content).hexdigest(), path))

        def add_file(path: str, filefield) -> str:
            """Gespeicherte Datei ins Archiv; Rückgabe: Pfad bzw. Hinweis, wenn sie fehlt."""
            try:
                with filefield.open("rb") as fh:
                    add(path, fh.read())
                return path
            except (OSError, ValueError):
                return f"(fehlt: {path})"

        # --- Kasse ---
        t = Table(
            "buchungen.csv",
            "Buchungen",
            "Alle Buchungen des Geschäftsjahres; Beträge positiv, Art gibt die Richtung",
            _columns(
                "Buchungsnummer",
                "Datum",
                "Art",
                "Betrag",
                "Konto",
                "Zielkonto",
                "Kategorie",
                "Steuerbereich",
                "Buchungstext",
                "Empfänger/Zahler",
                "Belegnummer/Referenz",
                "Veranstaltung",
                "Belege",
                "erfasst am",
                "storniert Buchung",
                "storniert durch",
                "Grund des Stornos",
                "festgeschrieben",
                num=("Betrag",),
                date=("Datum",),
            ),
        )
        for b in bookings:
            counter = b.cancellation if _has_cancellation(b) else None
            files = []
            for r in b.receipts.all():
                path = add_file(f"belege/{b.display_number}_{r.pk}_{_safe(r.name)}", r.file)
                # Ausgeblendet statt gelöscht: bleibt im Archiv, mit Grund
                files.append(f"{path} (ausgeblendet: {r.hidden_reason})" if r.hidden_at else path)
            t.add(
                b.display_number,
                _date(b.date),
                b.get_kind_display(),
                _money(b.amount),
                b.account.name,
                b.to_account.name if b.to_account_id else "",
                b.category_label or "",
                TAX_AREA_LABELS.get(b.tax_area_value, ""),
                b.text,
                b.counterparty,
                b.reference,
                b.project.name if b.project_id else "",
                ", ".join(files),
                _stamp(b.created_at),
                b.cancels.display_number if b.cancels_id else "",
                counter.display_number if counter else "",
                b.cancel_reason if b.cancels_id else counter.cancel_reason if counter else "",
                "ja" if closed or services.fixed_reason(b) else "nein",
            )
        tables.append(t)

        t = Table(
            "konten.csv",
            "Konten",
            "Konten mit Anfangsbestand und Bestand am Ende des Geschäftsjahres",
            _columns(
                "Konto",
                "Art",
                "IBAN",
                "Anfangsbestand",
                "Stichtag",
                "Bestand Jahresende",
                num=("Anfangsbestand", "Bestand Jahresende"),
                date=("Stichtag",),
            ),
        )
        for a in Account.objects.filter(organization=org).order_by("position", "name"):
            t.add(
                a.name,
                a.get_kind_display(),
                a.iban,
                _money(a.opening_balance),
                _date(a.opening_date),
                _money(services.balance(a, before=end + datetime.timedelta(days=1))),
            )
        tables.append(t)

        t = Table(
            "quittungen.csv",
            "Quittungen",
            "Quittungen mit Unterschrift; SHA-256 des beim Abschluss gespeicherten PDF",
            _columns(
                "Belegnummer",
                "Datum",
                "Richtung",
                "Betrag",
                "Gegenseite",
                "Zweck",
                "Status",
                "Kassierer",
                "unterschrieben Gegenseite",
                "ohne Unterschrift, Grund",
                "abgeschlossen",
                "SHA-256 PDF",
                "Storno Gegenbuchung",
                "Storno Grund",
                "SHA-256 Storno-PDF",
                num=("Betrag",),
                date=("Datum",),
            ),
        )
        for q in (
            CashReceipt.objects.filter(organization=org, booking__year=year)
            .select_related("cancel_booking__organization")
            .order_by("number")
        ):
            t.add(
                q.number,
                _date(q.receipt_date),
                q.get_direction_display(),
                _money(q.amount),
                q.counterparty_name,
                q.purpose,
                q.get_status_display(),
                q.treasurer_name,
                _stamp(q.counterparty_signed_at),
                q.no_signature_reason,
                _stamp(q.finalized_at),
                q.pdf_sha256,
                q.cancel_booking.display_number if q.cancel_booking_id else "",
                q.cancel_reason,
                q.cancel_sha256,
            )
        tables.append(t)

        tables += _billing_tables(org, start, end, add, add_file)
        tables += _donation_tables(org, start, end, add_file)
        tables += _bank_tables(org, start, end, add_file)
        tables.append(_cash_count_table(org, start, end, add_file))
        if org.reserves_enabled or _has_reserves(org):
            tables.append(_reserve_table(org, start, end))
        tables.append(_protocol_table(org, start))
        add("protokollpruefung.txt", _chain_report(org))

        for table in tables:
            add(table.url, table.content())
        add("index.xml", index_xml(org, label, start, end, tables))

        from .models import YearClosing

        closing = YearClosing.objects.filter(organization=org, year=year).first()
        if closing is not None:
            data = {
                "Geschäftsjahr": label,
                "abgeschlossen am": _stamp(closing.closed_at),
                "abgeschlossen von": (
                    closing.closed_by.get_full_name() or closing.closed_by.email
                    if closing.closed_by
                    else ""
                ),
                "Stand": closing.snapshot,
            }
            add("abschluss.json", json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
        add(
            "LIESMICH.txt",
            README.format(
                org=org.name,
                label=label,
                now=f"{timezone.localtime():%d.%m.%Y %H:%M}",
            ).encode("utf-8"),
        )
        zf.writestr("pruefsummen.txt", "".join(f"{h}  {p}\n" for h, p in sums))
    out.seek(0)
    return out, f"Kasse-{label.replace('/', '-')}-Export.zip", len(bookings)


def _billing_tables(org, start, end, add, add_file) -> list[Table]:
    from billing import archive
    from billing.models import DebitItem, DebitRun, Dunning, Invoice, InvoiceLine, Payment

    invoices = list(
        Invoice.objects.filter(
            organization=org, number__isnull=False, date__gte=start, date__lte=end
        )
        .select_related("organization")
        .order_by("year", "number")
    )
    inv = Table(
        "rechnungen.csv",
        "Rechnungen",
        "Festgeschriebene Rechnungen mit Rechnungsdatum im Geschäftsjahr",
        _columns(
            "Rechnungsnummer",
            "Rechnungsdatum",
            "fällig am",
            "Empfänger",
            "Betreff",
            "Betrag",
            "bezahlt",
            "Status",
            "storniert am",
            "Mahnstufe",
            "PDF",
            "SHA-256 PDF",
            num=("Betrag", "bezahlt"),
            date=("Rechnungsdatum", "fällig am"),
        ),
    )
    for i in invoices:
        path = ""
        if i.status in archive.ARCHIVED or i.issued_pdf:
            name = f"rechnungen/{_safe(i.display_number)}.pdf"
            if not i.issued_pdf:
                archive.archived_pdf(i)  # legt die ausgegebene Fassung beim ersten Abruf ab
            path = add_file(name, i.issued_pdf)
        inv.add(
            i.display_number,
            _date(i.date),
            _date(i.due_date),
            i.recipient_name.splitlines()[0] if i.recipient_name else "",
            i.subject,
            _money(i.total),
            _money(i.paid),
            i.get_status_display(),
            _stamp(i.cancelled_at),
            i.dunning_level,
            path,
            i.issued_pdf_sha256,
        )
    lines = Table(
        "rechnungsposten.csv",
        "Rechnungsposten",
        "Posten der Rechnungen (Bruttobeträge, enthaltene Umsatzsteuer nach Satz)",
        _columns("Rechnungsnummer", "Text", "Zusatz", "Betrag", "USt-Satz", num=("Betrag",)),
    )
    for line in (
        InvoiceLine.objects.filter(invoice__in=invoices)
        .select_related("invoice__organization")
        .order_by("invoice__year", "invoice__number", "position", "pk")
    ):
        lines.add(
            line.invoice.display_number,
            line.text,
            line.detail,
            _money(line.amount),
            f"{line.vat_rate:.2f}".replace(".", ",") if line.vat_rate else "",
        )
    pay = Table(
        "zahlungen.csv",
        "Zahlungen",
        "Zahlungseingänge zu Rechnungen mit Datum im Geschäftsjahr",
        _columns(
            "Rechnungsnummer",
            "Datum",
            "Betrag",
            "Zahlungsweg",
            "Buchungsnummer",
            num=("Betrag",),
            date=("Datum",),
        ),
    )
    for p in (
        Payment.objects.filter(organization=org, date__gte=start, date__lte=end)
        .select_related("invoice__organization", "booking__organization")
        .order_by("date", "pk")
    ):
        pay.add(
            p.invoice.display_number,
            _date(p.date),
            _money(p.amount),
            p.get_method_display(),
            p.booking.display_number,
        )
    dun = Table(
        "mahnungen.csv",
        "Mahnungen",
        "Mahnungen mit Datum im Geschäftsjahr",
        _columns(
            "Rechnungsnummer",
            "Stufe",
            "Bezeichnung",
            "Datum",
            "neue Zahlungsfrist",
            "Mahngebühr",
            "verschickt",
            num=("Mahngebühr",),
            date=("Datum", "neue Zahlungsfrist"),
        ),
    )
    for d in (
        Dunning.objects.filter(organization=org, date__gte=start, date__lte=end)
        .select_related("invoice__organization")
        .order_by("date", "pk")
    ):
        dun.add(
            d.invoice.display_number,
            d.level,
            d.name,
            _date(d.date),
            _date(d.due_date),
            _money(d.fee),
            _stamp(d.sent_at),
        )
    runs = Table(
        "lastschriften.csv",
        "Lastschriftläufe",
        "SEPA-Lastschriftläufe mit Einzugsdatum im Geschäftsjahr; Datei = erzeugte pain.008",
        _columns(
            "Lauf",
            "Einzugsdatum",
            "Konto",
            "Message-ID",
            "Status",
            "Summe",
            "Datei",
            "SHA-256 Datei",
            num=("Summe",),
            date=("Einzugsdatum",),
        ),
    )
    items = Table(
        "lastschriftposten.csv",
        "Lastschriften",
        "Einzelne Lastschriften der Läufe",
        _columns(
            "Lauf",
            "Rechnungsnummer",
            "Betrag",
            "Sequenz",
            "End-to-End-Referenz",
            "Mandatsreferenz",
            num=("Betrag",),
        ),
    )
    run_list = list(
        DebitRun.objects.filter(
            organization=org, collection_date__gte=start, collection_date__lte=end
        )
        .select_related("account")
        .order_by("collection_date", "pk")
    )
    for r in run_list:
        path, digest = "", ""
        if r.xml:
            content = r.xml.encode("utf-8")
            path = f"lastschriften/{r.collection_date:%Y-%m-%d}_{r.pk}.xml"
            add(path, content)
            digest = hashlib.sha256(content).hexdigest()
        runs.add(
            r.pk,
            _date(r.collection_date),
            r.account.name,
            r.message_id,
            r.get_status_display(),
            _money(r.total),
            path,
            digest,
        )
    for it in (
        DebitItem.objects.filter(run__in=run_list)
        .select_related("invoice__organization", "mandate")
        .order_by("run_id", "pk")
    ):
        items.add(
            it.run_id,
            it.invoice.display_number,
            _money(it.amount),
            it.sequence,
            it.end_to_end_id,
            it.mandate.reference,
        )
    return [inv, lines, pay, dun, runs, items]


def _donation_tables(org, start, end, add_file) -> list[Table]:
    from .models import Donation, DonationStatement

    don = Table(
        "zuwendungen.csv",
        "Zuwendungen",
        "Erfasste Zuwendungen (Spenden, Mitgliedsbeiträge, Sachzuwendungen) im Geschäftsjahr",
        _columns(
            "Datum",
            "Art",
            "Betrag",
            "Zuwendender",
            "Verzicht auf Erstattung",
            "Buchungsnummer",
            "Bestätigung",
            num=("Betrag",),
            date=("Datum",),
        ),
    )
    for d in (
        Donation.objects.filter(organization=org, date__gte=start, date__lte=end)
        .select_related("booking__organization", "statement")
        .order_by("date", "pk")
    ):
        don.add(
            _date(d.date),
            d.get_kind_display(),
            _money(d.amount),
            d.donor_name,
            "ja" if d.waiver else "nein",
            d.booking.display_number if d.booking_id else "",
            d.statement.number if d.statement_id else "",
        )
    st = Table(
        "zuwendungsbestaetigungen.csv",
        "Zuwendungsbestätigungen",
        "Ausgestellte Zuwendungsbestätigungen; PDF = Doppel (§ 50 Abs. 7 EStDV)",
        _columns(
            "Nummer",
            "Art",
            "Zuwendender",
            "Betrag",
            "von",
            "bis",
            "ausgestellt am",
            "unterschrieben von",
            "storniert am",
            "Grund des Stornos",
            "PDF",
            "SHA-256 PDF",
            num=("Betrag",),
            date=("von", "bis", "ausgestellt am"),
        ),
    )
    for s in DonationStatement.objects.filter(
        organization=org, issued_on__gte=start, issued_on__lte=end
    ).order_by("year", "seq"):
        path = add_file(f"zuwendungsbestaetigungen/{s.number}.pdf", s.file) if s.file else ""
        st.add(
            s.number,
            s.get_kind_display(),
            s.donor_name,
            _money(s.total),
            _date(s.period_from),
            _date(s.period_to),
            _date(s.issued_on),
            s.signer_name,
            _stamp(s.cancelled_at),
            s.cancel_reason,
            path,
            s.pdf_sha256,
        )
    return [don, st]


def _bank_tables(org, start, end, add_file) -> list[Table]:
    from django.db.models import Q

    from .models import BankLine, BankStatement

    lines = list(
        BankLine.objects.filter(organization=org, date__gte=start, date__lte=end)
        .select_related("account", "booking__organization", "statement")
        .order_by("account_id", "date", "pk")
    )
    ids = {line.statement_id for line in lines}
    statements = BankStatement.objects.filter(organization=org).filter(
        Q(pk__in=ids) | Q(date_from__lte=end, date_to__gte=start)
    )
    files: dict[int, str] = {}
    st = Table(
        "kontoauszuege.csv",
        "Kontoauszüge",
        "Eingelesene Kontoauszüge (CAMT.053); Originaldatei unverändert",
        _columns(
            "Auszug-ID",
            "Konto",
            "Auszug",
            "von",
            "bis",
            "Anfangssaldo",
            "Endsaldo",
            "eingelesen am",
            "Dateiname",
            "Originaldatei",
            "SHA-256 Originaldatei",
            num=("Anfangssaldo", "Endsaldo"),
            date=("von", "bis"),
        ),
    )
    for s in statements.select_related("account").order_by("account_id", "date_from", "pk"):
        path = (
            add_file(f"kontoauszuege/{s.pk}_{_safe(s.file_name)}", s.source)
            if s.source
            else "(vor der Aufbewahrung eingelesen)"
        )
        files[s.pk] = path
        st.add(
            s.pk,
            s.account.name,
            s.reference,
            _date(s.date_from),
            _date(s.date_to),
            _money(s.opening_balance) if s.opening_balance is not None else "",
            _money(s.closing_balance) if s.closing_balance is not None else "",
            _stamp(s.created_at),
            s.file_name,
            path,
            s.source_sha256,
        )
    ln = Table(
        "kontoumsaetze.csv",
        "Kontoumsätze",
        "Umsätze aus den Kontoauszügen mit Buchungstag im Geschäftsjahr",
        _columns(
            "Konto",
            "Buchungstag",
            "Wertstellung",
            "Betrag",
            "Richtung",
            "Gegenseite",
            "IBAN Gegenseite",
            "Verwendungszweck",
            "End-to-End-Referenz",
            "Status",
            "Buchungsnummer",
            "Auszug-ID",
            num=("Betrag",),
            date=("Buchungstag", "Wertstellung"),
        ),
    )
    for line in lines:
        ln.add(
            line.account.name,
            _date(line.date),
            _date(line.value_date),
            _money(line.amount),
            "Gutschrift" if line.credit else "Belastung",
            line.name,
            line.iban,
            line.purpose,
            line.end_to_end,
            line.get_status_display(),
            line.booking.display_number if line.booking_id else "",
            line.statement_id,
        )
    return [st, ln]


# Protokolleinträge der Organisation selbst, die die Kasse betreffen
_ORG_KEYS = {
    "Kasse festgeschrieben bis",
    "Datenexport Kasse",
    "steuerliche Bereiche in der Kasse",
    "Buchungsnummern",
    "Zählprotokoll und Kassenbericht",
    "DATEV-Export",
    "DATEV Beraternummer",
    "DATEV Mandantennummer",
    "DATEV Sachkontenlänge",
    "Kontenrahmen",
}


def _has_reserves(org) -> bool:
    from .models import Reserve

    return Reserve.objects.filter(organization=org).exists()


def _reserve_table(org, start, end) -> Table:
    """Rücklagen: Stand zu Beginn, Bewegungen im Jahr, Stand am Ende (C4)."""
    from . import reserves
    from .models import Reserve

    t = Table(
        "ruecklagen.csv",
        "Rücklagen",
        "Rücklagen nach § 62 AO: Stand zu Beginn und am Ende des Geschäftsjahres mit Bewegungen",
        _columns(
            "Rücklage",
            "Art",
            "Zweck",
            "Datum",
            "Bewegung",
            "Betrag",
            "Begründung",
            "erfasst von",
            num=("Betrag",),
            date=("Datum",),
        ),
    )
    before = start - datetime.timedelta(days=1)
    for r in Reserve.objects.filter(organization=org).order_by("name"):
        moves = list(r.movements.filter(date__gte=start, date__lte=end).order_by("date", "pk"))
        opening = reserves.balance(r, before)
        if not moves and not opening:
            continue
        common = (r.name, r.get_kind_display(), r.purpose)
        t.add(*common, _date(start), "Stand zu Beginn", _money(opening), "", "")
        for m in moves:
            t.add(
                *common,
                _date(m.date),
                m.get_direction_display(),
                _money(m.amount),
                m.note,
                m.created_by_name,
            )
        t.add(*common, _date(end), "Stand am Ende", _money(reserves.balance(r, end)), "", "")
    return t


def _cash_count_table(org, start, end, add_file) -> Table:
    from .models import Booking, CashCount

    t = Table(
        "kassenzaehlungen.csv",
        "Kassenzählungen",
        "Zählprotokolle (Kassensturz) und Kassenberichte für Feste (offene Ladenkasse)",
        _columns(
            "ID",
            "Art",
            "Datum",
            "Barkasse",
            "Bezeichnung",
            "gezählt",
            "Soll laut Kassenbuch",
            "Differenz",
            "Anfangsbestand",
            "Ausgaben",
            "Entnahmen",
            "Tageseinnahme",
            "Aufteilung",
            "Bemerkung",
            "gezählt von",
            "zweite Person",
            "Buchungen",
            "erstellt am",
            "PDF",
            "SHA-256 PDF",
            num=(
                "gezählt",
                "Soll laut Kassenbuch",
                "Differenz",
                "Anfangsbestand",
                "Ausgaben",
                "Entnahmen",
                "Tageseinnahme",
            ),
            date=("Datum",),
        ),
    )
    items = (
        CashCount.objects.filter(organization=org, date__gte=start, date__lte=end)
        .select_related("account")
        .order_by("date", "pk")
    )
    for item in items:
        event = item.kind == CashCount.Kind.EVENT
        numbers = [
            b.display_number
            for b in Booking.objects.filter(organization=org, pk__in=item.booking_ids or [])
            .select_related("organization")
            .order_by("number")
        ]
        path = (
            add_file(f"kassenzaehlungen/{item.pk}_{item.date:%Y-%m-%d}.pdf", item.pdf)
            if item.pdf
            else ""
        )
        t.add(
            item.pk,
            item.get_kind_display(),
            _date(item.date),
            item.account.name,
            item.title,
            _money(item.counted),
            "" if event else _money(item.expected),
            "" if event else _money(item.difference),
            _money(item.opening) if event else "",
            _money(item.expenses) if event else "",
            _money(item.withdrawals) if event else "",
            _money(item.takings) if event else "",
            ", ".join(f"{line['name']} {line['amount']}" for line in item.lines or []),
            item.note,
            item.counted_by,
            item.witness,
            ", ".join(numbers),
            _stamp(item.created_at),
            path,
            item.pdf_sha256,
        )
    return t


def _protocol_table(org, start) -> Table:
    from django.apps import apps

    from audit.log import OBJECT_TYPES
    from audit.models import AuditEntry

    types = set()
    for app in ("finance", "billing"):
        for model in apps.get_app_config(app).get_models():
            name = model._meta.model_name
            types.add(OBJECT_TYPES.get(name, name))
    since = timezone.make_aware(datetime.datetime.combine(start, datetime.time.min))
    t = Table(
        "protokoll.csv",
        "Änderungsprotokoll",
        "Änderungen an Finanzdaten ab Beginn des Geschäftsjahres (vorher/nachher als JSON)",
        _columns(
            "Zeitpunkt",
            "Person",
            "Aktion",
            "Objektart",
            "Objekt-ID",
            "Objekt",
            "Änderungen",
            "über",
            "Lfd. Nr.",
            "Prüfsumme Vorgänger",
            "Prüfsumme",
        ),
    )
    entries = AuditEntry.objects.filter(organization=org, timestamp__gte=since).order_by(
        "timestamp", "pk"
    )
    org_type = OBJECT_TYPES["organization"]
    for e in entries.filter(object_type__in=types | {org_type}).iterator():
        if e.object_type == org_type and not (_ORG_KEYS & set(e.changes or {})):
            continue
        t.add(
            _stamp(e.timestamp),
            e.user_email,
            e.get_action_display(),
            e.object_type,
            e.object_id,
            e.object_repr,
            json.dumps(e.changes, ensure_ascii=False, default=str),
            e.via,
            e.seq if e.seq is not None else "",
            e.prev_hash,
            e.hash,
        )
    return t


def _chain_report(org) -> bytes:
    """Ergebnis der Kettenprüfung des gesamten Änderungsprotokolls zum Exportzeitpunkt."""
    from audit.chain import seal, verify

    seal(org.pk)
    r = verify(org.pk)
    lines = [
        f"Prüfung des Änderungsprotokolls von {org.name}, {timezone.localtime():%d.%m.%Y %H:%M}",
        "",
        "Jeder Eintrag enthält die SHA-256-Prüfsumme seines Vorgängers (Spalten in",
        "protokoll.csv). Geprüft wurde die ganze Kette, nicht nur die Finanzdaten.",
        "",
        f"Einträge: {r['entries']}",
        f"Ergebnis: {'unverändert' if r['ok'] else 'VERÄNDERT'}",
    ]
    if r["cleared"]:
        lines.append(f"Inhalt aus Datenschutzgründen geleert (Löschfrist): {r['cleared']} Einträge")
    if r["head_seq"]:
        lines.append(f"Letzter Eintrag: Nr. {r['head_seq']}, Prüfsumme {r['head_hash']}")
    lines += [f"- {p}" for p in r["problems"]]
    lines += [
        "",
        "Die Prüfsumme des letzten Eintrags gehört mit dem Export ins Archiv: So fällt auch",
        "auf, wenn später Einträge am Ende entfernt werden.",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")
