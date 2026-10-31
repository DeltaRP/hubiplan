"""Regeln der Webseite: Einwilligungen, Vorschau, Modul-Schalter."""

from __future__ import annotations

import datetime

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import PreviewLink, PublicationConsent, Website, hash_token

MODULE = "website"
Category = PublicationConsent.Category

# Vorschau: kurzer Schlüssel aus HUBIplan (Knopf „Vorschau öffnen“), den die
# Webseite gegen einen Sitzungsschlüssel für einige Stunden eintauscht.
_SALT_OPEN = "website.preview.open"
_SALT_SESSION = "website.preview.session"
OPEN_MAX_AGE = 5 * 60
SESSION_MAX_AGE = 8 * 60 * 60


def module_enabled(org) -> bool:
    return bool(org) and MODULE in (org.enabled_modules or [])


def is_unit_site(org) -> bool:
    """Webseite einer Untereinheit (mit eigenem Arbeitsbereich), z. B. eines Zugs?"""
    return getattr(org, "type", None) == "unit" and bool(getattr(org, "organization_id", None))


def data_area(org):
    """Einheit, in deren Datenbereich Mitglieder, Termine und Untereinheiten liegen."""
    return org.organization if is_unit_site(org) else org


def units_below(org):
    """Untereinheiten, die die Webseite von ``org`` zeigen kann (bei einer Untereinheit:
    die darunter)."""
    from organizations.models import Department
    from organizations.tree import subtree_ids

    if is_unit_site(org):
        return Department.objects.filter(
            organization_id=org.organization_id, pk__in=subtree_ids(org)[1:]
        )
    return Department.objects.filter(organization=org)


def in_tree_order(units) -> list:
    """Untereinheiten in der Reihenfolge des Baums: jede vor ihren Untereinheiten,
    Geschwister so, wie sie in HUBIplan gezogen wurden."""
    from organizations.tree import UnitTree

    units = list(units)
    if not units:
        return units
    order = {pk: i for i, pk in enumerate(UnitTree.of(units[0].organization_id).ordered())}
    return sorted(units, key=lambda u: (order.get(u.pk, len(order)), u.name))


def website_of(org) -> Website | None:
    return Website.objects.filter(organization=org).first()


def preview_only() -> bool:
    """Testserver: alle Webseiten nur in der Vorschau (Umgebungsvariable)."""
    return bool(getattr(settings, "WEBSITE_PREVIEW_ONLY", False))


def effective_state(website: Website) -> str:
    if not module_enabled(website.organization):
        return Website.State.OFF
    if website.state == Website.State.PUBLIC and preview_only():
        return Website.State.MAINTENANCE
    return website.state


# --- Vorschau ---


def open_token(website: Website) -> str:
    return signing.dumps({"w": website.public_key}, salt=_SALT_OPEN, compress=True)


def session_token(website: Website, until: datetime.datetime, link_id: int | None = None) -> str:
    data = {"w": website.public_key, "u": int(until.timestamp())}
    if link_id is not None:
        # Sitzung aus einem weitergegebenen Link: endet, sobald der Link widerrufen ist
        data["l"] = link_id
    return signing.dumps(data, salt=_SALT_SESSION, compress=True)


def exchange(website: Website, token: str) -> tuple[str, datetime.datetime] | None:
    """Vorschau-Schlüssel (Knopf oder Link) → Sitzungsschlüssel mit Ablaufzeit."""
    now = timezone.now()
    until = None
    link_id = None
    try:
        data = signing.loads(token, salt=_SALT_OPEN, max_age=OPEN_MAX_AGE)
        # Der kurze Schlüssel aus dem Knopf gilt nur einmal: Ein Wert aus einem Zugriffslog
        # hilft danach nicht mehr (Gesamtaudit 30.10., I-S01)
        if data.get("w") == website.public_key and cache.add(
            f"website-open:{hash_token(token)}", 1, OPEN_MAX_AGE + 60
        ):
            until = now + datetime.timedelta(seconds=SESSION_MAX_AGE)
    except signing.BadSignature:
        link = PreviewLink.objects.filter(website=website, token_hash=hash_token(token)).first()
        if link is not None and link.is_active:
            until = min(link.expires_at, now + datetime.timedelta(seconds=SESSION_MAX_AGE))
            link_id = link.pk
    if until is None:
        return None
    return session_token(website, until, link_id), until


def valid_session(website: Website, token: str | None) -> bool:
    if not token:
        return False
    try:
        data = signing.loads(token, salt=_SALT_SESSION, max_age=SESSION_MAX_AGE)
    except signing.BadSignature:
        return False
    if data.get("w") != website.public_key or data.get("u", 0) <= timezone.now().timestamp():
        return False
    if "l" in data:
        return PreviewLink.objects.filter(
            pk=data["l"], website=website, revoked_at__isnull=True, expires_at__gt=timezone.now()
        ).exists()
    return True


# --- Einwilligungen ---


def active_entries(membership_ids) -> dict[int, set[str]]:
    """Aktive Einträge je Mitgliedschaft (Kategorien)."""
    result: dict[int, set[str]] = {}
    rows = PublicationConsent.objects.filter(
        membership_id__in=list(membership_ids), ended_at__isnull=True
    ).values_list("membership_id", "category")
    for membership_id, category in rows:
        result.setdefault(membership_id, set()).add(category)
    return result


def allowed(category: str, active: set[str]) -> bool:
    """Darf die Angabe veröffentlicht werden? ``active`` = aktive Einträge der Person."""
    if category in PublicationConsent.OBJECTION_CATEGORIES:
        return category not in active
    return category in active


def status(membership) -> list[dict]:
    """Stand je Kategorie für die Mitgliederakte und den Mitgliederbereich."""
    entries = list(PublicationConsent.objects.filter(membership=membership))
    active = {e.category: e for e in entries if e.ended_at is None}
    result = []
    for value, label in Category.choices:
        entry = active.get(value)
        objection = value in PublicationConsent.OBJECTION_CATEGORIES
        result.append(
            {
                "category": value,
                "label": label,
                "kind": "objection" if objection else "consent",
                "active": entry is not None,
                "published": allowed(value, set(active)),
                "since": entry.since if entry else None,
                "source": entry.source if entry else "",
                "history": [
                    {
                        "since": e.since,
                        "source": e.get_source_display(),
                        "ended_at": e.ended_at,
                        "ended_source": e.get_ended_source_display() if e.ended_source else "",
                    }
                    for e in entries
                    if e.category == value
                ],
            }
        )
    return result


@transaction.atomic
def set_entry(membership, category: str, active: bool, source: str, user, on=None):
    """Einwilligung/Widerspruch setzen oder beenden. Gibt (vorher, nachher) zurück."""
    on = on or timezone.localdate()
    current = (
        PublicationConsent.objects.select_for_update()
        .filter(membership=membership, category=category, ended_at__isnull=True)
        .first()
    )
    if active and current is None:
        PublicationConsent.objects.create(
            organization=membership.organization,
            membership=membership,
            category=category,
            since=on,
            source=source,
            recorded_by=user,
        )
        return False, True
    if not active and current is not None:
        current.ended_at = on
        current.ended_source = source
        current.save(update_fields=["ended_at", "ended_source"])
        return True, False
    return active, active
