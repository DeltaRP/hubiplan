"""Veranstaltungen: Summen, Auswertung je Veranstaltung und Vergleich einer Reihe.

Gezählt werden nur Einnahmen und Ausgaben, die der Veranstaltung zugeordnet
sind. Umbuchungen gehören nie zu einer Veranstaltung.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Q, Sum

from .models import Booking, Project, ProjectSeries, TaxArea
from .services import _money

ZERO = Decimal("0.00")


def totals(project_ids) -> dict[int, dict]:
    """Einnahmen, Ausgaben, Ergebnis und Zahl der Buchungen je Veranstaltung."""
    result: dict[int, dict] = {
        pk: {"income": ZERO, "expense": ZERO, "result": ZERO, "booking_count": 0}
        for pk in project_ids
    }
    rows = (
        Booking.objects.filter(project_id__in=list(result))
        .exclude(kind=Booking.Kind.TRANSFER)
        .values("project_id")
        .annotate(
            income=Sum("amount", filter=Q(kind=Booking.Kind.INCOME)),
            expense=Sum("amount", filter=Q(kind=Booking.Kind.EXPENSE)),
            n=Count("id"),
        )
    )
    for row in rows:
        entry = result[row["project_id"]]
        entry["income"] = row["income"] or ZERO
        entry["expense"] = row["expense"] or ZERO
        entry["result"] = entry["income"] - entry["expense"]
        entry["booking_count"] = row["n"]
    return result


def _bookings(project: Project):
    return (
        Booking.objects.filter(organization_id=project.organization_id, project=project)
        .exclude(kind=Booking.Kind.TRANSFER)
        .select_related("organization", "account", "category", "membership__person")
        .prefetch_related("receipts")
        .order_by("date", "year", "number")
    )


def _categories(bookings) -> list[dict]:
    per: dict = {}
    for b in bookings:
        key = (b.category_id or 0, b.category_label, b.tax_area_value)
        entry = per.setdefault(
            key,
            {
                "id": b.category_id,
                "name": b.category_label or "ohne Kategorie",
                "tax_area": b.tax_area_value,
                "income": ZERO,
                "expense": ZERO,
            },
        )
        entry["income" if b.kind == Booking.Kind.INCOME else "expense"] += b.amount
    rows = sorted(per.values(), key=lambda c: c["name"].lower())
    for c in rows:
        c["result"] = c["income"] - c["expense"]
    return rows


def _evaluation(project: Project) -> dict:
    org = project.organization
    bookings = list(_bookings(project))
    categories = _categories(bookings)
    income = sum((c["income"] for c in categories), ZERO)
    expense = sum((c["expense"] for c in categories), ZERO)

    areas = []
    if org.tax_areas_enabled:
        sums: dict[str, dict] = defaultdict(lambda: {"income": ZERO, "expense": ZERO})
        for c in categories:
            sums[c["tax_area"]]["income"] += c["income"]
            sums[c["tax_area"]]["expense"] += c["expense"]
        labels = dict(TaxArea.choices)
        for key in [*TaxArea.values, ""]:
            if key in sums:
                areas.append(
                    {
                        "area": key,
                        "label": labels.get(key, "ohne Zuordnung"),
                        **sums[key],
                        "result": sums[key]["income"] - sums[key]["expense"],
                    }
                )

    open_invoices = {"count": 0, "outstanding": ZERO}
    for inv in _open_invoices(project):
        open_invoices["count"] += 1
        open_invoices["outstanding"] += inv.outstanding

    return {
        "id": project.pk,
        "name": project.name,
        "starts_on": project.starts_on,
        "ends_on": project.ends_on,
        "status": project.status,
        "status_label": project.get_status_display(),
        "description": project.description,
        "department_name": project.department.display_name if project.department_id else None,
        "series": project.series_id,
        "series_name": project.series.name if project.series_id else None,
        "tax_areas_enabled": org.tax_areas_enabled,
        "categories": categories,
        "tax_areas": areas,
        "totals": {"income": income, "expense": expense, "result": income - expense},
        "booking_count": len(bookings),
        "bookings": [
            {
                "id": b.pk,
                "display_number": b.display_number,
                "date": b.date,
                "kind": b.kind,
                "kind_label": b.get_kind_display(),
                "amount": b.amount,
                "text": b.text,
                "reference": b.reference,
                "category_name": b.category_label,
                "account_name": b.account.name,
                "receipt_count": len(b.receipts.all()),
            }
            for b in bookings
        ],
        "events": [
            {
                "id": e.pk,
                "title": e.title,
                "starts_at": e.starts_at,
                "ends_at": e.ends_at,
                "all_day": e.all_day,
                "is_series": e.is_series,
                "is_cancelled": e.is_cancelled,
            }
            for e in project.events.order_by("starts_at", "pk")
        ],
        "open_invoices": open_invoices,
    }


def _open_invoices(project: Project):
    from django.apps import apps

    if not apps.is_installed("billing"):
        return []
    from billing.models import Invoice

    return list(Invoice.objects.filter(project=project, status=Invoice.Status.OPEN))


def evaluation(project: Project) -> dict:
    return _money(_evaluation(project))


def _comparison(series: ProjectSeries) -> dict:
    """Veranstaltungen einer Reihe nebeneinander, mit Summen je Kategorie."""
    projects = list(series.projects.order_by("starts_on", "pk"))
    sums = totals([p.pk for p in projects])
    names: dict = {}
    matrix: dict = defaultdict(dict)  # Kategorie -> Veranstaltung -> Saldo
    rows = (
        Booking.objects.filter(project__in=projects)
        .exclude(kind=Booking.Kind.TRANSFER)
        .values("project_id", "category_id", "category__name", "kind")
        .annotate(total=Sum("amount"))
    )
    for row in rows:
        key = row["category_id"] or 0
        names[key] = row["category__name"] or "ohne Kategorie"
        cell = matrix[key].setdefault(row["project_id"], {"income": ZERO, "expense": ZERO})
        cell["income" if row["kind"] == Booking.Kind.INCOME else "expense"] += row["total"]
    categories = []
    for key in sorted(names, key=lambda k: names[k].lower()):
        values = []
        for p in projects:
            cell = matrix[key].get(p.pk, {"income": ZERO, "expense": ZERO})
            values.append({**cell, "result": cell["income"] - cell["expense"]})
        categories.append({"id": key or None, "name": names[key], "values": values})
    return {
        "id": series.pk,
        "name": series.name,
        "projects": [
            {
                "id": p.pk,
                "name": p.name,
                "starts_on": p.starts_on,
                "status": p.status,
                "status_label": p.get_status_display(),
                **sums[p.pk],
            }
            for p in projects
        ],
        "categories": categories,
    }


def comparison(series: ProjectSeries) -> dict:
    return _money(_comparison(series))
