"""Pakete „Vorstand“ (P2) und „Satzung“ (P11): beide Richtungen, nur Anzeige."""

from __future__ import annotations

import base64

from django.core.files.base import ContentFile

from core import virenscan
from core.files import delete_on_commit

from .models import RemoteState
from .packets import BOTH, Packet, file_b64, register

STATUTE_LIMIT = 8 * 1024 * 1024


def build_board(coupling, level):
    """Wie auf der Webseite: nur Rollen mit „auf der Webseite zeigen“, Namen nur mit
    Einwilligung. Ohne eingerichtete Webseite nur Rollen und Funktionsadressen."""
    from access.models import Role
    from website.models import Website
    from website.public import SiteView

    org = coupling.local_unit
    website = Website.objects.filter(organization=org).first()
    if website is not None:
        roles = []
        for entry in SiteView(website).board():
            holders = [
                {"name": h.get("name", "")} for h in entry.get("holders", []) if h.get("name")
            ]
            roles.append(
                {
                    "role": entry.get("role") or entry.get("name") or "",
                    "email": entry.get("email") or "",
                    "holders": holders,
                }
            )
        return {"roles": roles}
    roles = Role.objects.filter(organization=org, on_website=True).order_by("position", "name")
    return {
        "roles": [{"role": r.name, "email": r.contact_email or "", "holders": []} for r in roles]
    }


def _store(coupling, key, data, file_bytes=None, filename=""):
    state, _ = RemoteState.objects.get_or_create(coupling=coupling, key=key)
    # Alte Dateien erst nach dem Commit löschen: Bei einem Fehler zeigt die Datenbank
    # wieder auf sie (Gesamtaudit 31.10.b, INF-F02)
    if not data.get("level"):
        delete_on_commit(state.file)
        state.delete()
        return
    state.data = data
    if file_bytes is not None:
        delete_on_commit(state.file)
        state.file.save(filename or f"{key}.pdf", ContentFile(file_bytes), save=False)
    state.save()


def apply_board(coupling, data):
    roles = []
    for r in (data.get("roles") or [])[:100] if data.get("level") else []:
        if not isinstance(r, dict):
            continue
        roles.append(
            {
                "role": str(r.get("role") or "")[:100],
                "email": str(r.get("email") or "")[:254],
                "holders": [
                    {"name": str(h.get("name") or "")[:200]}
                    for h in (r.get("holders") or [])[:20]
                    if isinstance(h, dict)
                ],
            }
        )
    _store(coupling, "board", {"level": data.get("level"), "roles": roles})


def persons_board(data):
    return sum(len(r.get("holders") or []) for r in data.get("roles") or [])


def build_statute(coupling, level):
    from statutes.models import Kind, StatuteVersion
    from statutes.services import publication

    org = coupling.local_unit
    pub = publication(org)
    if pub is None or not pub.is_public:
        return {"statute": None}
    current = (
        StatuteVersion.objects.filter(organization=org, department__isnull=True, kind=Kind.STATUTE)
        .order_by("-valid_from", "-pk")
        .first()
    )
    if current is None:
        return {"statute": None}
    return {
        "statute": {
            "valid_from": current.valid_from.isoformat(),
            "note": current.note,
            "name": current.name,
            "pdf": file_b64(current.file, STATUTE_LIMIT),
        }
    }


def apply_statute(coupling, data):
    statute = data.get("statute") if data.get("level") else None
    if not isinstance(statute, dict) or not statute.get("pdf"):
        _store(coupling, "statute", {"level": None})
        return
    try:
        raw = base64.b64decode(statute["pdf"], validate=True)
    except ValueError:
        return
    if len(raw) > STATUTE_LIMIT or not raw.startswith(b"%PDF"):
        return
    if not virenscan.inbound_ok(raw, "Satzung.pdf", "Satzung aus dem Verbund"):
        return
    meta = {
        "level": data.get("level"),
        "valid_from": str(statute.get("valid_from") or "")[:10],
        "note": str(statute.get("note") or "")[:500],
        "name": str(statute.get("name") or "Satzung.pdf")[:200],
    }
    _store(coupling, "statute", meta, raw, "satzung.pdf")


register(
    Packet(
        "board",
        "Vorstand (wie auf der Webseite: Rollen, Namen nur mit Einwilligung)",
        BOTH,
        personal="Namen der Vorstände mit Einwilligung zur Veröffentlichung",
        build=build_board,
        apply=apply_board,
        persons=persons_board,
        under_club=True,
    )
)
register(
    Packet(
        "statute",
        "Satzung (nur wenn sie öffentlich abrufbar ist)",
        BOTH,
        default="on",
        build=build_statute,
        apply=apply_statute,
        under_club=True,
    )
)
