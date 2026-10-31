"""Untereinheit auf eine eigene Instanz ausgliedern (Verbund, Schritt 8c).

Ablauf:

1. Der Vereinsvorstand wählt Weg und Stichtag und bestätigt die Prüfliste. Es entstehen ein
   Kopplungscode, der an diese Untereinheit gebunden ist, und ein Export der Untereinheit, in
   dem Weg, Stichtag und Code stehen.
2. Die neue Instanz liest den Export auf Plattformebene ein (Schritt 8b) und fragt mit dem
   Code die Kopplung unter den Verein an.
3. Bestätigt der Verein, wird die Untereinheit zum Platzhalter der fernen Einheit. Was mit den
   Mitgliedschaften geschieht, hängt vom Weg ab (Schritte 8d und 8e).
"""

from __future__ import annotations

import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Coupling, SpinOff

CODE_VALID = datetime.timedelta(days=30)
# Prüfliste je Weg: Schlüssel und Text (alle müssen bestätigt sein)
CHECKLIST = {
    SpinOff.Way.KEEP: {
        "privacy": "Die Datenschutzhinweise des Vereins nennen die neue Instanz.",
        "processing": "Die Auftragsverarbeitung mit dem Betreiber der neuen Instanz ist geregelt.",
    },
    SpinOff.Way.MOVE: {
        "statute": "Der Wechsel der Mitglieder ist nach der Satzung beschlossen "
        "(z. B. Mitgliederversammlung) und den Mitgliedern mitgeteilt.",
        "processing": "Die Übergabe der Mitgliederdaten an die neue Einheit ist geregelt.",
    },
}


def open_spin_off(unit) -> SpinOff | None:
    return SpinOff.objects.filter(
        unit=unit, state__in=[SpinOff.State.PREPARED, SpinOff.State.REQUESTED]
    ).first()


def check_unit(club, unit) -> None:
    from organizations.models import Department

    from . import services

    services.require_enabled()
    if unit.type != unit.Type.UNIT or unit.organization_id != club.pk:
        raise ValidationError("Unbekannte Untereinheit.")
    if unit.is_remote:
        raise ValidationError("Diese Einheit liegt schon auf einer anderen Instanz.")
    if not unit.is_active:
        raise ValidationError("Die Untereinheit ist stillgelegt.")
    if Department.objects.filter(parent=unit).exists():
        raise ValidationError(
            "Die Untereinheit hat selbst Untereinheiten. Bitte diese vorher umhängen; "
            "ausgegliedert wird immer eine Untereinheit ohne eigene Untereinheiten."
        )
    if open_spin_off(unit):
        raise ValidationError("Für diese Untereinheit ist schon eine Ausgliederung vorbereitet.")


def prepare(club, unit, user, *, way: str, cutoff, checklist: dict, with_files: bool):
    """Code und Export erstellen. Gibt die Ausgliederung zurück (Export läuft im Hintergrund)."""
    from datatransfer.models import TransferJob
    from datatransfer.views import start_export

    from . import services

    check_unit(club, unit)
    if way not in SpinOff.Way.values:
        raise ValidationError("Bitte einen Weg wählen.")
    missing = [text for key, text in CHECKLIST[way].items() if not (checklist or {}).get(key)]
    if missing:
        raise ValidationError("Bitte vorher bestätigen: " + " ".join(missing))
    if cutoff is None:
        raise ValidationError("Bitte einen Stichtag angeben.")
    with transaction.atomic():
        text, code = services.create_code(club, user, valid=CODE_VALID)
        job = start_export(
            club,
            user,
            kind=TransferJob.Kind.DEPARTMENT,
            with_files=with_files,
            department=unit,
            # Der Code kommt nur in die Exportdatei; danach behält die Datenbank nur die Prüfsumme
            extra={"spin_off": {"way": way, "cutoff": cutoff.isoformat(), "code": text}},
        )
        spin = SpinOff.objects.create(
            organization=club,
            unit=unit,
            way=way,
            cutoff=cutoff,
            checklist={k: True for k in CHECKLIST[way]},
            code=code,
            export_job=job,
            created_by=user,
        )
        services._audit_unit(
            club,
            user,
            f"Ausgliederung von „{unit.name}“ vorbereitet ({SpinOff.Way(way).label}, "
            f"Stichtag {cutoff:%d.%m.%Y})",
        )
    return spin


def cancel(spin: SpinOff, user) -> SpinOff:
    from . import services

    if spin.state != SpinOff.State.PREPARED:
        raise ValidationError(
            "Die Ausgliederung ist schon angefragt. Bitte die Kopplung unter Verbund ablehnen."
        )
    with transaction.atomic():
        if spin.code_id and spin.code.used_at is None:
            spin.code.expires_at = timezone.now()
            spin.code.save(update_fields=["expires_at"])
        spin.state = SpinOff.State.CANCELLED
        spin.save(update_fields=["state"])
        services._audit_unit(
            spin.organization, user, f"Ausgliederung von „{spin.unit.name}“ abgebrochen"
        )
    return spin


def placeholder_for(code):
    """Bei einem Code aus einer Ausgliederung: die Untereinheit selbst ist der Platzhalter."""
    spin = getattr(code, "spin_off", None)
    if spin is None or spin.state != SpinOff.State.PREPARED:
        return None
    if (
        Coupling.objects.filter(remote_unit=spin.unit)
        .exclude(state__in=[Coupling.State.ENDED, Coupling.State.MOVED])
        .exists()
    ):
        raise ValidationError("Diese Untereinheit ist schon gekoppelt.")
    return spin


def requested(spin: SpinOff, coupling: Coupling) -> None:
    spin.coupling = coupling
    spin.state = SpinOff.State.REQUESTED
    spin.save(update_fields=["coupling", "state"])


def accepted(coupling: Coupling, user) -> None:
    """Verein hat bestätigt: Untereinheit wird Platzhalter der fernen Einheit."""
    from . import services

    spin = SpinOff.objects.filter(coupling=coupling, state=SpinOff.State.REQUESTED).first()
    if spin is None:
        return
    unit = spin.unit
    unit.is_remote = True
    unit.save(update_fields=["is_remote"])
    if spin.way == SpinOff.Way.KEEP:
        # Weg A: heutige Mitglieder der Untereinheit werden beim Verein fern geführt (8d)
        from django.db.models import Q

        from members.models import Membership

        today = timezone.localdate()
        Membership.objects.filter(
            Q(department_memberships__valid_until__isnull=True)
            | Q(department_memberships__valid_until__gte=today),
            organization=spin.organization,
            department_memberships__department=unit,
            department_memberships__valid_from__lte=today,
        ).update(managed_by=coupling)
    spin.state = SpinOff.State.DONE
    spin.done_at = timezone.now()
    spin.save(update_fields=["state", "done_at"])
    services._audit(
        coupling, user, f"Untereinheit „{unit.name}“ ausgegliedert ({spin.get_way_display()})"
    )


def ended(coupling: Coupling) -> None:
    """Kopplung vor der Bestätigung abgelehnt oder gelöst: Untereinheit bleibt wie sie war."""
    SpinOff.objects.filter(coupling=coupling, state=SpinOff.State.REQUESTED).update(
        state=SpinOff.State.CANCELLED
    )


def export_data(job) -> dict | None:
    """Angaben für die Exportdatei (einmalig: der Code verlässt danach die Datenbank)."""
    info = (job.options or {}).get("spin_off")
    if not info:
        return None
    return dict(info)


# --- Weg B: Sammelaustritt zum Stichtag (Schritt 8e) ---


def exit_candidates(spin: SpinOff) -> list[dict]:
    """Mitgliedschaften, die zum Stichtag mit Grund „Wechsel“ enden würden (Vorschau)."""
    from django.db.models import Q

    from members.models import DepartmentMembership

    links = (
        DepartmentMembership.objects.filter(
            organization=spin.organization,
            department=spin.unit,
            valid_from__lte=spin.cutoff,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=spin.cutoff))
        .select_related("membership__person")
        .order_by("membership__person__last_name", "membership__person__first_name")
    )
    result, seen = [], set()
    for link in links:
        m = link.membership
        if m.pk in seen or not m.periods.filter(exit_date__isnull=True).exists():
            continue
        seen.add(m.pk)
        others = (
            m.department_memberships.exclude(department=spin.unit)
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gt=spin.cutoff))
            .select_related("department")
        )
        result.append(
            {
                "id": m.pk,
                "name": f"{m.person.last_name}, {m.person.first_name}",
                "also_in": [o.department.name for o in others],
            }
        )
    return result


def collective_exit(spin: SpinOff, user, exclude: list[int] | None = None) -> int:
    """Alle Mitglieder der Untereinheit treten zum Stichtag aus (Grund „Wechsel“).

    Die Zeiträume bleiben; danach gilt die Löschfrist wie bei jedem Austritt. Wer ausgenommen
    wird (z. B. bleibt zugleich in einer anderen Untereinheit), bleibt Mitglied."""
    from audit.log import record
    from members.models import ExitReason, Membership
    from members.workflows import exit_membership

    from . import services

    if spin.way != SpinOff.Way.MOVE:
        raise ValidationError("Nur bei „Mitglieder werden Mitglieder der Untereinheit“.")
    if spin.state != SpinOff.State.DONE:
        raise ValidationError("Erst nach der bestätigten Kopplung.")
    if spin.exited_at:
        raise ValidationError("Der Sammelaustritt ist schon ausgeführt.")
    skip = set(exclude or [])
    note = f"Wechsel zu {spin.unit.name} (Ausgliederung)"
    count = 0
    with transaction.atomic():
        spin = SpinOff.objects.select_for_update().get(pk=spin.pk)
        if spin.exited_at:
            raise ValidationError("Der Sammelaustritt ist schon ausgeführt.")
        for item in exit_candidates(spin):
            if item["id"] in skip:
                continue
            membership = Membership.objects.get(pk=item["id"], organization=spin.organization)
            exit_membership(membership, spin.cutoff, ExitReason.TRANSFER, note)
            record(
                spin.organization,
                user,
                "update",
                membership,
                {"Austritt": [None, f"{spin.cutoff:%d.%m.%Y}, {note}"]},
                person=membership.person,
            )
            count += 1
        spin.exited_at = timezone.now()
        spin.exited_count = count
        spin.save(update_fields=["exited_at", "exited_count"])
        services._audit_unit(
            spin.organization,
            user,
            f"Sammelaustritt zu „{spin.unit.name}“: {count} Mitglieder zum "
            f"{spin.cutoff:%d.%m.%Y} (Wechsel)",
        )
    return count
