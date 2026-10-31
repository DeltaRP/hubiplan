"""Wechsel zwischen Vereinen über Instanzgrenzen (Verbund, nur mit namentlicher Meldung).

Der Dachverband vermittelt, wie bei Vereinen auf derselben Instanz: Die Anfrage
landet beim bisherigen Verein, der Austritt oder eine nicht aktive Art bestätigt
oder ablehnt; danach nimmt der neue Verein auf. Liegt einer der beiden Vereine auf
einer anderen Instanz, gehen Anfrage und Entscheidung als Pakete hin und her:

- ``transfer.request`` nach unten (bisheriger Verein entscheidet) oder nach oben
  (ferner Verein möchte aufnehmen),
- ``transfer.decision`` in Gegenrichtung,
- ``transfer.cancel`` nach unten, wenn der neue Verein zurückzieht.

Der bisherige Verein schickt vor seiner Entscheidung den neuen Stand der Meldung,
damit der Dachverband den Austritt kennt, bevor der neue Verein aufnimmt.
"""

from __future__ import annotations

import contextvars
import datetime
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Coupling, RemoteMember, RemoteTransfer

# Während einer bestätigten Aufnahme nicht erneut beim Dachverband nachfragen
skip_remote_check = contextvars.ContextVar("skip_remote_check", default=False)


def _date(value):
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _coupling_of(placeholder) -> Coupling:
    coupling = Coupling.objects.filter(remote_unit=placeholder).select_related("peer").first()
    if coupling is None or not coupling.is_open:
        raise ValidationError(f"{placeholder.name} ist derzeit nicht erreichbar gekoppelt.")
    return coupling


def _number_of(person) -> int | None:
    from members.models import FederationMember

    return (
        FederationMember.objects.filter(person=person)
        .values_list("member_number", flat=True)
        .first()
    )


# --- oben (Dachverband) ---


def ask_from_side(request) -> RemoteTransfer:
    """Wechselanfrage an einen bisherigen Verein auf einer anderen Instanz schicken."""
    from . import services

    coupling = _coupling_of(request.from_org)
    rm = (
        RemoteMember.objects.filter(
            coupling=coupling,
            status=RemoteMember.Status.ACTIVE,
            membership__person=request.person,
        )
        .order_by("-updated_at")
        .first()
    )
    if rm is None:
        raise ValidationError("Die Person ist beim bisherigen Verein nicht namentlich gemeldet.")
    rt = RemoteTransfer.objects.create(
        coupling=coupling, role=RemoteTransfer.Role.FROM, transfer=request
    )
    services.enqueue(
        coupling,
        "transfer.request",
        {
            "tid": str(rt.tid),
            "uid": rm.uid,
            "to_unit": request.to_org.name,
            "entry_date": request.entry_date.isoformat(),
            "member_type_name": request.member_type_name,
            "message": request.message,
        },
        persons=1,
    )
    return rt


def cancelled(request) -> None:
    from . import services

    for rt in RemoteTransfer.objects.filter(
        transfer=request, role=RemoteTransfer.Role.FROM, status=RemoteTransfer.Status.PENDING
    ).select_related("coupling"):
        rt.status = RemoteTransfer.Status.CANCELLED
        rt.decided_at = timezone.now()
        rt.save(update_fields=["status", "decided_at"])
        if rt.coupling.is_open:
            services.enqueue(rt.coupling, "transfer.cancel", {"tid": str(rt.tid)})


def decided(request) -> None:
    """Entscheidung an einen neuen Verein auf einer anderen Instanz melden."""
    from members.models import TransferRequest

    from . import services

    rt = (
        RemoteTransfer.objects.filter(transfer=request, role=RemoteTransfer.Role.TO)
        .select_related("coupling")
        .first()
    )
    if rt is None:
        return
    accepted = request.status == TransferRequest.Status.ACCEPTED
    rt.status = RemoteTransfer.Status.ACCEPTED if accepted else RemoteTransfer.Status.REJECTED
    rt.response = request.response
    rt.decided_at = timezone.now()
    rt.save(update_fields=["status", "response", "decided_at"])
    if rt.coupling.is_open:
        services.enqueue(
            rt.coupling,
            "transfer.decision",
            {
                "tid": str(rt.tid),
                "status": "accepted" if accepted else "rejected",
                "response": request.response,
                "number": _number_of(request.person) if accepted else None,
            },
        )


def _receive_request_above(coupling: Coupling, data: dict) -> None:
    """Ein ferner Verein möchte jemanden aktiv aufnehmen."""
    from members.models import MemberType, TransferRequest
    from members.workflows import active_membership_elsewhere

    from . import register, services

    tid = str(data.get("tid") or "")
    if RemoteTransfer.objects.filter(coupling=coupling, tid=tid).exists():
        return
    placeholder = coupling.remote_unit
    federation = placeholder.parent
    entry = _date(data.get("entry_date")) or timezone.localdate()
    person = register._person_for(federation, {"number": data.get("number")})
    if person is None:
        candidates = register._candidates(
            federation,
            {
                "birth_date": _date(data.get("birth_date")),
                "last_name": str(data.get("last_name") or "").strip(),
                "first_name": str(data.get("first_name") or "").strip(),
            },
        )
        if len(candidates) == 1:
            from members.models import Person

            person = Person.objects.get(pk=candidates[0])
    other = active_membership_elsewhere(person, placeholder, entry) if person else None
    if other is None:
        # Nicht (mehr) anderswo aktiv: Der Verein darf direkt aufnehmen
        RemoteTransfer.objects.create(
            coupling=coupling,
            tid=tid,
            role=RemoteTransfer.Role.TO,
            status=RemoteTransfer.Status.ACCEPTED,
            decided_at=timezone.now(),
        )
        services.enqueue(
            coupling,
            "transfer.decision",
            {"tid": tid, "status": "accepted", "response": "", "number": None},
        )
        return
    name = str(data.get("member_type_name") or "aktiv")[:100]
    member_type, _ = MemberType.objects.get_or_create(
        organization=placeholder, name=name, defaults={"active": True, "reported": True}
    )
    request = TransferRequest.objects.create(
        scope=federation,
        person=person,
        from_org=other.organization,
        to_org=placeholder,
        member_type=member_type,
        member_type_name=name,
        entry_date=entry,
        admission={},
        message=str(data.get("message") or "")[:500],
    )
    RemoteTransfer.objects.create(
        coupling=coupling, tid=tid, role=RemoteTransfer.Role.TO, transfer=request
    )
    if request.from_org.is_remote:
        ask_from_side(request)


def _receive_decision_above(coupling: Coupling, data: dict) -> None:
    """Der bisherige Verein auf einer anderen Instanz hat entschieden."""
    from members.workflows import complete_remote_transfer

    rt = RemoteTransfer.objects.filter(
        coupling=coupling, tid=str(data.get("tid") or ""), role=RemoteTransfer.Role.FROM
    ).first()
    if rt is None or rt.status != RemoteTransfer.Status.PENDING or rt.transfer is None:
        return
    decision = str(data.get("decision") or "reject")
    rt.status = (
        RemoteTransfer.Status.REJECTED if decision == "reject" else RemoteTransfer.Status.ACCEPTED
    )
    rt.response = str(data.get("response") or "")[:500]
    rt.decided_at = timezone.now()
    rt.save(update_fields=["status", "response", "decided_at"])
    complete_remote_transfer(rt.transfer, decision, rt.response)


# --- unten (Verein) ---


def request_transfer(coupling: Coupling, data: dict, user) -> RemoteTransfer:
    """Wechselanfrage über den fernen Dachverband stellen (neuer Verein unten)."""
    from members.models import MemberType

    from . import services

    if coupling.direction != Coupling.Direction.PARENT or coupling.state != Coupling.State.ACTIVE:
        raise ValidationError("Die Kopplung nach oben ist nicht aktiv.")
    if coupling.level("members") != "b":
        raise ValidationError("Wechselanfragen brauchen die namentliche Meldung.")
    club = coupling.local_unit
    member_type = MemberType.objects.filter(organization=club, pk=data.get("member_type")).first()
    if member_type is None or not member_type.active:
        raise ValidationError("Bitte eine aktive Mitgliedsart wählen.")
    birth = _date(data.get("birth_date"))
    entry = _date(data.get("entry_date"))
    last = str(data.get("last_name") or "").strip()[:100]
    first = str(data.get("first_name") or "").strip()[:100]
    if not (birth and entry and last and first):
        raise ValidationError("Bitte Name, Vorname, Geburtsdatum und Eintritt angeben.")
    admission = {
        "last_name": last,
        "first_name": first,
        "birth_date": birth.isoformat(),
        "member_type": member_type.pk,
        "member_type_name": member_type.name,
        "entry_date": entry.isoformat(),
        "message": str(data.get("message") or "")[:500],
    }
    with transaction.atomic():
        rt = RemoteTransfer.objects.create(
            coupling=coupling, role=RemoteTransfer.Role.TO, data=admission, created_by=user
        )
        services.enqueue(
            coupling,
            "transfer.request",
            {
                "tid": str(rt.tid),
                "last_name": last,
                "first_name": first,
                "birth_date": birth.isoformat(),
                "number": None,
                "member_type_name": member_type.name,
                "entry_date": entry.isoformat(),
                "message": admission["message"],
            },
            persons=1,
        )
        services._audit(coupling, user, f"Wechselanfrage für {first} {last} gestellt")
    return rt


def _receive_request_below(coupling: Coupling, data: dict) -> None:
    """Der Dachverband fragt: Darf eine eigene aktive Person wechseln?"""
    from members.models import Membership

    from . import services

    tid = str(data.get("tid") or "")
    if RemoteTransfer.objects.filter(coupling=coupling, tid=tid).exists():
        return
    uid = str(data.get("uid") or "")
    membership = None
    if uid.startswith("m") and uid[1:].isdigit():
        membership = Membership.objects.filter(
            organization=coupling.local_unit, pk=int(uid[1:])
        ).first()
    if membership is None:
        raise ValidationError("Mitgliedschaft unbekannt.")
    RemoteTransfer.objects.create(
        coupling=coupling,
        tid=tid,
        role=RemoteTransfer.Role.FROM,
        membership=membership,
        data={
            "to_unit": str(data.get("to_unit") or "")[:200],
            "entry_date": str(_date(data.get("entry_date")) or ""),
            "member_type_name": str(data.get("member_type_name") or "")[:100],
            "message": str(data.get("message") or "")[:500],
        },
    )
    services._audit(
        coupling, None, f"Wechselanfrage für {membership.person} von {data.get('to_unit')}"
    )


def decide(rt: RemoteTransfer, decision: str, user, new_type=None, response: str = ""):
    """Unten: Wechselanfrage des Dachverbands entscheiden (bisheriger Verein)."""
    from members import workflows
    from members.models import ExitReason, TransferRequest

    from . import services

    if rt.role != RemoteTransfer.Role.FROM or rt.status != RemoteTransfer.Status.PENDING:
        raise ValidationError("Die Anfrage ist bereits erledigt.")
    coupling = rt.coupling
    if not coupling.is_open:
        raise ValidationError("Die Kopplung ist nicht aktiv.")
    entry = _date(rt.data.get("entry_date")) or timezone.localdate()
    membership = rt.membership
    with transaction.atomic():
        if decision == TransferRequest.Decision.EXIT:
            workflows.exit_membership(
                membership, entry - datetime.timedelta(days=1), ExitReason.TRANSFER
            )
        elif decision == TransferRequest.Decision.CHANGE_TYPE:
            if (
                new_type is None
                or new_type.active
                or new_type.organization_id != membership.organization_id
            ):
                raise ValidationError("Bitte eine nicht aktive Art wählen.")
            workflows.change_type(membership, new_type, entry)
        elif decision != "reject":
            raise ValidationError("Unbekannte Entscheidung.")
        rt.status = (
            RemoteTransfer.Status.REJECTED
            if decision == "reject"
            else RemoteTransfer.Status.ACCEPTED
        )
        rt.response = response[:500]
        rt.decided_at = timezone.now()
        rt.save(update_fields=["status", "response", "decided_at"])
    # Erst den neuen Stand, dann die Entscheidung: Oben ist der Austritt dann bekannt
    services.sync(Coupling.objects.get(pk=coupling.pk))
    with transaction.atomic():
        services.enqueue(
            coupling,
            "transfer.decision",
            {"tid": str(rt.tid), "decision": decision, "response": rt.response},
        )
        services._audit(coupling, user, f"Wechselanfrage für {membership.person} entschieden")
    return rt


def _receive_decision_below(coupling: Coupling, data: dict) -> None:
    """Der Dachverband meldet die Entscheidung zu einer eigenen Wechselanfrage."""
    from members import services as member_services
    from members.models import MemberType

    rt = RemoteTransfer.objects.filter(
        coupling=coupling, tid=str(data.get("tid") or ""), role=RemoteTransfer.Role.TO
    ).first()
    if rt is None or rt.status != RemoteTransfer.Status.PENDING:
        return
    rt.response = str(data.get("response") or "")[:500]
    rt.decided_at = timezone.now()
    if data.get("status") != "accepted":
        rt.status = RemoteTransfer.Status.REJECTED
        rt.save(update_fields=["status", "response", "decided_at"])
        return
    club = coupling.local_unit
    admission = rt.data or {}
    token = skip_remote_check.set(True)
    try:
        with transaction.atomic():
            member_type = MemberType.objects.get(organization=club, pk=admission["member_type"])
            membership = member_services.admit(
                club,
                {
                    "member_type": member_type,
                    "entry_date": _date(admission["entry_date"]),
                    "last_name": admission["last_name"],
                    "first_name": admission["first_name"],
                    "birth_date": _date(admission["birth_date"]),
                },
            )
    except Exception as exc:  # noqa: BLE001 - als Fehler an der Anfrage zeigen
        rt.status = RemoteTransfer.Status.FAILED
        rt.response = (f"Aufnahme nicht möglich: {exc}")[:500]
        rt.save(update_fields=["status", "response", "decided_at"])
        return
    finally:
        skip_remote_check.reset(token)
    rt.membership = membership
    rt.status = RemoteTransfer.Status.ACCEPTED
    rt.save(update_fields=["membership", "status", "response", "decided_at"])
    number = data.get("number")
    if number:
        try:
            RemoteMember.objects.update_or_create(
                coupling=coupling,
                uid=f"m{membership.pk}",
                defaults={"membership": membership, "number": int(number)},
            )
        except (TypeError, ValueError):
            pass


def _receive_cancel_below(coupling: Coupling, data: dict) -> None:
    rt = RemoteTransfer.objects.filter(
        coupling=coupling, tid=str(data.get("tid") or ""), role=RemoteTransfer.Role.FROM
    ).first()
    if rt is not None and rt.status == RemoteTransfer.Status.PENDING:
        rt.status = RemoteTransfer.Status.CANCELLED
        rt.decided_at = timezone.now()
        rt.save(update_fields=["status", "decided_at"])


def receive(coupling: Coupling, kind: str, data: dict) -> None:
    try:
        uuid.UUID(str(data.get("tid")))
    except ValueError as exc:
        raise ValidationError("Ungültige Wechselanfrage.") from exc
    below = coupling.direction == Coupling.Direction.PARENT
    if kind == "transfer.request":
        (_receive_request_below if below else _receive_request_above)(coupling, data)
    elif kind == "transfer.decision":
        (_receive_decision_below if below else _receive_decision_above)(coupling, data)
    elif kind == "transfer.cancel" and below:
        _receive_cancel_below(coupling, data)
    else:
        raise ValidationError("Unpassende Wechselmeldung.")


def transfer_data(rt: RemoteTransfer) -> dict:
    data = rt.data or {}
    person = rt.membership.person if rt.membership_id else None
    return {
        "id": rt.pk,
        "role": rt.role,
        "status": rt.status,
        "status_label": rt.get_status_display(),
        "name": (
            f"{person.first_name} {person.last_name}"
            if person
            else f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
        ),
        "to_unit": data.get("to_unit", ""),
        "entry_date": data.get("entry_date"),
        "member_type_name": data.get("member_type_name", ""),
        "message": data.get("message", ""),
        "response": rt.response,
        "created_at": rt.created_at,
        "decided_at": rt.decided_at,
        "member_id": rt.membership_id,
    }
