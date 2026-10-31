"""DATEV-Export für die Steuerberatung: Buchungsstapel im DATEV-Format (EXTF, Version 700).

Zuschaltbar je Einheit (Finanzamt-Prüfung B6). Jedes Konto bekommt ein DATEV-Finanzkonto
(z. B. 1200 Bank, 1000 Kasse), jede Kategorie ein Sachkonto. Daraus wird je Buchung:

- Einnahme: Finanzkonto im Soll an Sachkonto der Kategorie
- Ausgabe: Finanzkonto im Haben an Sachkonto der Kategorie
- Umbuchung: Zielkonto im Soll an Ausgangskonto

Stornos sind normale Gegenbuchungen und gehen genauso hinüber. Belegfeld 1 ist die
Buchungsnummer, damit sich jede Zeile dem Beleg in HUBIplan zuordnen lässt.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Booking

COLUMNS = [
    "Umsatz (ohne Soll/Haben-Kz)",
    "Soll/Haben-Kennzeichen",
    "WKZ Umsatz",
    "Kurs",
    "Basis-Umsatz",
    "WKZ Basis-Umsatz",
    "Konto",
    "Gegenkonto (ohne BU-Schlüssel)",
    "BU-Schlüssel",
    "Belegdatum",
    "Belegfeld 1",
    "Belegfeld 2",
    "Skonto",
    "Buchungstext",
]


def _q(text: str) -> str:
    """Textfeld in Anführungszeichen; Anführungszeichen verdoppelt, keine Zeilenumbrüche."""
    clean = " ".join(str(text or "").split()).replace('"', '""')
    return f'"{clean}"'


def _amount(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",")


def check_settings(org) -> list[str]:
    problems = []
    if not org.datev_enabled:
        problems.append("Der DATEV-Export ist nicht eingeschaltet.")
    if not (org.datev_consultant or "").isdigit():
        problems.append("Beraternummer fehlt.")
    if not (org.datev_client or "").isdigit():
        problems.append("Mandantennummer fehlt.")
    return problems


def rows(org, start: datetime.date, end: datetime.date) -> tuple[list[list[str]], list[str]]:
    """Zeilen des Buchungsstapels und fehlende Kontenzuordnungen."""
    bookings = (
        Booking.objects.filter(organization=org, date__gte=start, date__lte=end)
        .select_related("account", "to_account", "category", "organization")
        .order_by("date", "year", "number")
    )
    out: list[list[str]] = []
    missing: set[str] = set()
    for b in bookings:
        account = b.account.datev_account
        if not account:
            missing.add(f"Konto „{b.account.name}“")
        if b.kind == Booking.Kind.TRANSFER:
            target = b.to_account.datev_account if b.to_account else ""
            if b.to_account and not target:
                missing.add(f"Konto „{b.to_account.name}“")
            konto, gegen, sh = target, account, "S"
        else:
            cat = b.category.datev_account if b.category else ""
            if not cat:
                missing.add(f"Kategorie „{b.category.name if b.category else 'ohne'}“")
            konto, gegen = account, cat
            sh = "S" if b.kind == Booking.Kind.INCOME else "H"
        text = b.text
        if b.counterparty:
            text = f"{b.counterparty}: {text}"
        out.append(
            [
                _amount(b.amount),
                f'"{sh}"',
                '"EUR"',
                "",
                "",
                "",
                konto,
                gegen,
                "",
                f"{b.date:%d%m}",
                _q(b.display_number[:36]),
                _q((b.reference or "")[:12]),
                "",
                _q(text[:60]),
            ]
        )
    return out, sorted(missing)


def build(org, start: datetime.date, end: datetime.date, fiscal_start: datetime.date) -> bytes:
    problems = check_settings(org)
    lines, missing = rows(org, start, end)
    if missing:
        problems.append("Ohne DATEV-Konto: " + ", ".join(missing) + ".")
    if problems:
        raise ValidationError(" ".join(problems))
    now = timezone.localtime()
    header = [
        '"EXTF"',
        "700",
        "21",
        '"Buchungsstapel"',
        "13",
        now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}",
        "",
        '"RE"',
        _q("HUBIplan"),
        '""',
        org.datev_consultant,
        org.datev_client,
        f"{fiscal_start:%Y%m%d}",
        str(org.datev_account_length or 4),
        f"{start:%Y%m%d}",
        f"{end:%Y%m%d}",
        _q(f"HUBIplan {start:%d.%m.%Y}–{end:%d.%m.%Y}"[:30]),
        '""',
        "1",
        "0",
        "0",
        '"EUR"',
        "",
        '""',
        "",
        "",
        _q("".join(c for c in org.datev_chart if c.isdigit())[:2]),
        "",
        "",
        '""',
        '""',
    ]
    text = "\r\n".join(
        [";".join(header), ";".join(_q(c) for c in COLUMNS), *(";".join(r) for r in lines)]
    )
    # DATEV erwartet Windows-1252 (ANSI)
    return (text + "\r\n").encode("cp1252", errors="replace")
