"""Namentliche Mitgliedermeldung im Verbund (Paket „members“, Stufe B; P4-B, P5, P14).

Unten (Verein) baut der Stand je gemeldeter Mitgliedschaft nur das Minimum:
Name, Vorname, Geburtsdatum, Verbandsnummer, gemeldete Mitgliedsarten mit
Zeiträumen und Ein-/Austritte (Austrittsgrund nur „Wechsel“ oder „sonstiges“).
Nie Anschrift, E-Mail, Telefon, Bankdaten, Fotos, Zusatzfelder, Rollen, Züge.

Oben (Dachverband) werden daraus Mitgliedschaften im Platzhalter des Vereins.
So gelten Verbandsnummer, „nur eine aktive Mitgliedschaft“, Mitgliedsdauer und
Jubiläen wie bei Vereinen auf derselben Instanz. Ist eine Person schon bekannt
(gleicher Name und Geburtsdatum, aber keine Verbandsnummer), entsteht ein
Klärfall, den der Dachverband entscheidet. Fällt jemand aus der Meldung
(Widerspruch, Art ohne Meldung, Freigabe entzogen) oder löscht der Verein nach
Ablauf der Löschfrist, kürzt der Dachverband auf das Minimum.
"""

from __future__ import annotations

import datetime

from django.utils import timezone
from django.utils.translation import gettext

from .models import Coupling, RemoteMember, RemoteState

LIMIT = 20000
NOTE = "nicht mehr gemeldet (Verbund)"


def _date(value):
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


# --- unten: Stand bauen ---


def build_rows(coupling: Coupling) -> list[dict]:
    from core.tenancy import tenant_context
    from members.models import ExitReason, Membership

    club = coupling.local_unit
    numbers = dict(
        RemoteMember.objects.filter(coupling=coupling, number__isnull=False).values_list(
            "uid", "number"
        )
    )
    rows = []
    with tenant_context(club.pk):
        memberships = (
            Membership.objects.filter(organization=club)
            .select_related("person")
            .prefetch_related("periods", "type_assignments__member_type")
            .order_by("pk")
        )
        for m in memberships[:LIMIT]:
            types = [
                {
                    "name": ta.member_type.name,
                    "active": ta.member_type.active,
                    "from": ta.valid_from.isoformat(),
                    "until": ta.valid_until.isoformat() if ta.valid_until else None,
                }
                for ta in sorted(m.type_assignments.all(), key=lambda t: t.valid_from)
                if ta.member_type.reported
            ]
            if not types:
                continue
            uid = f"m{m.pk}"
            person = m.person
            rows.append(
                {
                    "uid": uid,
                    "last_name": person.last_name,
                    "first_name": person.first_name,
                    "birth_date": person.birth_date.isoformat(),
                    "number": numbers.get(uid),
                    "purged": bool(m.purged_at),
                    "periods": [
                        {
                            "entry": p.entry_date.isoformat(),
                            "exit": p.exit_date.isoformat() if p.exit_date else None,
                            "transfer": p.exit_reason == ExitReason.TRANSFER,
                        }
                        for p in sorted(m.periods.all(), key=lambda p: p.entry_date)
                    ],
                    "types": types,
                }
            )
    return rows


def number_for(membership) -> RemoteMember | None:
    """Verbandsnummer einer eigenen Mitgliedschaft, die der ferne Dachverband vergeben hat."""
    return (
        RemoteMember.objects.filter(
            coupling__local_unit_id=membership.organization_id,
            coupling__direction=Coupling.Direction.PARENT,
            uid=f"m{membership.pk}",
        )
        .select_related("coupling__remote_unit")
        .order_by("-coupling__created_at")
        .first()
    )


def receive_numbers(coupling: Coupling, data: dict) -> None:
    from members.models import Membership

    if coupling.direction != Coupling.Direction.PARENT:
        return
    own = set(
        Membership.objects.filter(organization=coupling.local_unit).values_list("pk", flat=True)
    )
    for uid, number in (data.get("numbers") or {}).items():
        uid = str(uid)[:40]
        if not uid.startswith("m") or not uid[1:].isdigit() or int(uid[1:]) not in own:
            continue
        try:
            number = int(number)
        except (TypeError, ValueError):
            continue
        RemoteMember.objects.update_or_create(
            coupling=coupling,
            uid=uid,
            defaults={"membership_id": int(uid[1:]), "number": number},
        )


# --- oben: Stand übernehmen ---


def _clean_row(row) -> dict | None:
    if not isinstance(row, dict):
        return None
    birth = _date(row.get("birth_date"))
    uid = str(row.get("uid") or "")[:40]
    last = str(row.get("last_name") or "").strip()[:100]
    first = str(row.get("first_name") or "").strip()[:100]
    if not (uid and birth and last):
        return None
    periods = []
    for p in (row.get("periods") or [])[:50]:
        entry = _date(p.get("entry")) if isinstance(p, dict) else None
        if entry:
            periods.append(
                {"entry": entry, "exit": _date(p.get("exit")), "transfer": bool(p.get("transfer"))}
            )
    types = []
    for t in (row.get("types") or [])[:50]:
        start = _date(t.get("from")) if isinstance(t, dict) else None
        if start:
            types.append(
                {
                    "name": str(t.get("name") or "gemeldet")[:100],
                    "active": bool(t.get("active")),
                    "from": start,
                    "until": _date(t.get("until")),
                }
            )
    if not periods or not types:
        return None
    try:
        number = int(row["number"]) if row.get("number") is not None else None
    except (TypeError, ValueError):
        number = None
    return {
        "uid": uid,
        "last_name": last,
        "first_name": first,
        "birth_date": birth,
        "number": number,
        "purged": bool(row.get("purged")),
        "periods": periods,
        "types": types,
    }


def _json_row(row: dict) -> dict:
    out = dict(row)
    out["birth_date"] = row["birth_date"].isoformat()
    out["periods"] = [
        {**p, "entry": p["entry"].isoformat(), "exit": p["exit"] and p["exit"].isoformat()}
        for p in row["periods"]
    ]
    out["types"] = [
        {**t, "from": t["from"].isoformat(), "until": t["until"] and t["until"].isoformat()}
        for t in row["types"]
    ]
    return out


def _row_from_json(data: dict) -> dict | None:
    return _clean_row(data)


def apply_rows(coupling: Coupling, rows: list) -> None:
    """Stand der namentlichen Meldung beim Dachverband übernehmen."""
    from changes.tracking import suppress

    placeholder = coupling.remote_unit
    federation = placeholder.parent
    known = {rm.uid: rm for rm in RemoteMember.objects.filter(coupling=coupling)}
    seen = set()
    with suppress():
        for raw in rows[:LIMIT]:
            row = _clean_row(raw)
            if row is None or row["uid"] in seen:
                continue
            seen.add(row["uid"])
            rm = known.get(row["uid"])
            if rm is not None and rm.membership_id:
                _update(rm, row)
            elif rm is not None and rm.status == RemoteMember.Status.UNCLEAR:
                rm.data = {**rm.data, "row": _json_row(row)}
                rm.save(update_fields=["data", "updated_at"])
            else:
                _import(coupling, federation, row, rm)
        relinked = set(
            RemoteMember.objects.filter(
                coupling=coupling, uid__in=seen, status=RemoteMember.Status.ACTIVE
            ).values_list("membership_id", flat=True)
        )
        for uid, rm in known.items():
            if uid in seen or rm.status == RemoteMember.Status.WITHDRAWN:
                continue
            if rm.membership_id and rm.membership_id in relinked:
                # Dieselbe Person unter neuer Kennung (z. B. nach einem Umzug des Vereins)
                rm.status = RemoteMember.Status.WITHDRAWN
                rm.membership = None
                rm.data = {}
                rm.save(update_fields=["status", "membership", "data", "updated_at"])
            else:
                withdraw(rm)
    send_numbers(coupling)


def _person_for(federation, row):
    """Vorhandene Person zur Zeile: über die Verbandsnummer, sonst None."""
    from members.models import FederationMember

    if row["number"]:
        fm = (
            FederationMember.objects.filter(scope=federation, member_number=row["number"])
            .select_related("person")
            .first()
        )
        if fm is not None:
            return fm.person
    return None


def _shared(person, placeholder) -> bool:
    """Ist die Person auch außerhalb dieses Platzhalters Mitglied (anderer Verein)?

    Ohne RLS gelesen (nur ja/nein): Mitgliedschaften anderer Vereine fehlen sonst und die
    Prüfung fiele zugunsten des Partners aus.
    """
    from core.tenancy import rls_bypass

    with rls_bypass():
        return (
            person.memberships.exclude(organization_id=placeholder.pk)
            .filter(purged_at__isnull=True)
            .exists()
        )


def _transferred(person, placeholder) -> bool:
    """Hat der Dachverband den Wechsel dieser Person zu diesem Verein bestätigt?"""
    from core.tenancy import rls_bypass
    from members.models import TransferRequest

    with rls_bypass():
        return TransferRequest.objects.filter(
            person=person, to_org_id=placeholder.pk, status=TransferRequest.Status.ACCEPTED
        ).exists()


def _candidates(federation, row):

    from members.services import persons_matching

    found = persons_matching(
        federation.pk, row["last_name"], row["first_name"], row["birth_date"], limit=5
    )
    return [p.pk for p in found]


def _import(coupling, federation, row, rm=None, person=None):
    from members.models import Person

    found = None
    if person is None:
        found = _person_for(federation, row)
        # Eine Verbandsnummer allein beweist nicht, dass der Partner für diese Person
        # spricht: Ist sie schon Mitglied eines anderen Vereins, entscheidet der
        # Dachverband im Klärfall (Gesamtaudit 01.11., GA-S02).
        if found is not None and (
            not _shared(found, coupling.remote_unit) or _transferred(found, coupling.remote_unit)
        ):
            person = found
    if person is None:
        candidates = _candidates(federation, row)
        if found is not None and found.pk not in candidates:
            candidates = [found.pk, *candidates][:5]
        if candidates:
            rm = rm or RemoteMember(coupling=coupling, uid=row["uid"])
            rm.status = RemoteMember.Status.UNCLEAR
            rm.data = {"row": _json_row(row), "candidates": candidates}
            rm.save()
            return rm
        person = Person.objects.create(
            scope=federation,
            last_name=row["last_name"],
            first_name=row["first_name"],
            birth_date=row["birth_date"],
        )
    membership = _membership(coupling.remote_unit, federation, person)
    rm = rm or RemoteMember(coupling=coupling, uid=row["uid"])
    rm.membership = membership
    rm.status = RemoteMember.Status.ACTIVE
    rm.data = {}
    rm.save()
    _update(rm, row)
    return rm


def _membership(placeholder, federation, person):
    from members.models import Membership

    membership, _ = Membership.objects.get_or_create(
        organization=placeholder, person=person, defaults={"scope": federation}
    )
    if membership.purged_at:
        membership.purged_at = None
        membership.save(update_fields=["purged_at", "updated_at"])
        from members import loeschliste

        loeschliste.note_readmitted(membership)
    return membership


def _update(rm: RemoteMember, row: dict) -> None:
    from members import services as member_services
    from members import workflows
    from members.models import ExitReason, MembershipPeriod, MemberType, MemberTypeAssignment

    membership = rm.membership
    placeholder = membership.organization
    person = membership.person
    # Berichtigung (Art. 16/19): Name und Geburtsdatum kommen vom Verein. Ist die Person
    # auch in einem anderen Verein, gibt der Dachverband die Änderung frei (GA-S02).
    changed = [f for f in ("last_name", "first_name", "birth_date") if getattr(person, f) != row[f]]
    data = dict(rm.data or {})
    if changed and _shared(person, placeholder):
        data[CORRECTION] = {f: row[f].isoformat() if f == "birth_date" else row[f] for f in changed}
    else:
        data.pop(CORRECTION, None)
        if changed:
            for f in changed:
                setattr(person, f, row[f])
            person.save(update_fields=[*changed, "updated_at"])
    if data != (rm.data or {}):
        rm.data = data
        rm.save(update_fields=["data", "updated_at"])
    membership.periods.all().delete()
    membership.type_assignments.all().delete()
    for p in row["periods"]:
        reason = ""
        if p["exit"]:
            reason = ExitReason.TRANSFER if p["transfer"] else ExitReason.EXIT
        MembershipPeriod.objects.create(
            organization=placeholder,
            membership=membership,
            entry_date=p["entry"],
            exit_date=p["exit"],
            exit_reason=reason,
        )
    for t in row["types"]:
        member_type, _ = MemberType.objects.get_or_create(
            organization=placeholder,
            name=t["name"],
            defaults={"active": t["active"], "reported": True},
        )
        if member_type.active != t["active"]:
            member_type.active = t["active"]
            member_type.save(update_fields=["active"])
        MemberTypeAssignment.objects.create(
            organization=placeholder,
            membership=membership,
            member_type=member_type,
            valid_from=t["from"],
            valid_until=t["until"],
        )
    member_services.ensure_federation_member(person, placeholder)
    data = {k: v for k, v in (rm.data or {}).items() if k != "active_elsewhere"}
    today = timezone.localdate()
    current = membership.current_type(today)
    if current is not None and current.member_type.active and membership.current_period(today):
        other = member_services.active_elsewhere(person, placeholder, today)
        if other:
            data["active_elsewhere"] = other
    if row["purged"] and not membership.purged_at:
        workflows.purge_membership(membership)
    if data != (rm.data or {}) or rm.status != RemoteMember.Status.ACTIVE:
        rm.data = data
        rm.status = RemoteMember.Status.ACTIVE
        rm.save(update_fields=["data", "status", "updated_at"])


def withdraw(rm: RemoteMember) -> None:
    """Nicht mehr gemeldet: offene Zeiträume enden heute, dann nur das Minimum."""
    from members import workflows
    from members.models import ExitReason

    membership = rm.membership
    if membership is not None:
        today = timezone.localdate()
        for period in membership.periods.filter(exit_date__isnull=True):
            period.exit_date = max(today, period.entry_date)
            period.exit_reason = ExitReason.EXIT
            period.note = NOTE
            period.save()
        membership.type_assignments.filter(valid_until__isnull=True).update(valid_until=today)
        if not membership.purged_at:
            workflows.purge_membership(membership)
    rm.status = RemoteMember.Status.WITHDRAWN
    rm.data = {}
    rm.save(update_fields=["status", "data", "updated_at"])


def withdraw_all(coupling: Coupling) -> None:
    from changes.tracking import suppress

    with suppress():
        for rm in RemoteMember.objects.filter(coupling=coupling).exclude(
            status=RemoteMember.Status.WITHDRAWN
        ):
            if rm.membership_id is None:
                rm.delete()  # Klärfall ohne übernommene Daten: nichts zu behalten
            else:
                withdraw(rm)


def send_numbers(coupling: Coupling) -> None:
    """Verbandsnummern der gemeldeten Personen an den Verein schicken (wenn geändert)."""
    from members.models import FederationMember

    from . import packets, services

    mapping = {}
    for uid, person_id in RemoteMember.objects.filter(
        coupling=coupling, status=RemoteMember.Status.ACTIVE, membership__isnull=False
    ).values_list("uid", "membership__person_id"):
        mapping[uid] = person_id
    numbers = dict(
        FederationMember.objects.filter(person_id__in=mapping.values()).values_list(
            "person_id", "member_number"
        )
    )
    payload = {"numbers": {uid: numbers[pid] for uid, pid in mapping.items() if pid in numbers}}
    digest = packets.digest(payload)
    state, _ = RemoteState.objects.get_or_create(coupling=coupling, key="numbers_sent")
    if state.data.get("digest") == digest:
        return
    state.data = {"digest": digest}
    state.save()
    if payload["numbers"]:
        services.enqueue(coupling, "register.numbers", payload)


# --- oben: Klärfälle ---

# Vom Verein gemeldete Berichtigung einer Person, die auch woanders Mitglied ist
CORRECTION = "berichtigung"


def decide_correction(rm: RemoteMember, apply: bool) -> RemoteMember:
    """Gemeldete Berichtigung übernehmen (``apply``) oder verwerfen."""
    import datetime

    from django.core.exceptions import ValidationError

    from changes.tracking import suppress

    proposal = (rm.data or {}).get(CORRECTION)
    if not proposal or rm.membership_id is None:
        raise ValidationError(gettext("Keine offene Berichtigung."))
    if apply:
        person = rm.membership.person
        fields = []
        for f, value in proposal.items():
            if f not in ("last_name", "first_name", "birth_date"):
                continue
            setattr(person, f, datetime.date.fromisoformat(value) if f == "birth_date" else value)
            fields.append(f)
        with suppress():
            person.save(update_fields=[*fields, "updated_at"])
    rm.data = {k: v for k, v in (rm.data or {}).items() if k != CORRECTION}
    rm.save(update_fields=["data", "updated_at"])
    return rm


def resolve(rm: RemoteMember, person_id: int | None) -> RemoteMember:
    """Klärfall entscheiden: ``person_id`` = dieselbe Person, None = andere Person."""
    from django.core.exceptions import ValidationError

    from changes.tracking import suppress
    from members.models import Person

    if rm.status != RemoteMember.Status.UNCLEAR:
        raise ValidationError(gettext("Kein offener Klärfall."))
    row = _row_from_json((rm.data or {}).get("row") or {})
    if row is None:
        raise ValidationError(gettext("Die gemeldeten Angaben sind unvollständig."))
    coupling = rm.coupling
    federation = coupling.remote_unit.parent
    person = None
    if person_id is not None:
        if person_id not in (rm.data or {}).get("candidates", []):
            raise ValidationError(gettext("Diese Person steht nicht zur Auswahl."))
        person = Person.objects.get(pk=person_id, scope=federation)
    else:
        person = Person.objects.create(
            scope=federation,
            last_name=row["last_name"],
            first_name=row["first_name"],
            birth_date=row["birth_date"],
        )
    with suppress():
        _import(coupling, federation, row, rm, person=person)
    send_numbers(coupling)
    rm.refresh_from_db()
    return rm


# --- Abfrage „aktive Mitgliedschaft vorhanden?“ (P7) ---


def parent_coupling(club) -> Coupling | None:
    """Aktive Kopplung nach oben mit namentlicher Meldung (sonst None)."""
    coupling = (
        Coupling.objects.filter(
            local_unit=club, direction=Coupling.Direction.PARENT, state=Coupling.State.ACTIVE
        )
        .select_related("peer", "local_unit")
        .first()
    )
    if coupling is None or coupling.level("members") != "b":
        return None
    return coupling


def ask_active_elsewhere(club, person, on, membership=None) -> str | None:
    """Fragt den fernen Dachverband, ob die Person anderswo aktiv ist.

    Gibt nur den Namen der anderen Einheit zurück. Ist der Dachverband nicht
    erreichbar, blockiert das die Aufnahme nicht (jede Instanz bleibt autark);
    der Dachverband sieht einen Widerspruch dann beim nächsten Stand als Klärfall.
    """
    import logging

    from . import services, transport
    from .transfers import skip_remote_check

    if skip_remote_check.get():
        return None  # Aufnahme nach bestätigtem Wechsel
    coupling = parent_coupling(club)
    if coupling is None:
        return None
    uid = f"m{membership.pk}" if membership is not None else ""
    number = (
        RemoteMember.objects.filter(coupling=coupling, uid=uid)
        .values_list("number", flat=True)
        .first()
        if uid
        else None
    )
    try:
        answer = transport.call(
            services.keys_of(coupling.peer),
            "/api/peering/v1/query/",
            {
                "from_unit": str(club.uuid),
                "to_unit": str(coupling.remote_uuid),
                "kind": "active",
                "uid": uid,
                "number": number,
                "last_name": person.last_name,
                "first_name": person.first_name,
                "birth_date": person.birth_date.isoformat(),
                "on": on.isoformat(),
            },
        )
    except transport.PeerError as exc:
        logging.getLogger(__name__).info("Abfrage beim Dachverband nicht möglich: %s", exc)
        return None
    other = answer.get("active_in")
    return str(other)[:200] if other else None


def answer_query(coupling: Coupling, payload: dict) -> dict:
    """Oben: Anfrage eines fernen Vereins beantworten (nur den Namen der anderen Einheit)."""
    from members import services as member_services

    if coupling.direction != Coupling.Direction.CHILD or coupling.state != Coupling.State.ACTIVE:
        return {"active_in": None}
    if coupling.remote_level("members") != "b" or payload.get("kind") != "active":
        return {"active_in": None}
    placeholder = coupling.remote_unit
    federation = placeholder.parent
    on = _date(payload.get("on")) or timezone.localdate()
    person = None
    rm = RemoteMember.objects.filter(
        coupling=coupling, uid=str(payload.get("uid") or "")[:40]
    ).first()
    if rm is not None and rm.membership_id:
        person = rm.membership.person
    if person is None and payload.get("number"):
        person = _person_for(federation, {"number": payload.get("number")})
    if person is None:
        birth = _date(payload.get("birth_date"))
        matches = member_services.persons_matching(
            federation.pk,
            str(payload.get("last_name") or ""),
            str(payload.get("first_name") or ""),
            birth,
            limit=2,
        )
        person = matches[0] if len(matches) == 1 else None
    if person is None:
        return {"active_in": None}
    return {"active_in": member_services.active_elsewhere(person, placeholder, on)}


# --- Korrekturvorschlag von oben (P6) ---

SUGGEST_FIELDS = ("last_name", "first_name", "birth_date")


def suggest(rm: RemoteMember, values: dict, message: str, user) -> None:
    """Oben: Korrektur zu einer gemeldeten Person vorschlagen. Ändern darf nur der Verein."""
    from django.core.exceptions import ValidationError

    from . import services

    if rm.status != RemoteMember.Status.ACTIVE or rm.membership is None:
        raise ValidationError(gettext("Die Person ist nicht mehr gemeldet."))
    if not rm.coupling.is_open:
        raise ValidationError(gettext("Die Kopplung ist nicht aktiv."))
    person = rm.membership.person
    data, previous = {}, {}
    for field in SUGGEST_FIELDS:
        if field not in values:
            continue
        new = values[field]
        old = getattr(person, field)
        if new != old:
            data[field] = new.isoformat() if hasattr(new, "isoformat") else str(new)
            previous[field] = old.isoformat() if hasattr(old, "isoformat") else str(old)
    if not data:
        raise ValidationError(gettext("Keine Änderungen."))
    services.enqueue(
        rm.coupling,
        "register.suggest",
        {"uid": rm.uid, "data": data, "previous": previous, "message": message[:300]},
        persons=1,
    )
    services._audit(rm.coupling, user, f"Korrektur zu {person} vorgeschlagen")


def receive_suggestion(coupling: Coupling, data: dict) -> int:
    """Unten: Vorschlag als Änderungsmeldung anlegen; der Verein übernimmt oder lehnt ab."""
    from members.models import Membership
    from portal.models import ChangeRequest

    if coupling.direction != Coupling.Direction.PARENT:
        return 0
    uid = str(data.get("uid") or "")
    if not uid.startswith("m") or not uid[1:].isdigit():
        return 0
    membership = Membership.objects.filter(
        organization=coupling.local_unit, pk=int(uid[1:])
    ).first()
    if membership is None:
        return 0
    values = {}
    for field in SUGGEST_FIELDS:
        value = (data.get("data") or {}).get(field)
        if value is None:
            continue
        value = str(value).strip()[:100]
        if field == "birth_date" and _date(value) is None:
            continue
        if value:
            values[field] = value
    if not values:
        return 0
    previous = {
        k: str(v)[:100] for k, v in (data.get("previous") or {}).items() if k in SUGGEST_FIELDS
    }
    text = str(data.get("message") or "").strip()
    ChangeRequest.objects.create(
        organization=coupling.local_unit,
        membership=membership,
        user=None,
        data=values,
        previous=previous,
        message=f"Korrekturvorschlag von {coupling.remote_unit.name}"
        + (f": {text}" if text else "")[:400],
    )
    return 1
