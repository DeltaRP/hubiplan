"""Paket „Mitgliedermeldung“ (P4) nach oben.

Stufe A: nur Zahlen der gemeldeten Mitgliedschaften (Mitgliedsart mit „an
Dachverband melden“) am Tag der Meldung, nach aktiv/passiv und Geburtsmonat. Das
reicht für die Beitragsrechnung des Dachverbands nach seinen Altersstufen. Kein
Personenbezug: Geburtsmonat und Anzahl, nie Namen.
"""

from __future__ import annotations

import datetime

from django.db.models import Q
from django.utils import timezone

from .models import RemoteState
from .packets import UP, Packet, register

LEVEL_A = "a"
LEVEL_B = "b"


def _current(club, on):
    from core.tenancy import tenant_context
    from members.models import Membership

    with tenant_context(club.pk):
        memberships = (
            Membership.objects.filter(organization=club, purged_at__isnull=True)
            .filter(
                Q(periods__entry_date__lte=on)
                & (Q(periods__exit_date__isnull=True) | Q(periods__exit_date__gte=on))
            )
            .distinct()
            .select_related("person")
            .prefetch_related("type_assignments__member_type", "periods")
        )
        result = []
        for m in memberships:
            assignment = m.current_type(on)
            if assignment is None or not assignment.member_type.reported:
                continue
            result.append((m, assignment.member_type))
        return result


def build(coupling, level):
    on = timezone.localdate()
    counts: dict[tuple[str, str], int] = {}
    for m, member_type in _current(coupling.local_unit, on):
        kind = "active" if member_type.active else "passive"
        birth = m.person.birth_date.strftime("%Y-%m") if m.person.birth_date else ""
        counts[(kind, birth)] = counts.get((kind, birth), 0) + 1
    rows = [{"kind": k, "birth": b, "n": n} for (k, b), n in sorted(counts.items())]
    data = {"on": on.isoformat(), "counts": rows, "total": sum(counts.values())}
    if level == LEVEL_B:
        from .register import build_rows

        data["persons"] = build_rows(coupling)
    return data


def apply(coupling, data):
    from core.tenancy import unit_context

    # Gemeldete Mitgliedschaften gehören dem Platzhalter des Vereins (Verbandsbereich oben)
    with unit_context(coupling.remote_unit_id):
        _apply(coupling, data)


def _apply(coupling, data):
    from . import register

    state, _ = RemoteState.objects.get_or_create(coupling=coupling, key="members")
    if data.get("level") == LEVEL_B and isinstance(data.get("persons"), list):
        register.apply_rows(coupling, data["persons"])
    else:
        register.withdraw_all(coupling)
    if not data.get("level"):
        state.delete()
        return
    rows = []
    for row in (data.get("counts") or [])[:5000]:
        if not isinstance(row, dict) or row.get("kind") not in ("active", "passive"):
            continue
        try:
            n = int(row.get("n"))
        except (TypeError, ValueError):
            continue
        birth = str(row.get("birth") or "")[:7]
        rows.append({"kind": row["kind"], "birth": birth, "n": max(0, min(n, 100000))})
    state.data = {
        "level": data.get("level"),
        "on": str(data.get("on") or "")[:10],
        "counts": rows,
        "total": sum(r["n"] for r in rows),
    }
    state.save()


def counts_for(federation, club, on, stages):
    """Gemeldete Zahlen eines fernen Vereins für die Beitragsrechnung des Dachverbands
    (gleiche Schlüssel wie ``billing.services.reported_counts``, ohne Ehrungen).

    None bei namentlicher Meldung: Dann liegen die Mitgliedschaften im Platzhalter."""
    from billing.services import age_on

    from .models import Coupling

    coupling = Coupling.objects.filter(remote_unit_id=club.pk).first()
    if coupling is None or coupling.state not in ("active", "paused"):
        return {}
    state = RemoteState.objects.filter(coupling=coupling, key="members").first()
    if state is None:
        return {}
    if state.data.get("level") == LEVEL_B:
        return None  # namentlich gemeldet: rechnen wie bei Vereinen derselben Instanz
    ref = federation.fiscal_start(federation.fiscal_year_of(on))
    result: dict = {}
    for row in state.data.get("counts") or []:
        try:
            year, month = (int(x) for x in row["birth"].split("-"))
            birth = datetime.date(year, month, 15)
        except (KeyError, ValueError):
            birth = None
        age = age_on(birth, ref) if birth else 0
        stage = next(
            (
                st.pk
                for st in sorted(stages, key=lambda x: (x.min_age or 0, x.pk))
                if st.matches(age)
            ),
            0,
        )
        key = (row["kind"], stage, ())
        result[key] = result.get(key, 0) + int(row["n"])
    return result


register(
    Packet(
        "members",
        "Mitgliedermeldung an die Einheit darüber",
        (UP,),
        levels=(
            (LEVEL_A, "Stufe A: nur Zahlen (aktiv/passiv, Geburtsmonat)"),
            (
                LEVEL_B,
                "Stufe B: namentlich minimal (Name, Vorname, Geburtsdatum, Verbandsnummer, "
                "Mitgliedsart, Zeiträume)",
            ),
        ),
        personal="Stufe A: keiner (nur Anzahlen) · Stufe B: ja, nur das Minimum",
        build=build,
        apply=apply,
        persons=lambda data: len(data.get("persons") or []),
    )
)
