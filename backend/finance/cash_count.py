"""Zählprotokoll und Kassenbericht für Feste (Finanzamt-Prüfung B2).

Zählprotokoll (Kassensturz): Bargeld nach Stückelung zählen, mit dem Bestand laut
Kassenbuch vergleichen; eine Differenz wird mit Grund als Buchung „Kassendifferenz“ erfasst.

Kassenbericht (offene Ladenkasse, z. B. Getränkeverkauf am Fest): Die Tageseinnahme
ergibt sich rückwärts aus gezähltem Endbestand − Anfangsbestand + bar bezahlten Ausgaben +
Entnahmen (Anwendungserlass zu § 146 AO). Sie wird je Kategorie als Einnahme gebucht.

Beide werden einmal erstellt und nicht mehr geändert; das PDF hängt als Beleg an den
Buchungen und liegt mit Prüfsumme am Protokoll.
"""

from __future__ import annotations

import datetime
import hashlib
import io
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from organizations.theme import effective_theme

from . import services
from .models import DENOMINATIONS, Account, Booking, CashCount, Category, Project, Receipt
from .report import _euro, _styles, _table

ZERO = Decimal("0.00")


def _amount(value, field: str) -> Decimal:
    try:
        result = Decimal(str(value if value not in (None, "") else "0")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError({field: gettext("Bitte einen Betrag angeben.")}) from exc
    if result < 0:
        raise ValidationError({field: gettext("Der Betrag darf nicht negativ sein.")})
    return result


def count_total(denominations: dict) -> tuple[dict, Decimal]:
    """Bereinigte Stückelung und Summe."""
    clean: dict[str, int] = {}
    total = 0
    for key, raw in (denominations or {}).items():
        try:
            cents, n = int(key), int(raw or 0)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                {"denominations": gettext("Bitte ganze Stückzahlen angeben.")}
            ) from exc
        if cents not in DENOMINATIONS or n < 0 or n > 100000:
            raise ValidationError({"denominations": gettext("Unbekannte Stückelung oder Anzahl.")})
        if n:
            clean[str(cents)] = n
            total += cents * n
    return clean, (Decimal(total) / 100).quantize(Decimal("0.01"))


def _label(cents: int) -> str:
    return f"{cents // 100} €" if cents >= 100 else f"{cents} ct"


def _booking(org, user, *, account, date, kind, amount, category, text, project=None):
    year = org.fiscal_year_of(date)
    booking = Booking(
        organization=org,
        year=year,
        number=services.next_number(org.pk, year),
        date=date,
        kind=kind,
        amount=amount,
        account=account,
        category=category,
        text=text[:200],
        reference="Kassenzählung",
        project=project,
        created_by=user,
    )
    booking.full_clean(exclude=["organization", "created_by"])
    booking.save()
    return booking


def _category(org, raw, kind: str, field: str) -> Category:
    cat = Category.objects.filter(organization=org, pk=raw, is_active=True).first() if raw else None
    if cat is None:
        raise ValidationError({field: gettext("Bitte eine Kategorie wählen.")})
    if cat.kind not in (kind, Category.Kind.BOTH):
        raise ValidationError(
            {
                field: gettext("Die Kategorie „{name}“ passt nicht zur Buchungsart.").format(
                    name=cat.name
                )
            }
        )
    return cat


@transaction.atomic
def create(org, user, data: dict) -> CashCount:
    if not org.cash_counts_enabled:
        raise ValidationError(gettext("Zählprotokoll und Kassenbericht sind nicht eingeschaltet."))
    kind = data.get("kind")
    if kind not in CashCount.Kind.values:
        raise ValidationError({"kind": gettext("Bitte Zählprotokoll oder Kassenbericht wählen.")})
    account = Account.objects.filter(organization=org, pk=data.get("account") or 0).first()
    if account is None or account.kind != Account.Kind.CASH or not account.is_active:
        raise ValidationError({"account": gettext("Bitte eine aktive Barkasse wählen.")})
    try:
        date = datetime.date.fromisoformat(str(data.get("date")))
    except ValueError as exc:
        raise ValidationError({"date": gettext("Bitte ein Datum angeben.")}) from exc
    if date > timezone.localdate():
        raise ValidationError(
            {"date": gettext("Gezählt wird heute oder an einem vergangenen Tag.")}
        )
    if reason := services.fixed_on(org, date, timezone.now()):
        raise ValidationError({"date": "Die Kasse ist an diesem Tag festgeschrieben" + reason})
    services.ensure_open(org, date=date)
    counted_by = str(data.get("counted_by") or "").strip()[:200]
    if not counted_by:
        raise ValidationError({"counted_by": gettext("Bitte angeben, wer gezählt hat.")})
    project = None
    if data.get("project"):
        project = Project.objects.filter(organization=org, pk=data["project"]).first()
        if project is None:
            raise ValidationError({"project": gettext("Unbekannte Veranstaltung.")})
    denominations, counted = count_total(data.get("denominations") or {})
    note = str(data.get("note") or "").strip()[:500]
    record = CashCount(
        organization=org,
        kind=kind,
        account=account,
        date=date,
        title=str(data.get("title") or "").strip()[:200],
        project=project,
        denominations=denominations,
        counted=counted,
        note=note,
        counted_by=counted_by,
        witness=str(data.get("witness") or "").strip()[:200],
        created_by=user,
    )
    # Bestand laut Kassenbuch am Ende des Tages (vor den neuen Buchungen)
    services.ensure_cash_ok([account], date)
    record.expected = services.balances(org.pk, before=date + datetime.timedelta(days=1))[
        account.pk
    ]
    bookings: list[Booking] = []
    if kind == CashCount.Kind.COUNT:
        diff = record.difference
        if diff:
            if len(note) < 5:
                raise ValidationError(
                    {
                        "note": gettext(
                            "Bei einer Differenz bitte den Grund angeben (mind. 5 Zeichen)."
                        )
                    }
                )
            booking_kind = Booking.Kind.INCOME if diff > 0 else Booking.Kind.EXPENSE
            cat = _category(org, data.get("category"), booking_kind, "category")
            bookings.append(
                _booking(
                    org,
                    user,
                    account=account,
                    date=date,
                    kind=booking_kind,
                    amount=abs(diff),
                    category=cat,
                    text=f"Kassendifferenz laut Zählprotokoll: {note}",
                    project=project,
                )
            )
    else:
        if not record.title:
            raise ValidationError(
                {"title": gettext("Bitte das Fest bzw. den Verkaufsstand angeben.")}
            )
        record.opening = _amount(data.get("opening"), "opening")
        record.expenses = _amount(data.get("expenses"), "expenses")
        record.withdrawals = _amount(data.get("withdrawals"), "withdrawals")
        takings = record.takings
        if takings < 0:
            raise ValidationError(
                gettext(
                    "Die Tageseinnahme wäre negativ. Bitte Anfangsbestand, Ausgaben und "
                    "Entnahmen prüfen."
                )
            )
        lines = []
        for i, line in enumerate(data.get("lines") or []):
            amount = _amount(line.get("amount"), f"lines.{i}")
            if not amount:
                continue
            cat = _category(org, line.get("category"), Booking.Kind.INCOME, f"lines.{i}")
            lines.append((cat, amount))
        total = sum((a for _, a in lines), ZERO)
        if total != takings:
            raise ValidationError(
                {
                    "lines": gettext(
                        "Die Aufteilung ergibt {x}, die Tageseinnahme ist {x2}."
                    ).format(x=_euro(total), x2=_euro(takings))
                }
            )
        record.lines = [{"category": c.pk, "name": c.name, "amount": f"{a:.2f}"} for c, a in lines]
        for cat, amount in lines:
            bookings.append(
                _booking(
                    org,
                    user,
                    account=account,
                    date=date,
                    kind=Booking.Kind.INCOME,
                    amount=amount,
                    category=cat,
                    text=f"Tageseinnahme {record.title} ({cat.name}) laut Kassenbericht",
                    project=project,
                )
            )
    services.ensure_cash_ok([account], date)
    record.booking_ids = [b.pk for b in bookings]
    record.save()
    content = render(record, bookings)
    name = f"{record.get_kind_display()}-{date:%Y-%m-%d}-{record.pk}.pdf"
    record.pdf.save(name, ContentFile(content), save=False)
    record.pdf_sha256 = hashlib.sha256(content).hexdigest()
    record.save(update_fields=["pdf", "pdf_sha256"])
    for b in bookings:
        doc = Receipt(
            organization=org,
            booking=b,
            name=name,
            content_type="application/pdf",
            size=len(content),
            uploaded_by=user,
        )
        doc.file.save(name, ContentFile(content), save=False)
        doc.save()
    return record


def render(record: CashCount, bookings: list[Booking]) -> bytes:
    org = record.organization
    st = _styles()
    primary = colors.HexColor(effective_theme(org.ancestors())["primary"])
    r, rb = st["right"], st["right_bold"]
    head = record.get_kind_display()
    if record.title:
        head += f": {record.title}"
    story: list = [
        Paragraph(f"<b>{escape(head)}</b>", st["title"]),
        Paragraph(
            f"{escape(org.name)} · {escape(record.account.name)} · {record.date:%d.%m.%Y}"
            + (f" · Veranstaltung {escape(record.project.name)}" if record.project else ""),
            st["normal"],
        ),
        Spacer(1, 4 * mm),
        Paragraph("<b>Gezählter Bestand</b>", st["h2"]),
    ]
    rows = [[Paragraph("<b>Stückelung</b>", st["normal"]), Paragraph("<b>Anzahl</b>", r)]]
    rows[0].append(Paragraph("<b>Betrag</b>", r))
    for cents in DENOMINATIONS:
        n = record.denominations.get(str(cents), 0)
        if n:
            rows.append(
                [
                    Paragraph(_label(cents), st["normal"]),
                    Paragraph(str(n), r),
                    Paragraph(_euro(Decimal(cents * n) / 100), r),
                ]
            )
    rows.append(
        [
            Paragraph("<b>Summe</b>", st["normal"]),
            Paragraph("", r),
            Paragraph(_euro(record.counted), rb),
        ]
    )
    story.append(_table(rows, [40 * mm, 25 * mm, 35 * mm], primary))

    story.append(Paragraph("<b>Ergebnis</b>", st["h2"]))
    if record.kind == CashCount.Kind.COUNT:
        rows = [
            [
                Paragraph("Bestand laut Kassenbuch", st["normal"]),
                Paragraph(_euro(record.expected), r),
            ],
            [Paragraph("gezählt", st["normal"]), Paragraph(_euro(record.counted), r)],
            [Paragraph("<b>Differenz</b>", st["normal"]), Paragraph(_euro(record.difference), rb)],
        ]
    else:
        rows = [
            [Paragraph("gezählter Endbestand", st["normal"]), Paragraph(_euro(record.counted), r)],
            [
                Paragraph("− Anfangsbestand (Wechselgeld)", st["normal"]),
                Paragraph(_euro(record.opening), r),
            ],
            [
                Paragraph("+ bar bezahlte Ausgaben", st["normal"]),
                Paragraph(_euro(record.expenses), r),
            ],
            [Paragraph("+ Entnahmen", st["normal"]), Paragraph(_euro(record.withdrawals), r)],
            [Paragraph("<b>Tageseinnahme</b>", st["normal"]), Paragraph(_euro(record.takings), rb)],
        ]
    story.append(_table(rows, [75 * mm, 35 * mm], primary))
    if record.lines:
        story.append(Paragraph("<b>Aufteilung der Einnahme</b>", st["h2"]))
        rows = [[Paragraph("<b>Kategorie</b>", st["normal"]), Paragraph("<b>Betrag</b>", r)]]
        rows += [
            [Paragraph(escape(line["name"]), st["normal"]), Paragraph(_euro(line["amount"]), r)]
            for line in record.lines
        ]
        story.append(_table(rows, [75 * mm, 35 * mm], primary, total_row=False))
    if record.note:
        story.append(Paragraph(f"<b>Bemerkung:</b> {escape(record.note)}", st["normal"]))
    if bookings:
        numbers = ", ".join(b.display_number for b in bookings)
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(f"Gebucht als {escape(numbers)}.", st["normal"]))
    story += [
        Spacer(1, 10 * mm),
        Paragraph(
            f"Gezählt von {escape(record.counted_by)}"
            + (f", zweite Person: {escape(record.witness)}" if record.witness else ""),
            st["normal"],
        ),
        Paragraph(
            f"Erstellt am {timezone.localtime(record.created_at or timezone.now()):%d.%m.%Y %H:%M} "
            "in HUBIplan; das Protokoll lässt sich danach nicht mehr ändern.",
            st["small"],
        ),
    ]
    buf = io.BytesIO()
    SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, title=head
    ).build(story)
    return buf.getvalue()
