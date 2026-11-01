"""Fachlogik: Beitragsberechnung, Beitragsläufe, Rechnungsnummern, Zahlungen."""

from __future__ import annotations

import calendar
import datetime
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext

from access.catalog import DEPT_INVOICES_VIEW
from finance import services as finance_services
from finance.models import Booking
from members.honorary import adjusted_fee
from members.models import (
    DepartmentRoleHolder,
    HonoraryTitle,
    HonoraryTitleAward,
    Membership,
)
from members.services import contact_for, shared_contacts
from organizations.terms import fill

from .models import (
    PERIODS_PER_YEAR,
    ZERO,
    AgeRate,
    BillingSettings,
    Dunning,
    DunningLevel,
    FeeRate,
    FeeRun,
    Invoice,
    InvoiceLine,
    Mandate,
    Payment,
    Rhythm,
)

CENT = Decimal("0.01")
MONTHS = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]


def settings_for(org) -> BillingSettings:
    obj, _ = BillingSettings.objects.get_or_create(organization=org)
    return obj


# --- Zeiträume ---


def add_months(day: datetime.date, months: int) -> datetime.date:
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    return datetime.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class Period:
    year: int
    index: int  # 1-basiert
    rhythm: str
    start: datetime.date
    end: datetime.date
    months: int
    label: str
    # Erster Tag des Geschäftsjahres: Monatsgrenzen zählen von hier aus (Monatsende!)
    first: datetime.date | None = None


def period(org, year: int, rhythm: str, index: int) -> Period:
    count = PERIODS_PER_YEAR[rhythm]
    if not 1 <= index <= count:
        raise ValidationError({"period": gettext("Diesen Abrechnungszeitraum gibt es nicht.")})
    months = 12 // count
    first = org.fiscal_start(year)
    start = add_months(first, months * (index - 1))
    end = add_months(first, months * index) - datetime.timedelta(days=1)
    fy = org.fiscal_label(year)
    if rhythm == Rhythm.YEARLY:
        label = f"Geschäftsjahr {fy}" if not org.fiscal_is_calendar else str(year)
    elif rhythm == Rhythm.HALFYEARLY:
        label = f"{index}. Halbjahr {fy}"
    elif rhythm == Rhythm.QUARTERLY:
        label = f"{index}. Quartal {fy}"
    else:
        label = f"{MONTHS[start.month - 1]} {start.year}"
    return Period(year, index, rhythm, start, end, months, label, first)


def periods(org, year: int, rhythm: str) -> list[Period]:
    return [period(org, year, rhythm, i) for i in range(1, PERIODS_PER_YEAR[rhythm] + 1)]


# --- Beitrag eines Mitglieds ---


def age_on(birth: datetime.date, on: datetime.date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


_MISSING = object()


def yearly_fee(
    org, member_type, birth_date, year: int, *, cache: dict | None = None
) -> tuple[Decimal, str]:
    """Jahresbeitrag und Bezeichnung der greifenden Altersstufe (oder "").

    ``cache``: für viele Mitglieder nacheinander (Beitragslauf) – Beitragssätze und
    Altersstufen werden dann nur einmal gelesen."""
    cache = {} if cache is None else cache
    rates = cache.setdefault("rates", {})
    rate = rates.get(member_type.pk, _MISSING)
    if rate is _MISSING:
        rate = rates[member_type.pk] = FeeRate.objects.filter(member_type=member_type).first()
    base = rate.amount if rate else None
    age = age_on(birth_date, org.fiscal_start(year))
    if "stages" not in cache:
        cache["stages"] = list(AgeRate.objects.filter(organization=org))
    stages = [
        s for s in cache["stages"] if s.member_type_id in (None, member_type.pk) and s.matches(age)
    ]
    # eine Stufe für genau diese Mitgliedsart geht vor
    stages.sort(key=lambda s: (s.member_type_id is None, s.min_age or 0))
    stage = stages[0] if stages else None
    if stage is None:
        return (base if base is not None else ZERO), ""
    if stage.amount is not None:
        return stage.amount, stage.name
    if base is None:
        return ZERO, stage.name
    factor = (Decimal(100) - stage.discount_percent) / Decimal(100)
    return (base * factor).quantize(CENT, ROUND_HALF_UP), stage.name


def _member_months(periods_, p: Period) -> int:
    """Angefangene Monate des Zeitraums, in denen die Mitgliedschaft bestand.

    Die Monatsgrenzen werden vom Beginn des Geschäftsjahres aus gezählt, nicht vom
    Beginn des Zeitraums: Beginnt das Jahr am 31.01., läuft der zweite Monat vom 28.02.
    bis 30.03. (nicht nur bis 27.03.).
    """
    first = p.first or p.start
    offset = p.months * (p.index - 1) if p.first else 0
    count = 0
    for k in range(p.months):
        m_start = add_months(first, offset + k)
        m_end = add_months(first, offset + k + 1) - datetime.timedelta(days=1)
        if any(
            p.entry_date <= m_end and (p.exit_date is None or p.exit_date >= m_start)
            for p in periods_
        ):
            count += 1
    return count


def rate_share(yearly: Decimal, p: Period) -> Decimal:
    """Anteil eines Jahresbetrags für einen Zeitraum, so dass alle Raten eines Jahres
    zusammen genau den Jahresbetrag ergeben (Fachfrage 1, Audit 31.10.): Restcents gehen
    auf die ersten Raten. 100,00 € monatlich: 4 × 8,34 + 8 × 8,33."""
    yearly = yearly.quantize(CENT, ROUND_HALF_UP)
    count = 12 // p.months if p.months and 12 % p.months == 0 else 0
    if count <= 1:
        return (yearly * p.months / Decimal(12)).quantize(CENT, ROUND_HALF_UP)
    sign = -1 if yearly < 0 else 1
    total = abs(yearly)
    base = (total / count).quantize(CENT, ROUND_DOWN)
    rest = int((total - base * count) / CENT)
    share = base + (CENT if p.index <= rest else Decimal(0))
    return share * sign


@dataclass
class FeeItem:
    membership: Membership
    amount: Decimal
    text: str
    detail: str
    department: object | None = None
    # Per Mail oder Post erreichbar (für die Prüfliste, ohne die Kontakte erneut zu lesen)
    reachable: bool = True


@dataclass
class RunPlan:
    member_items: list[FeeItem] = field(default_factory=list)
    department_items: dict[int, list[FeeItem]] = field(default_factory=dict)
    departments: dict[int, object] = field(default_factory=dict)
    skipped: list[dict] = field(default_factory=list)


def fee_exempt_units(org) -> dict[int, str]:
    """Untereinheiten ohne Vereinsbeitrag: Nummer -> Name der beitragsfreien Einheit.

    Der Schalter gilt auch für alle Einheiten darunter; genannt wird dann die Einheit,
    an der er steht."""
    from organizations.models import Department

    units = {
        u["pk"]: u
        for u in Department.objects.filter(organization=org).values(
            "pk", "parent_id", "fee_exempt", "name"
        )
    }
    result: dict[int, str] = {}
    for pk in units:
        seen = set()
        cur = units.get(pk)
        while cur is not None and cur["pk"] not in seen:
            seen.add(cur["pk"])
            if cur["fee_exempt"]:
                result[pk] = cur["name"]
                break
            cur = units.get(cur["parent_id"])
    return result


def plan_run(org, p: Period, exclude: set[int] | None = None) -> RunPlan:
    """Wer in diesem Zeitraum welchen Beitrag zahlt und über wen."""
    exclude = exclude or set()
    cfg = settings_for(org)
    plan = RunPlan()
    # Ein und derselbe Zeitraum der Mitgliedschaft muss den Abrechnungszeitraum berühren.
    # Erst nur die Nummern (sortiert), dann in Blöcken laden: große Vereine halten so nicht
    # alle Zeiträume, Arten und Zugehörigkeiten gleichzeitig im Speicher (PERF-01).
    ids = list(
        Membership.objects.filter(organization=org, purged_at__isnull=True)
        .filter(
            Q(periods__entry_date__lte=p.end)
            & (Q(periods__exit_date__isnull=True) | Q(periods__exit_date__gte=p.start))
        )
        .exclude(pk__in=exclude)
        .distinct()
        .order_by("person__last_name", "person__first_name", "pk")
        .values_list("pk", "person__last_name", "person__first_name")
    )
    ids = [row[0] for row in ids]
    fee_cache: dict = {}
    shared = shared_contacts()
    exempt_units = fee_exempt_units(org)
    # Ehrungen mit Beitragsanpassung einmal für alle lesen, je Person der Stichtag
    awards: dict[int, list] = {}
    for a in (
        HonoraryTitleAward.objects.filter(organization_id=org.pk)
        .exclude(title__fee_mode=HonoraryTitle.FeeMode.NONE)
        .select_related("title")
    ):
        awards.setdefault(a.person_id, []).append(a)
    for m in _in_blocks(ids):
        spans = [
            s
            for s in m.periods.all()
            if s.entry_date <= p.end and (s.exit_date is None or s.exit_date >= p.start)
        ]
        if not spans:
            continue
        ref = max(p.start, min(s.entry_date for s in spans))
        assignment = next(
            (
                a
                for a in m.type_assignments.all()
                if a.valid_from <= ref and (a.valid_until is None or a.valid_until >= ref)
            ),
            None,
        )
        if assignment is None:
            assignment = next(
                (
                    a
                    for a in m.type_assignments.all()
                    if a.valid_from <= p.end and (a.valid_until is None or a.valid_until >= ref)
                ),
                None,
            )
        name = f"{m.person.last_name}, {m.person.first_name}"
        # Mitglied einer beitragsfreien Untereinheit: kein Vereinsbeitrag
        exempt = next(
            (
                exempt_units[d.department_id]
                for d in m.department_memberships.all()
                if d.department_id in exempt_units
                and d.department.is_active
                and d.valid_from <= ref
                and (d.valid_until is None or d.valid_until >= ref)
            ),
            None,
        )
        if exempt is not None:
            plan.skipped.append(
                {"membership": m.pk, "name": name, "reason": f"beitragsfrei ({exempt})"}
            )
            continue
        if assignment is None:
            plan.skipped.append({"membership": m.pk, "name": name, "reason": "keine Mitgliedsart"})
            continue
        member_type = assignment.member_type
        yearly, stage = yearly_fee(org, member_type, m.person.birth_date, p.year, cache=fee_cache)
        details = [member_type.name]
        if stage:
            details.append(stage)
        reason = member_type.name
        # Ehrungen des Vereins mit Beitragsanpassung: der günstigste gilt
        titles = [
            a.title
            for a in awards.get(m.person_id, [])
            if a.valid_from <= ref and (a.valid_until is None or a.valid_until >= ref)
        ]
        honored = adjusted_fee(titles, yearly)
        if honored is not None:
            yearly, title_name = honored
            details = [member_type.name, title_name]
            reason = title_name
        amount = rate_share(yearly, p)
        if cfg.pro_rata:
            months = _member_months(spans, p)
            if months < p.months:
                amount = amount * months / p.months
                details.append(f"anteilig {months}/{p.months} Monate")
        amount = amount.quantize(CENT, ROUND_HALF_UP)
        if amount <= 0:
            plan.skipped.append(
                {"membership": m.pk, "name": name, "reason": f"beitragsfrei ({reason})"}
            )
            continue
        dept = None
        if not m.pays_fee_self:
            link = next(
                (
                    d
                    for d in m.department_memberships.all()
                    if d.valid_from <= ref
                    and d.department.is_active
                    and (d.valid_until is None or d.valid_until >= ref)
                ),
                None,
            )
            dept = link.department if link else None
        contact = contact_for(m.person, org, shared)
        reachable = bool(contact and contact.email) or bool(
            contact and contact.street and contact.postal_code and contact.city
        )
        item = FeeItem(m, amount, name, " · ".join(details), dept, reachable)
        if dept is None:
            item.text = f"Mitgliedsbeitrag {p.label}"
            plan.member_items.append(item)
        else:
            plan.departments[dept.pk] = dept
            plan.department_items.setdefault(dept.pk, []).append(item)
    return plan


PLAN_BLOCK = 500


def _in_blocks(ids: list[int]):
    """Mitgliedschaften in fester Reihenfolge, blockweise mit allem Nötigen geladen.

    Nach jedem Block werden Zeiträume, Arten und Zugehörigkeiten wieder freigegeben; nur
    Person und Kontaktdaten bleiben (für Empfänger und Prüfliste)."""
    for start in range(0, len(ids), PLAN_BLOCK):
        block = ids[start : start + PLAN_BLOCK]
        found = {
            m.pk: m
            for m in Membership.objects.filter(pk__in=block)
            .select_related("person")
            .prefetch_related(
                "periods",
                "type_assignments__member_type",
                "department_memberships__department",
                "person__contacts",
            )
        }
        for pk in block:
            m = found.get(pk)
            if m is None:
                continue
            yield m
            cache = getattr(m, "_prefetched_objects_cache", {})
            for key in ("periods", "type_assignments", "department_memberships"):
                cache.pop(key, None)


def preview_checks(org, plan: RunPlan) -> dict:
    """Zahlen für die Prüfliste vor dem Beitragslauf (blockieren nie)."""
    from portal.models import ChangeRequest

    from .sepa import mandate_usable

    memberships = [i.membership for i in plan.member_items]
    unreachable = sum(1 for i in plan.member_items if not i.reachable)
    with_mandate = 0
    if settings_for(org).sepa_enabled and memberships:
        usable = {
            mandate.membership_id
            for mandate in Mandate.objects.filter(
                organization=org,
                membership__in=memberships,
                status=Mandate.Status.ACTIVE,
            )
            if mandate_usable(mandate)
        }
        with_mandate = len(usable)
    return {
        "unreachable": unreachable,
        "with_mandate": with_mandate,
        "open_change_requests": ChangeRequest.objects.filter(
            organization=org, status=ChangeRequest.Status.PENDING
        ).count(),
    }


# --- Empfänger ---


def _address(contact) -> str:
    if contact is None:
        return ""
    lines = [contact.street, f"{contact.postal_code} {contact.city}".strip()]
    if contact.country and contact.country != "Deutschland":
        lines.append(contact.country)
    return "\n".join(line for line in lines if line)


def member_recipient(org, membership: Membership) -> dict:
    person = membership.person
    contact = contact_for(person, org)
    return {
        "recipient_name": f"{person.first_name} {person.last_name}",
        "recipient_address": _address(contact),
        "recipient_email": contact.email if contact else "",
    }


def department_treasurer(department) -> Membership | None:
    on = timezone.localdate()
    holders = (
        DepartmentRoleHolder.objects.filter(role__department=department, valid_from__lte=on)
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
        .select_related("role", "membership__person")
        .order_by("valid_from", "pk")
    )
    for h in holders:
        if DEPT_INVOICES_VIEW in (h.role.permissions or []):
            return h.membership
    return None


def department_recipient(org, department) -> dict:
    treasurer = department_treasurer(department)
    if treasurer is None:
        return {
            "recipient_name": f"{org.department_label} {department.name}",
            "recipient_address": "",
            "recipient_email": "",
        }
    person = treasurer.person
    contact = contact_for(person, org)
    return {
        "recipient_name": (
            f"{org.department_label} {department.name}\n"
            f"z. Hd. {person.first_name} {person.last_name}"
        ),
        "recipient_address": _address(contact),
        "recipient_email": contact.email if contact else "",
    }


def refresh_recipient(invoice: Invoice) -> None:
    org = invoice.organization
    if invoice.recipient_kind == Invoice.Recipient.MEMBER and org.type == "unit":
        from .units import member_recipient as unit_member_recipient

        # Arbeitsbereich einer Untereinheit: Mitgliedsdaten liegen darüber
        data = unit_member_recipient(org, invoice.membership_id)
    elif invoice.recipient_kind == Invoice.Recipient.MEMBER:
        data = member_recipient(org, invoice.membership)
    elif invoice.recipient_kind == Invoice.Recipient.CLUB:
        data = club_recipient(invoice.club)
    else:
        data = department_recipient(org, invoice.department)
    for key, value in data.items():
        setattr(invoice, key, value)


# --- Beitragslauf ---


def lock_run(run: FeeRun) -> None:
    """Beitragslauf bis zum Ende der Transaktion sperren: Neu berechnen und Festschreiben
    desselben Laufs laufen nacheinander, nie verschränkt (sonst doppelte Entwürfe)."""
    FeeRun.objects.select_for_update().filter(pk=run.pk).values_list("pk").first()


def edited_drafts(run: FeeRun) -> int:
    """Entwürfe des Laufs, die nach dem Anlegen von Hand geändert wurden."""
    from django.db.models import F

    return Invoice.objects.filter(
        run=run,
        status=Invoice.Status.DRAFT,
        updated_at__gt=F("created_at") + datetime.timedelta(seconds=2),
    ).count()


def build_run(run: FeeRun, user) -> dict:
    """Entwürfe für alle noch nicht festgeschriebenen Beiträge dieses Laufs anlegen."""
    lock_run(run)
    org = run.organization
    if org.type == "federation":
        return build_federation_run(run, user)
    Invoice.objects.filter(run=run, status=Invoice.Status.DRAFT).delete()
    # Stornierte Rechnungen zählen nicht: Storno und Neu berechnen ist der Korrekturweg
    # (wie beim Dachverband); der neue Entwurf wird vor dem Festschreiben geprüft
    done = Invoice.objects.exclude(status__in=[Invoice.Status.DRAFT, Invoice.Status.CANCELLED])
    covered = set(
        InvoiceLine.objects.filter(
            invoice__in=done.filter(run=run), is_fee=True, membership__isnull=False
        ).values_list("membership_id", flat=True)
    )
    # Festgeschriebene Einzelrechnungen des Laufs zählen auch dann, wenn ihre Posten
    # von Hand geändert wurden
    covered |= set(
        done.filter(run=run, membership__isnull=False).values_list("membership_id", flat=True)
    )
    p = period(org, run.year, run.rhythm, run.period)
    plan = plan_run(org, p, exclude=covered)
    created = 0
    common = {
        "organization": org,
        "run": run,
        "date": run.invoice_date,
        "due_date": run.due_date,
        "created_by": user,
    }
    for item in plan.member_items:
        invoice = Invoice(
            recipient_kind=Invoice.Recipient.MEMBER,
            membership=item.membership,
            subject=f"Mitgliedsbeitrag {p.label}",
            total=item.amount,
            **common,
            **member_recipient(org, item.membership),
        )
        invoice.save()
        InvoiceLine.objects.create(
            organization=org,
            invoice=invoice,
            text=item.text,
            detail=item.detail,
            amount=item.amount,
            membership=item.membership,
            is_fee=True,
        )
        created += 1
    for dept_id, items in plan.department_items.items():
        dept = plan.departments[dept_id]
        invoice = Invoice(
            recipient_kind=Invoice.Recipient.DEPARTMENT,
            department=dept,
            subject=f"Mitgliedsbeiträge {p.label} – {dept.name}",
            total=sum((i.amount for i in items), ZERO),
            **common,
            **department_recipient(org, dept),
        )
        invoice.save()
        InvoiceLine.objects.bulk_create(
            InvoiceLine(
                organization=org,
                invoice=invoice,
                position=n,
                text=i.text,
                detail=i.detail,
                amount=i.amount,
                membership=i.membership,
                is_fee=True,
            )
            for n, i in enumerate(items)
        )
        created += 1
    return {"created": created, "skipped": plan.skipped}


def run_summary(run: FeeRun) -> dict:
    invoices = Invoice.objects.filter(run=run)
    by_status = {
        s: invoices.filter(status=s).aggregate(n=Sum("total"))["n"] or ZERO
        for s in Invoice.Status.values
    }
    counts = {s: invoices.filter(status=s).count() for s in Invoice.Status.values}
    return {
        "counts": counts,
        "totals": by_status,
        "members": InvoiceLine.objects.filter(invoice__run=run, is_fee=True)
        .exclude(invoice__status=Invoice.Status.CANCELLED)
        .count(),
        "departments": invoices.filter(recipient_kind=Invoice.Recipient.DEPARTMENT)
        .exclude(status=Invoice.Status.CANCELLED)
        .count(),
        "paid": invoices.aggregate(n=Sum("paid"))["n"] or ZERO,
        "unsent_with_email": invoices.filter(status=Invoice.Status.OPEN, sent_at__isnull=True)
        .exclude(recipient_email="")
        .count(),
        "without_email": invoices.exclude(status=Invoice.Status.CANCELLED)
        .filter(recipient_email="")
        .count(),
    }


# --- Rechnungsnummern und Festschreiben ---


def next_invoice_number(org_id: int, year: int) -> int:
    with connection.cursor() as cursor:
        # eigener Sperrschlüssel, getrennt von den Buchungsnummern
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [org_id, 100000 + year])
    last = (
        Invoice.objects.filter(organization_id=org_id, year=year, number__isnull=False)
        .order_by("-number")
        .values_list("number", flat=True)
        .first()
    )
    return (last or 0) + 1


def recalc_total(invoice: Invoice) -> None:
    invoice.total = invoice.lines.aggregate(s=Sum("amount"))["s"] or ZERO


def lock_invoice(
    invoice: Invoice, fields: tuple | None = ("status", "paid", "total", "dunning_level")
) -> None:
    """Rechnung bis zum Ende der Transaktion sperren und den aktuellen Stand nachladen.

    Alle Übergänge (Festschreiben, Zahlung, Storno, Mahnung, Lastschrift) sperren die
    Rechnung zuerst; so prüft jeder den Stand, den der vorige hinterlassen hat.
    ``fields=None`` lädt alle Felder neu.
    """
    Invoice._base_manager.select_for_update().filter(pk=invoice.pk).values_list("pk").first()
    invoice.refresh_from_db(fields=list(fields) if fields is not None else None)


@transaction.atomic
def finalize(invoice: Invoice) -> None:
    lock_invoice(invoice, ("status",))
    if invoice.status != Invoice.Status.DRAFT:
        raise ValidationError(gettext("Die Rechnung ist schon festgeschrieben."))
    recalc_total(invoice)
    if invoice.total <= 0:
        raise ValidationError(gettext("Der Rechnungsbetrag muss größer als 0 sein."))
    refresh_recipient(invoice)
    org = invoice.organization
    invoice.year = org.fiscal_year_of(invoice.date)
    invoice.number = next_invoice_number(org.pk, invoice.year)
    invoice.status = Invoice.Status.OPEN
    invoice.save()
    if invoice.club_id is not None and invoice.club.is_remote:
        from peering import packet_invoices

        packet_invoices.on_finalize(invoice)


IN_DEBIT_RUN = (
    "Die Rechnung steckt in einem noch nicht gebuchten Lastschriftlauf. "
    "Bitte den Lauf zuerst buchen oder verwerfen."
)


def in_open_debit_run(invoice: Invoice) -> bool:
    from .models import DebitItem, DebitRun

    return DebitItem.objects.filter(invoice=invoice, run__status=DebitRun.Status.CREATED).exists()


@transaction.atomic
def cancel(invoice: Invoice) -> None:
    lock_invoice(invoice)
    if invoice.status != Invoice.Status.OPEN:
        raise ValidationError(gettext("Nur offene Rechnungen lassen sich stornieren."))
    if in_open_debit_run(invoice):
        raise ValidationError(IN_DEBIT_RUN)
    if invoice.payments.exists():
        raise ValidationError(
            gettext("Zu der Rechnung gibt es Zahlungen. Bitte zuerst die Zahlungen entfernen.")
        )
    invoice.status = Invoice.Status.CANCELLED
    invoice.cancelled_at = timezone.now()
    invoice.save(update_fields=["status", "cancelled_at", "updated_at"])
    if invoice.club_id is not None and invoice.club.is_remote:
        from peering import packet_invoices

        packet_invoices.on_cancel(invoice)


# --- Zahlungen ---


def _update_paid(invoice: Invoice) -> None:
    invoice.paid = invoice.payments.aggregate(s=Sum("amount"))["s"] or ZERO
    invoice.status = Invoice.Status.PAID if invoice.paid >= invoice.total else Invoice.Status.OPEN
    invoice.save(update_fields=["paid", "status", "updated_at"])
    if invoice.club_id is not None and invoice.club.is_remote:
        from peering import packet_invoices

        packet_invoices.on_paid_changed(invoice)


@transaction.atomic
def add_payment(
    invoice: Invoice, *, date, amount: Decimal, method: str, account, user, debit: bool = False
) -> Payment:
    """Zahlung mit Kassenbuchung. ``debit``: Buchung eines Lastschriftlaufs."""
    lock_invoice(invoice)
    org = invoice.organization
    if invoice.status not in (Invoice.Status.OPEN, Invoice.Status.PAID):
        raise ValidationError(gettext("Zahlungen gibt es nur zu festgeschriebenen Rechnungen."))
    # Der Betrag des Laufs steht schon in der Bankdatei; eine Zahlung dazwischen
    # würde Bank und Kasse auseinanderlaufen lassen.
    if not debit and in_open_debit_run(invoice):
        raise ValidationError(IN_DEBIT_RUN)
    if amount <= 0:
        raise ValidationError({"amount": gettext("Der Betrag muss größer als 0 sein.")})
    if amount > invoice.outstanding:
        raise ValidationError(
            {"amount": f"Offen sind nur noch {invoice.outstanding:.2f} €.".replace(".", ",")}
        )
    cfg = settings_for(org)
    if cfg.category is None:
        raise ValidationError(
            gettext(
                "Bitte unter Beiträge → Einstellungen eine Kategorie für Beitragszahlungen wählen."
            )
        )
    if account is None or account.organization_id != org.pk:
        raise ValidationError({"account": gettext("Bitte das Konto wählen.")})
    finance_services.ensure_open(org, date=date)
    year = org.fiscal_year_of(date)
    booking = Booking(
        organization=org,
        year=year,
        number=finance_services.next_number(org.pk, year),
        date=date,
        kind=Booking.Kind.INCOME,
        amount=amount,
        account=account,
        category=cfg.category,
        text=f"Zahlung {invoice.display_number} {invoice.recipient_name.splitlines()[0]}"[:200],
        reference=invoice.display_number,
        counterparty=invoice.recipient_name.splitlines()[0][:200] if invoice.recipient_name else "",
        # Arbeitsbereich einer Untereinheit: Mitglieder liegen im Datenbereich darüber
        membership=None if org.type == "unit" else invoice.membership,
        department=invoice.department,
        project=invoice.project,
        created_by=user,
    )
    booking.full_clean(exclude=["organization", "created_by"])
    booking.save()
    payment = Payment.objects.create(
        organization=org,
        invoice=invoice,
        date=date,
        amount=amount,
        method=method,
        booking=booking,
        created_by=user,
    )
    _update_paid(invoice)
    return payment


@transaction.atomic
def remove_payment(payment: Payment, user=None) -> Booking | None:
    """Zahlung entfernen. Am Tag der Erfassung wird die Buchung gelöscht, danach storniert
    (GoBD: Gegenbuchung, die Buchung bleibt). Gibt die Stornobuchung zurück, sonst None."""
    invoice = payment.invoice
    lock_invoice(invoice)
    booking = payment.booking
    finance_services.ensure_open(invoice.organization, year=booking.year)
    payment.delete()
    booking.refresh_from_db()
    counter = None
    if finance_services.deletable(booking):
        account, since = booking.account, booking.date
        if booking.receipts.exists():
            raise ValidationError(
                gettext("An der Buchung hängen Belege. Bitte diese zuerst in der Kasse entfernen.")
            )
        booking.delete()
        finance_services.ensure_cash_ok([account], since)
    else:
        counter = finance_services.cancel_booking(
            booking,
            user,
            f"Zahlung zu Rechnung {invoice.display_number} entfernt",
            check_links=False,
        )
    _update_paid(invoice)
    return counter


# --- Dachverband an Verein ---


@dataclass
class ClubItem:
    club: object
    lines: list[tuple[str, str, Decimal]]
    total: Decimal
    members: int


def club_recipient(club) -> dict:
    from organizations.serializers import effective_contact

    lines = [club.street, f"{club.postal_code} {club.city}".strip()]
    return {
        "recipient_name": club.name,
        "recipient_address": "\n".join(line for line in lines if line),
        "recipient_email": effective_contact(club).get("email") or "",
    }


def reported_counts(
    federation, club, on: datetime.date
) -> dict[tuple[str, int, tuple[int, ...]], int]:
    """Gemeldete Mitglieder eines Vereins am Stichtag nach (aktiv/passiv, Altersstufe
    (ID, 0 = keine), Ehrungen des Dachverbands mit Beitragsanpassung).

    Die Altersstufe zählt über ihre ID: Zwei Stufen dürfen gleich heißen."""
    from core.tenancy import tenant_context
    from members.honorary import current_awards
    from members.models import HonoraryTitle

    stages = list(AgeRate.objects.filter(organization=federation, member_type__isnull=True))
    if club.is_remote:
        # Verein auf einer anderen Instanz: Zahlen aus seiner Meldung (Verbund, Stufe A)
        from peering.packet_members import counts_for

        remote = counts_for(federation, club, on, stages)
        if remote is not None:
            return remote
    # Ehrungen des Dachverbands (eigene Zeilen, vor dem Wechsel in den Verein lesen)
    titles: dict[int, set[int]] = {}
    for person_id, title_id in (
        current_awards(on)
        .filter(organization=federation)
        .exclude(title__fee_mode=HonoraryTitle.FeeMode.NONE)
        .values_list("person_id", "title_id")
    ):
        titles.setdefault(person_id, set()).add(title_id)
    counts: dict[tuple[str, int, tuple[int, ...]], int] = {}
    with tenant_context(club.pk):
        memberships = (
            Membership.objects.filter(organization=club, purged_at__isnull=True)
            .filter(
                Q(periods__entry_date__lte=on)
                & (Q(periods__exit_date__isnull=True) | Q(periods__exit_date__gte=on))
            )
            .distinct()
            .select_related("person")
        )
        for m in memberships:
            assignment = m.current_type(on)
            if assignment is None or not assignment.member_type.reported:
                continue
            kind = "active" if assignment.member_type.active else "passive"
            age = age_on(
                m.person.birth_date, federation.fiscal_start(federation.fiscal_year_of(on))
            )
            stage = next(
                (
                    st.pk
                    for st in sorted(stages, key=lambda x: (x.min_age or 0, x.pk))
                    if st.matches(age)
                ),
                0,
            )
            key = (kind, stage, tuple(sorted(titles.get(m.person_id, ()))))
            counts[key] = counts.get(key, 0) + 1
    return counts


def plan_federation_run(federation, p: Period, exclude: set[int] | None = None) -> list[ClubItem]:
    from members.models import HonoraryTitle
    from organizations.models import Organization

    exclude = exclude or set()
    cfg = settings_for(federation)
    stages = {
        st.pk: st
        for st in AgeRate.objects.filter(organization=federation, member_type__isnull=True)
    }
    honorary = {t.pk: t for t in HonoraryTitle.objects.filter(organization=federation)}
    labels = {"active": "aktive Mitglieder", "passive": "passive Mitglieder"}
    base_rates = {"active": cfg.club_rate_active, "passive": cfg.club_rate_passive}
    items = []
    clubs = Organization.objects.filter(
        parent=federation, type=Organization.Type.CLUB, is_active=True
    ).order_by("name")
    for club in clubs:
        if club.pk in exclude:
            continue
        lines: list[tuple[str, str, Decimal]] = []
        counts = reported_counts(federation, club, p.start)
        # Gleiche Posten (z. B. nach Ehrung) zusammenfassen
        merged: dict[tuple[str, Decimal], int] = {}

        def order(entry, stages=stages):
            (kind, stage_id, title_ids), _ = entry
            name = stages[stage_id].name if stage_id in stages else ""
            return (kind, name, stage_id, title_ids)

        for (kind, stage_id, title_ids), n in sorted(counts.items(), key=order):
            base = base_rates[kind]
            stage = stages.get(stage_id)
            stage_name = stage.name if stage is not None else ""
            if stage is not None and stage.amount is not None:
                rate = stage.amount
            elif base is None:
                rate = None
            elif stage is not None:
                rate = base * (Decimal(100) - stage.discount_percent) / Decimal(100)
            else:
                rate = base
            text = labels[kind] + (f", {stage_name}" if stage_name else "")
            honored = adjusted_fee([honorary[t] for t in title_ids if t in honorary], rate or ZERO)
            if honored is not None:
                rate, title_name = honored
                text = f"{text}, {title_name}"
            if rate is None:
                continue
            rate = rate_share(rate, p)
            if rate <= 0:
                continue
            merged[(text, rate)] = merged.get((text, rate), 0) + n
        for (text, rate), n in merged.items():
            lines.append((text, f"{n} × {rate:.2f} €".replace(".", ","), rate * n))
        if cfg.club_base_amount:
            base_amount = rate_share(cfg.club_base_amount, p)
            lines.append((fill("Grundbetrag je {sg}", federation), "", base_amount))
        total = sum((amount for *_, amount in lines), ZERO)
        if total > 0:
            items.append(ClubItem(club, lines, total, sum(counts.values())))
    return items


def build_federation_run(run: FeeRun, user) -> dict:
    org = run.organization
    Invoice.objects.filter(run=run, status=Invoice.Status.DRAFT).delete()
    covered = set(
        Invoice.objects.filter(run=run, club__isnull=False)
        .exclude(status=Invoice.Status.DRAFT)
        .exclude(status=Invoice.Status.CANCELLED)
        .values_list("club_id", flat=True)
    )
    p = period(org, run.year, run.rhythm, run.period)
    created = 0
    for item in plan_federation_run(org, p, exclude=covered):
        invoice = Invoice.objects.create(
            organization=org,
            run=run,
            recipient_kind=Invoice.Recipient.CLUB,
            club=item.club,
            subject=f"Verbandsbeitrag {p.label}",
            date=run.invoice_date,
            due_date=run.due_date,
            total=item.total,
            created_by=user,
            **club_recipient(item.club),
        )
        InvoiceLine.objects.bulk_create(
            InvoiceLine(
                organization=org,
                invoice=invoice,
                position=n,
                text=text,
                detail=detail,
                amount=amount,
                is_fee=True,
            )
            for n, (text, detail, amount) in enumerate(item.lines)
        )
        created += 1
    return {"created": created, "skipped": []}


# --- Umsatzsteuer ---


def included_vat(gross: Decimal, rate: Decimal) -> Decimal:
    """Enthaltene Umsatzsteuer eines Bruttobetrags, kaufmännisch auf Cent gerundet.

    Gemeinsam für Rechnungen und Quittungen (Audit 31.10. FIN31-06: vorher rundete die
    Quittung einen halben Cent ab, die Rechnung auf)."""
    return (gross * rate / (Decimal(100) + rate)).quantize(CENT, ROUND_HALF_UP)


def vat_breakdown(invoice: Invoice) -> list[dict]:
    """Enthaltene Umsatzsteuer je Steuersatz (Beträge sind brutto)."""
    by_rate: dict[Decimal, Decimal] = {}
    for line in invoice.lines.all():
        if line.vat_rate:
            by_rate[line.vat_rate] = by_rate.get(line.vat_rate, ZERO) + line.amount
    result = []
    for rate, gross in sorted(by_rate.items()):
        vat = included_vat(gross, rate)
        result.append({"rate": rate, "gross": gross, "net": gross - vat, "vat": vat})
    return result


# --- Mahnungen ---


def next_level(invoice: Invoice, levels: list[DunningLevel]) -> DunningLevel | None:
    return next((lv for lv in levels if lv.level > invoice.dunning_level), None)


def dunning_proposals(org, on: datetime.date | None = None) -> list[tuple[Invoice, DunningLevel]]:
    """Offene Rechnungen, für die die nächste Mahnstufe fällig ist."""
    on = on or timezone.localdate()
    levels = list(DunningLevel.objects.filter(organization=org).order_by("level"))
    if not levels:
        return []
    result = []
    invoices = (
        Invoice.objects.filter(organization=org, status=Invoice.Status.OPEN, due_date__lt=on)
        # Rechnungen in einem laufenden Lastschrifteinzug werden nicht gemahnt
        .exclude(debits__run__status="created")
        .select_related("organization", "department", "club", "membership__person")
        .order_by("due_date", "number")
    )
    for invoice in invoices:
        level = next_level(invoice, levels)
        if level is None or invoice.outstanding <= 0:
            continue
        if invoice.due_date + datetime.timedelta(days=level.days) <= on:
            result.append((invoice, level))
    return result


@transaction.atomic
def dun(invoice: Invoice, level: DunningLevel, user, on: datetime.date | None = None) -> Dunning:
    lock_invoice(invoice)
    on = on or timezone.localdate()
    if invoice.status != Invoice.Status.OPEN:
        raise ValidationError(gettext("Gemahnt werden nur offene Rechnungen."))
    # Der Einzug läuft schon; eine Mahnung (womöglich mit Gebühr) wäre irreführend
    if in_open_debit_run(invoice):
        raise ValidationError(IN_DEBIT_RUN)
    if level.level <= invoice.dunning_level:
        raise ValidationError(gettext("Diese Mahnstufe ist schon erreicht."))
    cfg = settings_for(invoice.organization)
    dunning = Dunning.objects.create(
        organization=invoice.organization,
        invoice=invoice,
        level=level.level,
        name=level.name,
        text=level.text,
        date=on,
        due_date=on + datetime.timedelta(days=max(cfg.due_days, 7)),
        fee=level.fee,
        created_by=user,
    )
    if level.fee > 0:
        position = (
            invoice.lines.order_by("-position").values_list("position", flat=True).first() or 0
        ) + 1
        InvoiceLine.objects.create(
            organization=invoice.organization,
            invoice=invoice,
            position=position,
            text=f"Mahngebühr ({level.name})",
            detail=f"{on:%d.%m.%Y}",
            amount=level.fee,
            is_dunning_fee=True,
        )
        recalc_total(invoice)
    invoice.dunning_level = level.level
    invoice.dunned_at = on
    invoice.save(update_fields=["total", "dunning_level", "dunned_at", "updated_at"])
    return dunning
