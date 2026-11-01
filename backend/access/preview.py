"""Ansicht als Rolle: HUBIplan so zeigen, wie eine Rolle der Einheit es sieht.

Wer das Recht „Ansicht als Rolle“ hat, wählt eine Rolle seiner Einheit. Bis zum
Beenden gelten in dieser Einheit nur noch die Rechte, die er selbst hat und die
Rolle hat (Schnittmenge, Ralf 01.11.: nie mehr als die eigenen Rechte). Die Ansicht
ist nur zum Lesen: Die Middleware lehnt jede ändernde Anfrage an die API ab.

Die Wahl steht in der Sitzung, damit auch Dateien, Bilder und weitere Tabs dieselbe
Ansicht bekommen. Beginn und Ende stehen im Änderungsprotokoll der Einheit.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass

from django.http import JsonResponse

SESSION_KEY = "hubiplan_ansicht"

READ_ONLY_MESSAGE = (
    "Ansicht als Rolle: Hier wird nur gelesen. Beende die Ansicht oben, um etwas zu ändern."
)

# Ändernde Anfragen, die während der Ansicht erlaubt bleiben: die Ansicht selbst
# beginnen oder beenden und das CSRF-Token holen. An- und Abmelden laufen nicht
# über /api/ und bleiben ohnehin möglich.
_ALLOWED = re.compile(r"^/api/(csrf/|orgs/\d+/ansicht/)$")


@dataclass(frozen=True)
class Preview:
    user_id: int
    org_id: int
    role_id: int


_current: ContextVar[Preview | None] = ContextVar("hubiplan_ansicht", default=None)


def current() -> Preview | None:
    return _current.get()


def from_session(request) -> Preview | None:
    session = getattr(request, "session", None)
    user = getattr(request, "user", None)
    if session is None or user is None or not user.is_authenticated:
        return None
    data = session.get(SESSION_KEY)
    if not isinstance(data, dict):
        return None
    try:
        preview = Preview(int(data["user"]), int(data["org"]), int(data["role"]))
    except (KeyError, TypeError, ValueError):
        return None
    # Gehört zu einem anderen Konto (sollte nach dem Anmelden nie vorkommen)
    return preview if preview.user_id == user.pk else None


def start(request, org, role) -> None:
    request.session[SESSION_KEY] = {"user": request.user.pk, "org": org.pk, "role": role.pk}
    _current.set(Preview(request.user.pk, org.pk, role.pk))


def stop(request) -> None:
    request.session.pop(SESSION_KEY, None)
    _current.set(None)


def role_permissions(org, role_id: int) -> set[str] | None:
    """Rechte der Rolle (None: Rolle gibt es in dieser Einheit nicht mehr)."""
    from core.tenancy import tenant_context

    from .models import Role

    with tenant_context(org.pk):
        perms = (
            Role.objects.filter(pk=role_id, organization=org)
            .values_list("permissions", flat=True)
            .first()
        )
    if perms is None:
        return None
    return {p for p in perms if isinstance(p, str)}


def apply(user, org, perms: set[str]) -> set[str]:
    """Rechte in ``org`` während einer Ansicht als Rolle (sonst unverändert)."""
    from .catalog import ROLES_PREVIEW

    preview = _current.get()
    if preview is None or preview.user_id != user.pk or preview.org_id != org.pk:
        return perms
    if ROLES_PREVIEW not in perms:
        return perms  # Recht inzwischen entzogen: Ansicht gilt nicht mehr
    role_perms = role_permissions(org, preview.role_id)
    if role_perms is None:
        return perms
    return perms & role_perms


class RolePreviewMiddleware:
    """Ansicht aus der Sitzung lesen; während der Ansicht nur lesende API-Anfragen."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        preview = from_session(request)
        token = _current.set(preview)
        try:
            if (
                preview is not None
                and request.method not in ("GET", "HEAD", "OPTIONS")
                and request.path.startswith("/api/")
                and not _ALLOWED.match(request.path)
            ):
                return JsonResponse({"detail": READ_ONLY_MESSAGE, "ansicht": True}, status=403)
            return self.get_response(request)
        finally:
            _current.reset(token)
