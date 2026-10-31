"""Mandantentrennung auf Datenbankebene (PostgreSQL Row-Level Security).

Die Anwendung filtert jede Abfrage selbst nach Organisation. Zusätzlich sperrt
PostgreSQL fremde Zeilen per RLS. Dafür setzt die Anwendung je Anfrage drei
Sitzungsvariablen, die die RLS-Regeln (siehe core/rls.py) auswerten:

- ``app.org_id``      aktive Organisation der Anfrage
- ``app.user_id``     angemeldeter Benutzer (darf seine eigenen Rollen sehen)
- ``app.bypass_rls``  'on' nur für Systemaufgaben (Admin, Seed, Plattformbereich)
- ``app.scope_id``    Verbandsbereich (Dachverband bzw. eigenständiger Verein)
- ``app.fed_access``  Freigabe des Dachverbands auf Mitgliedsdaten seiner Vereine

RLS greift nur, wenn die Anwendung nicht als Tabelleneigentümer arbeitet. Deshalb
wechselt jede Verbindung zur Laufzeit in die Rolle ``DATABASE_APP_ROLE``
(Standard: hubiplan_app). Migrationen laufen ohne diesen Wechsel.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace

from django.conf import settings
from django.db import connection
from django.db.backends.signals import connection_created
from django.dispatch import receiver

_STATE_ATTR = "_hubiplan_rls"


@dataclass(frozen=True)
class RlsState:
    org_id: int | None = None
    user_id: int | None = None
    bypass: bool = False
    # Verbandsbereich: Dachverband des aktiven Vereins (oder der Verein selbst,
    # wenn er keinem Dachverband angehört). Personen und Verbandsnummern gelten
    # in diesem Bereich.
    scope_id: int | None = None
    # Freigabe des Dachverbands für Mitgliedsdaten: "", "read" oder "write"
    fed_access: str = ""


def _is_postgres() -> bool:
    return connection.vendor == "postgresql"


def _apply(state: RlsState) -> None:
    setattr(connection, _STATE_ATTR, state)
    if not _is_postgres():
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.org_id', %s, false), "
            "set_config('app.user_id', %s, false), "
            "set_config('app.bypass_rls', %s, false), "
            "set_config('app.scope_id', %s, false), "
            "set_config('app.fed_access', %s, false)",
            [
                "" if state.org_id is None else str(state.org_id),
                "" if state.user_id is None else str(state.user_id),
                "on" if state.bypass else "off",
                "" if state.scope_id is None else str(state.scope_id),
                state.fed_access,
            ],
        )


def scope_of(org_id: int | None) -> int | None:
    """Verbandsbereich einer Organisation (Organisationen haben kein RLS)."""
    if org_id is None:
        return None
    from organizations.models import Organization

    org = Organization.objects.filter(pk=org_id).select_related("parent").first()
    if org is None:
        return None
    if org.type == Organization.Type.CLUB and org.parent and org.parent.type == "federation":
        return org.parent_id
    return org.pk


def set_rls(
    org_id: int | None = None,
    user_id: int | None = None,
    bypass: bool = False,
    scope_id: int | None = None,
    fed_access: str = "",
) -> None:
    """Setzt die RLS-Sitzungsvariablen der aktuellen Datenbankverbindung."""
    _apply(RlsState(org_id, user_id, bypass, scope_id, fed_access))


def get_rls() -> RlsState:
    return getattr(connection, _STATE_ATTR, RlsState())


def reset_rls() -> None:
    _apply(RlsState())


@contextmanager
def tenant_context(
    org_id: int | None, user_id: int | None = None, scope_id: int | None = None
) -> Iterator[None]:
    """Arbeitet vorübergehend im Kontext einer Organisation."""
    previous = get_rls()
    _apply(
        replace(
            previous,
            org_id=org_id,
            user_id=user_id if user_id is not None else previous.user_id,
            scope_id=scope_id if scope_id is not None else scope_of(org_id),
            fed_access="",
        )
    )
    try:
        yield
    finally:
        _apply(previous)


@contextmanager
def unit_context(org_id: int) -> Iterator[None]:
    """Arbeitet streng im Bereich einer Organisation, auch innerhalb von ``rls_bypass``.

    Für Eingänge von außen (Verbund): Erst wird unter Umgehung gesucht, wer gemeint ist,
    dann läuft die Verarbeitung mit RLS wie für einen Vorstand dieser Einheit."""
    previous = get_rls()
    _apply(RlsState(org_id=org_id, scope_id=scope_of(org_id)))
    try:
        yield
    finally:
        _apply(previous)


@contextmanager
def rls_bypass() -> Iterator[None]:
    """Hebt RLS vorübergehend auf. Nur für Systemaufgaben verwenden."""
    previous = get_rls()
    _apply(replace(previous, bypass=True))
    try:
        yield
    finally:
        _apply(previous)


@contextmanager
def user_view(user_id: int | None) -> Iterator[None]:
    """Sicht genau eines Kontos auf seine eigenen Zeilen (Rollen, Zugänge).

    Für Sicherheitsentscheidungen über ein Konto, das noch nicht angemeldet ist
    (Verbundanmeldung, Anmeldelinks) oder nicht der Aufrufer ist (Geräte abmelden):
    In der Sicht des Aufrufers fehlen dessen Zeilen sonst unter RLS, und die Prüfung
    fiele fälschlich zu dessen Gunsten aus (Gesamtaudit 31.10.b, AT-S01/AT-F01).
    """
    previous = get_rls()
    _apply(RlsState(user_id=user_id))
    try:
        yield
    finally:
        _apply(previous)


@receiver(connection_created)
def _switch_to_app_role(sender, connection, **kwargs) -> None:
    role = getattr(settings, "DATABASE_APP_ROLE", "")
    if role and connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(f'SET ROLE "{role}"')


class TenantMiddleware:
    """Setzt die RLS-Variablen zu Beginn jeder Anfrage zurück.

    Verbindungen werden wiederverwendet; ohne Zurücksetzen könnte eine Anfrage
    den Organisationskontext der vorherigen erben. Die aktive Organisation setzt
    erst die API-Ansicht, nachdem sie die Berechtigung geprüft hat.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        user_id = user.pk if user is not None and user.is_authenticated else None
        # Django-Admin: nur für Superuser, arbeitet organisationsübergreifend
        bypass = bool(
            request.path.startswith("/admin/") and user_id and user.is_superuser  # type: ignore[union-attr]
        )
        set_rls(None, user_id, bypass)
        try:
            return self.get_response(request)
        finally:
            reset_rls()
