"""Wer sieht welche Termine, und wer darf sie bearbeiten?

Jede Sicht (Vorstand einer Organisation, Abteilungsrolle, Mitgliederbereich,
öffentlicher Link) beschreibt sich als ``Viewer``. Die Datenbank (RLS) lässt
zusätzlich nur Termine der eigenen Organisation und die nicht internen Termine
des eigenen Dachverbands heraus.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from django.db.models import Q
from django.utils import timezone

from access.catalog import DEPT_EVENTS_MANAGE, EVENTS_MANAGE, FINANCE_EDIT, FINANCE_VIEW
from access.models import RoleAssignment
from organizations.models import Department, Organization
from organizations.tree import UnitTree, with_ancestors

from .models import CalendarPublication, Event, EventCategory

MODULE = "events"
SHARED = (Event.Visibility.PUBLIC, Event.Visibility.MEMBERS)

DEFAULT_CATEGORIES = (
    ("Versammlung", "#2f5f8f"),
    ("Fest", "#b5462f"),
    ("Umzug", "#8a5a12"),
    ("Schießen", "#3f6f2f"),
    ("Geselliges", "#6a4f8f"),
)


def module_on(org: Organization | None) -> bool:
    return bool(org) and MODULE in (org.enabled_modules or [])


def federation_of(org: Organization) -> Organization | None:
    parent = org.parent if org.type == Organization.Type.CLUB else None
    if parent is not None and parent.type == Organization.Type.FEDERATION and module_on(parent):
        return parent
    return None


def is_board(user, org: Organization) -> bool:
    return (
        RoleAssignment.objects.active()
        .filter(user=user, organization=org, role__is_board=True)
        .exists()
    )


def _shared_of(org: Organization) -> Q:
    """Nicht interne Termine einer Organisation selbst (ohne Abteilungen)."""
    return Q(organization=org, department__isnull=True, visibility__in=SHARED)


def _flag(direction: str, owner: str) -> Q:
    """Termin wird nach oben bzw. unten weitergegeben: Angabe am Termin, sonst die
    Voreinstellung der anbietenden Einheit (``owner``: "organization" oder "department")."""
    field = f"share_{direction}"
    return Q(**{field: True}) | Q(**{f"{field}__isnull": True, f"{owner}__events_{field}": True})


def up(owner: str) -> Q:
    return _flag("up", owner)


def down(owner: str) -> Q:
    return _flag("down", owner)


def effective_share(event: Event, direction: str) -> bool:
    value = getattr(event, f"share_{direction}")
    if value is not None:
        return value
    owner = event.department if event.department_id else event.organization
    return getattr(owner, f"events_share_{direction}")


def has_own_calendar_admin(unit: Department) -> bool:
    """Hat die Untereinheit eine eigene Verwaltung für ihren Kalender?

    Dann entscheidet sie selbst über die Weitergabe ihrer Termine, sonst die
    Einheit darüber.
    """
    from members.models import DepartmentRoleHolder, today
    from portal.models import PortalAccess

    club = unit.organization
    if club is None or not club.department_access_enabled:
        return False
    on = today()
    # Eine Rolle gilt auch für alle Untereinheiten darunter
    units = UnitTree.of(club.pk).ancestors(unit.pk) or [unit.pk]
    memberships = (
        DepartmentRoleHolder.objects.filter(
            role__department_id__in=units,
            role__department__self_managed=True,
            role__permissions__contains=[DEPT_EVENTS_MANAGE],
            valid_from__lte=on,
        )
        .exclude(valid_until__lt=on)
        .values_list("membership_id", flat=True)
    )
    return PortalAccess.objects.filter(
        organization=club, membership_id__in=list(memberships), user__isnull=False
    ).exists()


@dataclass
class Viewer:
    """Sicht auf Kalender. ``org`` = Organisation, in deren RLS-Kontext gelesen wird."""

    org: Organization
    department: Department | None = None
    can_manage: bool = False
    sees_board: bool = False
    # Mitgliederbereich: Untereinheiten des Mitglieds samt denen darüber …
    member_departments: list[int] = field(default_factory=list)
    # … und nur die, denen das Mitglied direkt angehört
    member_direct: list[int] = field(default_factory=list)
    kind: str = "org"  # org | department | member | public
    # Mitgliederbereich: eigene Mitgliedschaft (für Zu- und Absagen)
    membership_id: int | None = None
    # Finanzen der Organisation: "" (kein Zugriff), "view" oder "edit"
    finance: str = ""

    def visible_q(self) -> Q:
        org = self.org
        fed = federation_of(org)
        if self.kind == "public":
            return Q(
                organization=org,
                department=self.department,
                visibility=Event.Visibility.PUBLIC,
            )
        if self.kind == "department":
            # Eigene Termine; die der Untereinheiten, wenn sie nach oben freigegeben
            # sind; die der Einheiten darüber, wenn sie nach unten freigegeben sind
            tree = UnitTree.of(org.pk)
            q = (
                Q(organization=org, department=self.department)
                | Q(
                    organization=org,
                    department_id__in=tree.subtree(self.department.pk)[1:],
                    visibility__in=SHARED,
                )
                & up("department")
                | Q(
                    organization=org,
                    department_id__in=tree.ancestors(self.department.pk)[1:],
                    visibility__in=SHARED,
                )
                & down("department")
                | _shared_of(org) & down("organization")
            )
        elif self.kind == "member":
            # Termine der eigenen Untereinheiten immer, die der Einheiten darüber
            # nach ihrer Freigabe nach unten
            above = [d for d in self.member_departments if d not in self.member_direct]
            q = (
                _shared_of(org)
                | Q(
                    organization=org,
                    department_id__in=self.member_direct,
                    visibility__in=SHARED,
                )
                | Q(organization=org, department_id__in=above, visibility__in=SHARED)
                & down("department")
            )
        else:
            own = Q(organization=org, department__isnull=True)
            if not self.sees_board:
                own &= Q(visibility__in=SHARED)
            q = own
            if org.type == Organization.Type.CLUB:
                # Termine der Untereinheiten, wenn sie nach oben freigegeben sind
                q |= Q(organization=org, department__isnull=False, visibility__in=SHARED) & up(
                    "department"
                )
            # Termine der Einheiten mit eigenem Datenbereich direkt darunter
            q |= Q(
                organization__parent=org,
                organization__type=Organization.Type.CLUB,
                department__isnull=True,
                visibility__in=SHARED,
            ) & up("organization")
        if fed is not None:
            q |= _shared_of(fed) & down("organization")
        # Verbund: übermittelte Termine der fernen Einheit darüber (sie hat schon
        # nur weitergegeben, was nach unten freigegeben ist)
        from peering.services import remote_parent

        remote = remote_parent(org) if self.kind != "public" else None
        if remote is not None:
            q |= _shared_of(remote)
        return q

    def events(self):
        return (
            Event.objects.filter(self.visible_q())
            .select_related("organization", "department", "category", "project")
            .distinct()
        )

    def owns(self, event: Event) -> bool:
        """Gehört der Termin zum Kalender dieser Sicht?"""
        if event.organization_id != self.org.pk:
            return False
        if self.department is None:
            return event.department_id is None
        return event.department_id == self.department.pk

    def can_edit(self, event: Event) -> bool:
        # Termine aus dem Verbund pflegt ihre Heimat-Instanz
        return (
            self.can_manage
            and self.kind in ("org", "department")
            and self.owns(event)
            and not event.remote_uid
        )

    def response_scope(self, event: Event) -> str | int | None:
        """Welche Rückmeldungen sieht diese Sicht?

        ``"all"`` (Vorstand der Ebene, die den Termin angelegt hat), die Abteilung
        (Zugvorstand bei Vereinsterminen: nur seine Zugmitglieder) oder ``None``.
        """
        if self.can_edit(event):
            return "all"
        if (
            self.kind == "department"
            and self.can_manage
            and event.organization_id == self.org.pk
            and event.department_id is None
        ):
            return self.department.pk
        return None


def org_viewer(user, org: Organization, perms: set[str]) -> Viewer:
    manage = EVENTS_MANAGE in perms
    finance = ""
    if "finance" in (org.enabled_modules or []):
        finance = "edit" if FINANCE_EDIT in perms else "view" if FINANCE_VIEW in perms else ""
    return Viewer(org, None, manage, manage or is_board(user, org), kind="org", finance=finance)


def department_viewer(ctx) -> Viewer:
    return Viewer(
        ctx.club,
        ctx.department,
        DEPT_EVENTS_MANAGE in ctx.permissions,
        True,
        kind="department",
    )


def member_viewer(
    club: Organization, department_ids: list[int], membership_id: int | None = None
) -> Viewer:
    # Wer einer Untereinheit angehört, sieht auch die Termine der Einheiten darüber
    ids = list(department_ids)
    ids = sorted(with_ancestors(club.pk, ids) or ids)
    return Viewer(
        club,
        None,
        False,
        False,
        ids,
        sorted(department_ids),
        kind="member",
        membership_id=membership_id,
    )


def owner_label(event: Event, short: bool = False) -> str:
    """Wer den Termin anbietet; ``short`` für Listen (Kurzname, falls vorhanden)."""
    owner = event.department if event.department_id else event.organization
    return owner.display_name if short else owner.name


def level(event: Event) -> str:
    if event.department_id:
        return "department"
    return event.organization.type


def ensure_categories(org: Organization) -> None:
    """Neue Kalender starten mit ein paar Kategorien (lassen sich ändern)."""
    if not EventCategory.objects.filter(organization=org).exists():
        EventCategory.objects.bulk_create(
            EventCategory(organization=org, name=name, color=color)
            for name, color in DEFAULT_CATEGORIES
        )


def publication(org, department=None, create: bool = False) -> CalendarPublication | None:
    pub = CalendarPublication.objects.filter(organization=org, department=department).first()
    if pub is None and create:
        pub = CalendarPublication.objects.create(
            organization=org, department=department, public_key=CalendarPublication.new_key()
        )
    return pub


def parse_range(params) -> tuple[datetime.datetime, datetime.datetime]:
    """Zeitraum aus ``from``/``to`` (Datum, jeweils einschließlich). Standard: 3 Monate."""
    today = timezone.localdate()

    def _date(name: str, default: datetime.date) -> datetime.date:
        value = params.get(name)
        if not value:
            return default
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            return default

    start = _date("from", today.replace(day=1))
    end = _date("to", start + datetime.timedelta(days=92))
    if end < start:
        end = start
    # Höchstens etwa ein Jahr und zwei Monate (Jahresprogramm mit Vorschau)
    end = min(end, start + datetime.timedelta(days=430))
    tz = timezone.get_current_timezone()
    begin = timezone.make_aware(datetime.datetime.combine(start, datetime.time.min), tz)
    finish = timezone.make_aware(
        datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min), tz
    )
    return begin, finish
