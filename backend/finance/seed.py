"""Erfundene Kassendaten für die Demodaten der Pilotorganisationen (deterministisch).

Konten, Kategorien und Buchungen im laufenden Geschäftsjahr, bis zum heutigen
Tag. Buchungen durchlaufen dieselbe Prüfung wie in der Oberfläche
(``full_clean``) und bekommen ihre Nummer wie dort (``next_number``).
"""

from __future__ import annotations

import datetime
import random
from decimal import Decimal

from django.utils import timezone

from members.models import Membership
from organizations.models import Department, Organization

from . import services
from .models import Account, Booking, Category, TaxArea

INCOME, EXPENSE, TRANSFER = Booking.Kind.INCOME, Booking.Kind.EXPENSE, Booking.Kind.TRANSFER

# Erfundene Bankleitzahl, nur für Demodaten
DEMO_BLZ = "12345678"


def demo_iban(account_number: int) -> str:
    """Gültige (Prüfziffer), aber erfundene deutsche IBAN."""
    bban = f"{DEMO_BLZ}{account_number:010d}"
    check = 98 - int(bban + "131400") % 97  # "DE" = 13 14, Prüfziffer 00
    return f"DE{check:02d}{bban}"


CLUB_ACCOUNTS = [
    # (Name, Art, Anfangsbestand, Kontonummer)
    ("Girokonto", Account.Kind.BANK, "8420.37", 4711),
    ("Barkasse", Account.Kind.CASH, "350.00", None),
    ("Sparkonto Rücklage", Account.Kind.SAVINGS, "15000.00", 4712),
]

CLUB_CATEGORIES = [
    # (Name, Art, steuerlicher Bereich)
    ("Mitgliedsbeiträge", Category.Kind.INCOME, TaxArea.IDEAL),
    ("Spenden", Category.Kind.INCOME, TaxArea.IDEAL),
    ("Zinsen", Category.Kind.INCOME, TaxArea.ASSETS),
    ("Schützenfest Festzelt", Category.Kind.BOTH, TaxArea.BUSINESS),
    ("Schützenfest Getränke", Category.Kind.BOTH, TaxArea.BUSINESS),
    ("Musik und Fanfaren-Corps", Category.Kind.EXPENSE, TaxArea.PURPOSE),
    ("Saalmiete", Category.Kind.EXPENSE, TaxArea.IDEAL),
    ("Ehrungen und Orden", Category.Kind.EXPENSE, TaxArea.IDEAL),
    ("Verbandsbeitrag", Category.Kind.EXPENSE, TaxArea.IDEAL),
    ("Versicherungen", Category.Kind.EXPENSE, TaxArea.IDEAL),
    ("Bankgebühren", Category.Kind.EXPENSE, TaxArea.IDEAL),
    ("Bürobedarf und Porto", Category.Kind.EXPENSE, TaxArea.IDEAL),
    ("Zugzuschüsse", Category.Kind.EXPENSE, TaxArea.IDEAL),
]

# Erfundene Geschäfte und Dienstleister für die Demodaten (nach Buchungstext)
DEMO_PARTNERS = {
    "Kontoführungsgebühren": "Musterbank (erfunden)",
    "Kontoführungsgebühren Quartal": "Musterbank (erfunden)",
    "Gebühr Rücklastschrift Beitrag": "Musterbank (erfunden)",
    "Saalmiete Vereinslokal": "Gaststätte Zur Linde (erfunden)",
    "Vereinshaftpflicht und Unfall": "Beispiel Versicherung AG (erfunden)",
    "Verbandsversicherung": "Beispiel Versicherung AG (erfunden)",
    "Verbandsbeitrag an den Bürger-Schützenverein": "Bürger-Schützenverein",
    "Anzahlung Festzeltmiete": "Festzeltbau Mustermann GmbH (erfunden)",
    "Restzahlung Festzeltmiete": "Festzeltbau Mustermann GmbH (erfunden)",
    "Getränkelieferung Schützenfest": "Getränke Beispiel KG (erfunden)",
    "Pfandrückgabe Getränke": "Getränke Beispiel KG (erfunden)",
    "Notenmaterial Fanfaren-Corps": "Musikhaus Notenblatt (erfunden)",
    "Musikkapelle Festumzug": "Blasorchester Beispielstadt (erfunden)",
    "Reparatur Fanfaren": "Musikhaus Notenblatt (erfunden)",
    "Verbandsorden Schützenfest": "Ordenmanufaktur Muster (erfunden)",
    "Orden und Ehrennadeln": "Ordenmanufaktur Muster (erfunden)",
    "Spende Bäckerei am Markt (erfunden)": "Bäckerei am Markt (erfunden)",
}

FEDERATION_ACCOUNTS = [("Girokonto", Account.Kind.BANK, "3125.80", 1855)]

FEDERATION_CATEGORIES = [
    ("Beiträge der Vereine", Category.Kind.INCOME, TaxArea.IDEAL),
    ("Ehrungen und Orden", Category.Kind.EXPENSE, TaxArea.IDEAL),
    ("Versicherungen", Category.Kind.EXPENSE, TaxArea.IDEAL),
    ("Bankgebühren", Category.Kind.EXPENSE, TaxArea.IDEAL),
]


def _club_plan(rnd: random.Random) -> list[dict]:
    """Buchungen des Vereins als (Monat, Tag) im Geschäftsjahr."""
    plan: list[dict] = []

    def add(month, day, kind, amount, text, account="Girokonto", **extra):
        plan.append(
            {
                "month": month,
                "day": day,
                "kind": kind,
                "amount": Decimal(amount),
                "text": text,
                "account": account,
                **extra,
            }
        )

    # Laufende Kosten
    for month in range(1, 13):
        fee = f"{rnd.randint(1150, 1450) / 100:.2f}"
        add(month, 28, EXPENSE, fee, "Kontoführungsgebühren", category="Bankgebühren")
    for month in (1, 2, 3, 4, 5, 6, 9, 10, 11, 12):
        add(
            month,
            5,
            EXPENSE,
            "180.00",
            "Saalmiete Vereinslokal",
            category="Saalmiete",
            reference=f"Rg. {month:02d}",
        )
    # Beiträge: Sammellastschriften und einzelne Überweisungen
    for day, amount, part in ((15, "6840.00", "A–K"), (16, "5760.00", "L–Z")):
        add(
            2,
            day,
            INCOME,
            amount,
            f"Beitragseinzug Lastschrift {part}",
            category="Mitgliedsbeiträge",
            reference="SEPA-Sammler",
        )
    for month, day in ((3, 4), (3, 18), (4, 9), (5, 22), (6, 3)):
        add(
            month,
            day,
            INCOME,
            "72.00",
            "Mitgliedsbeitrag Überweisung",
            category="Mitgliedsbeiträge",
            member=True,
        )
    add(
        3,
        11,
        EXPENSE,
        "3.50",
        "Gebühr Rücklastschrift Beitrag",
        category="Bankgebühren",
        member=True,
    )
    # Spenden
    for month, day, amount, text in (
        (1, 12, "250.00", "Spende Neujahrsempfang"),
        (5, 8, "500.00", "Spende Bäckerei am Markt (erfunden)"),
        (8, 30, "300.00", "Spende Festbesucher"),
        (11, 19, "150.00", "Spende Martinsfeuer"),
    ):
        add(month, day, INCOME, amount, text, category="Spenden")
    # Versicherungen und Verband
    add(
        1,
        20,
        EXPENSE,
        "612.40",
        "Vereinshaftpflicht und Unfall",
        category="Versicherungen",
        reference="Police 77-001",
    )
    add(
        3,
        1,
        EXPENSE,
        "1480.00",
        "Verbandsbeitrag an den Bürger-Schützenverein",
        category="Verbandsbeitrag",
    )
    # Schützenfest (Ende August)
    add(
        6,
        15,
        EXPENSE,
        "2500.00",
        "Anzahlung Festzeltmiete",
        category="Schützenfest Festzelt",
        reference="AB-2026-17",
    )
    add(7, 31, TRANSFER, "800.00", "Wechselgeld für das Schützenfest", to_account="Barkasse")
    add(
        8,
        22,
        EXPENSE,
        "3970.00",
        "Restzahlung Festzeltmiete",
        category="Schützenfest Festzelt",
        reference="RE-2026-88",
    )
    add(
        8,
        22,
        EXPENSE,
        "4215.60",
        "Getränkelieferung Schützenfest",
        category="Schützenfest Getränke",
        reference="RE-4410",
    )
    add(
        8,
        23,
        INCOME,
        "2350.00",
        "Eintritt Festzelt Samstag",
        account="Barkasse",
        category="Schützenfest Festzelt",
    )
    add(
        8,
        24,
        INCOME,
        "1980.00",
        "Eintritt Festzelt Sonntag",
        account="Barkasse",
        category="Schützenfest Festzelt",
    )
    add(
        8,
        24,
        INCOME,
        "5120.50",
        "Getränkeverkauf Festzelt",
        account="Barkasse",
        category="Schützenfest Getränke",
    )
    add(
        8,
        25,
        INCOME,
        "3045.00",
        "Getränkeverkauf Frühschoppen",
        account="Barkasse",
        category="Schützenfest Getränke",
    )
    add(
        8,
        26,
        TRANSFER,
        "11500.00",
        "Einzahlung Festeinnahmen",
        account="Barkasse",
        to_account="Girokonto",
    )
    add(9, 2, INCOME, "640.00", "Pfandrückgabe Getränke", category="Schützenfest Getränke")
    # Musik und Fanfaren-Corps
    add(
        4,
        14,
        EXPENSE,
        "420.00",
        "Notenmaterial Fanfaren-Corps",
        category="Musik und Fanfaren-Corps",
        department="Hubertus Fanfaren-Corps",
    )
    add(
        8,
        20,
        EXPENSE,
        "2200.00",
        "Musikkapelle Festumzug",
        category="Musik und Fanfaren-Corps",
        reference="RE-M-12",
    )
    add(
        10,
        7,
        EXPENSE,
        "865.00",
        "Reparatur Fanfaren",
        category="Musik und Fanfaren-Corps",
        department="Hubertus Fanfaren-Corps",
    )
    # Ehrungen
    add(
        5,
        30,
        EXPENSE,
        "348.50",
        "Orden und Ehrennadeln",
        category="Ehrungen und Orden",
        reference="RE-O-5",
    )
    add(8, 18, EXPENSE, "189.00", "Königsplakette Gravur", category="Ehrungen und Orden")
    add(11, 28, EXPENSE, "96.00", "Urkunden Jubilare", category="Ehrungen und Orden")
    # Zugzuschüsse
    for month, day, zug in ((3, 21, "Herolde"), (6, 12, "Dicke Fründe"), (9, 19, "Jot drop")):
        add(
            month,
            day,
            EXPENSE,
            "150.00",
            f"Zuschuss Zugabend {zug}",
            category="Zugzuschüsse",
            department=zug,
        )
    # Kleinbeträge bar
    for month, day, amount, text in (
        (1, 9, "23.80", "Briefmarken Einladungen"),
        (2, 3, "41.15", "Druckerpapier und Toner"),
        (4, 27, "18.90", "Porto Jahreshauptversammlung"),
        (9, 12, "32.40", "Kerzen und Dekoration"),
    ):
        add(month, day, EXPENSE, amount, text, account="Barkasse", category="Bürobedarf und Porto")
    add(1, 8, TRANSFER, "200.00", "Bargeldabhebung für die Barkasse", to_account="Barkasse")
    # Rücklage und Zinsen
    add(9, 15, TRANSFER, "5000.00", "Rücklage Schützenfest", to_account="Sparkonto Rücklage")
    add(
        6,
        30,
        INCOME,
        "37.50",
        "Zinsen erstes Halbjahr",
        account="Sparkonto Rücklage",
        category="Zinsen",
    )
    add(
        12,
        31,
        INCOME,
        "41.20",
        "Zinsen zweites Halbjahr",
        account="Sparkonto Rücklage",
        category="Zinsen",
    )
    return plan


def _federation_plan(rnd: random.Random) -> list[dict]:
    plan = [
        {
            "month": 3,
            "day": 3,
            "kind": INCOME,
            "amount": Decimal("1480.00"),
            "text": "Verbandsbeitrag Hubertus-Schützenverein",
            "category": "Beiträge der Vereine",
        },
        {
            "month": 1,
            "day": 22,
            "kind": EXPENSE,
            "amount": Decimal("298.00"),
            "text": "Verbandsversicherung",
            "category": "Versicherungen",
        },
        {
            "month": 7,
            "day": 10,
            "kind": EXPENSE,
            "amount": Decimal("412.30"),
            "text": "Verbandsorden Schützenfest",
            "category": "Ehrungen und Orden",
        },
    ]
    for month in (3, 6, 9, 12):
        plan.append(
            {
                "month": month,
                "day": 30,
                "kind": EXPENSE,
                "amount": Decimal(f"{rnd.randint(890, 1190) / 100:.2f}"),
                "text": "Kontoführungsgebühren Quartal",
                "category": "Bankgebühren",
            }
        )
    for entry in plan:
        entry.setdefault("account", "Girokonto")
    return plan


def seed_finance(orgs: dict[str, Organization], today: datetime.date | None = None) -> None:
    """Kassendaten anlegen; vorhandene Buchungen bleiben unverändert."""
    today = today or timezone.localdate()
    club, federation = orgs["club"], orgs["federation"]
    if not club.tax_areas_enabled and not Booking.objects.filter(organization=club).exists():
        club.tax_areas_enabled = True
        club.save(update_fields=["tax_areas_enabled"])
    rnd = random.Random(1855)  # noqa: S311 – nur Testdaten
    _seed_org(club, CLUB_ACCOUNTS, CLUB_CATEGORIES, _club_plan(rnd), today, "Kreissparkasse")
    _seed_org(
        federation,
        FEDERATION_ACCOUNTS,
        FEDERATION_CATEGORIES,
        _federation_plan(rnd),
        today,
        "Kreissparkasse",
    )


def _seed_org(org, accounts, categories, plan, today, bank_name) -> None:
    year = org.fiscal_year_of(today)
    start, _ = org.fiscal_range(year)
    accs = {}
    for position, (name, kind, opening, number) in enumerate(accounts):
        accs[name], _ = Account.objects.get_or_create(
            organization=org,
            name=name,
            defaults={
                "kind": kind,
                "opening_balance": Decimal(opening),
                "opening_date": start,
                "iban": demo_iban(number) if number else "",
                "bank_name": bank_name if number else "",
                "position": position,
            },
        )
    cats = {}
    for name, kind, area in categories:
        cats[name], _ = Category.objects.get_or_create(
            organization=org,
            name=name,
            defaults={"kind": kind, "tax_area": area if org.tax_areas_enabled else ""},
        )
    if Booking.objects.filter(organization=org).exists():
        return
    members = list(
        Membership.objects.filter(organization=org, periods__exit_date__isnull=True)
        .order_by("pk")
        .distinct()[:40]
    )
    rnd = random.Random(org.pk)  # noqa: S311 – nur Testdaten
    entries = []
    for entry in plan:
        date = _date_in_year(start, entry["month"], entry["day"])
        if date is None or date > today or date < start:
            continue
        entries.append((date, entry))
    for date, entry in sorted(entries, key=lambda e: e[0]):
        booking = Booking(
            organization=org,
            year=year,
            number=services.next_number(org.pk, year),
            date=date,
            kind=entry["kind"],
            amount=entry["amount"],
            account=accs[entry["account"]],
            to_account=accs.get(entry.get("to_account", "")),
            category=cats.get(entry.get("category", "")),
            text=entry["text"],
            reference=entry.get("reference", ""),
            counterparty=entry.get("partner") or DEMO_PARTNERS.get(entry["text"], ""),
        )
        if entry.get("member") and members:
            booking.membership = rnd.choice(members)
            person = booking.membership.person
            booking.text = f"{entry['text']} {person.first_name} {person.last_name}"
            booking.counterparty = f"{person.first_name} {person.last_name}"
        if dept := entry.get("department"):
            booking.department = Department.objects.filter(organization=org, name=dept).first()
        booking.full_clean()
        booking.save()


def _date_in_year(start: datetime.date, month: int, day: int) -> datetime.date | None:
    year = start.year if month >= start.month else start.year + 1
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def seed_projects(orgs: dict[str, Organization], today: datetime.date | None = None) -> None:
    """Beispiel-Veranstaltung „Schützenfest“ mit den passenden Buchungen des Vereins.

    Nur, solange der Verein noch keine Veranstaltung hat.
    """
    from .models import Project, ProjectSeries

    today = today or timezone.localdate()
    club = orgs["club"]
    if Project.objects.filter(organization=club).exists():
        return
    year = club.fiscal_year_of(today)
    bookings = Booking.objects.filter(organization=club, year=year).exclude(
        kind=Booking.Kind.TRANSFER
    )
    fest = bookings.filter(category__name__startswith="Schützenfest") | bookings.filter(
        text__in=["Musikkapelle Festumzug", "Spende Festbesucher"]
    )
    opening = bookings.filter(text="Eintritt Festzelt Samstag").first()
    start = opening.date if opening else _date_in_year(club.fiscal_range(year)[0], 8, 29)
    end = start + datetime.timedelta(days=2)
    series, _ = ProjectSeries.objects.get_or_create(organization=club, name="Schützenfest")
    project = Project.objects.create(
        organization=club,
        series=series,
        name=f"Schützenfest {start.year}",
        starts_on=start,
        ends_on=end,
        status=Project.Status.DONE if end < today else Project.Status.PLANNED,
        description="Beispiel: Festzelt, Getränke und Musik des Schützenfests (erfundene Zahlen).",
    )
    fest.update(project=project)
