"""Paket „Mitglieder der ausgegliederten Untereinheit“ (Verbund, Schritt 8d, Weg A).

Nach einer Ausgliederung mit „Mitglieder bleiben Vereinsmitglieder“ pflegt die Untereinheit
Stammdaten und Kontakt ihrer Mitglieder auf ihrer eigenen Instanz. Sie schickt dem Verein
den Stand; der Verein ordnet ihn über die Kennungen aus dem Export seinen bestehenden
Mitgliedschaften zu, nie über Namen. Diese Mitgliedschaften sind beim Verein „fern geführt“
(``Membership.managed_by``): Zeiträume, Mitgliedsart und Beitrag bleiben Sache des Vereins,
Name, Geburtsdatum und Kontakt kommen von der Untereinheit. Korrekturen schlägt der Verein
nur vor (wie der Dachverband, Paket „members“).

- Neue Mitglieder der Untereinheit werden beim Verein neue, fern geführte Mitgliedschaften,
  nach der Prüfung „nirgends aktiv“. Gibt es schon eine Person mit gleichem Namen und
  Geburtsdatum, entsteht ein Klärfall; zusammengeführt wird nie automatisch.
- Wer die Untereinheit verlässt (oder nicht mehr im Stand steht), bleibt Vereinsmitglied:
  Die Zuordnung zur Untereinheit endet, und der Verein pflegt die Person wieder selbst.
"""

from __future__ import annotations

import datetime

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Coupling, RemoteMember
from .packets import UP, Packet, register

KEY = "unit_members"
LIMIT = 20000
PERSON_FIELDS = ("last_name", "first_name", "birth_date", "gender")
CONTACT = ("email", "phone", "street", "postal_code", "city", "country")
LIMITS = {"email": 254, "phone": 50, "street": 200, "postal_code": 10, "city": 100}


def _date(value):
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


# --- unten (ausgegliederte Einheit): Stand bauen ---


def build(coupling: Coupling, level) -> dict:
    from core.tenancy import tenant_context
    from members import services
    from members.models import Membership

    unit = coupling.local_unit
    today = timezone.localdate()
    rows = []
    with tenant_context(unit.pk):
        memberships = (
            Membership.objects.filter(organization=unit, purged_at__isnull=True)
            .select_related("person")
            .prefetch_related("periods", "type_assignments__member_type", "person__contacts")
            .order_by("pk")
        )
        for m in memberships[:LIMIT]:
            current = m.current_period(today) is not None
            if not current and not m.origin_ref:
                continue  # Frühere eigene Mitglieder gehen den Verein nichts an
            person = m.person
            contact = services.contact_for(person, unit)
            assignment = m.current_type(today) if current else None
            entries = sorted(p.entry_date for p in m.periods.all())
            rows.append(
                {
                    "uid": f"m{m.pk}",
                    "origin": m.origin_ref,
                    "current": current,
                    "last_name": person.last_name,
                    "first_name": person.first_name,
                    "birth_date": person.birth_date.isoformat(),
                    "gender": person.gender,
                    "type": assignment.member_type.name if assignment else "",
                    "entry": entries[-1].isoformat() if entries else None,
                    "contact": {f: getattr(contact, f, "") or "" for f in CONTACT}
                    if contact
                    else {},
                }
            )
    return {"rows": rows}


def persons(data) -> int:
    return len(data.get("rows") or [])


# --- oben (Verein): Stand übernehmen ---


def _spin(coupling):
    from .models import SpinOff

    return SpinOff.objects.filter(
        coupling=coupling, way=SpinOff.Way.KEEP, state=SpinOff.State.DONE
    ).first()


def _clean(row) -> dict | None:
    if not isinstance(row, dict):
        return None
    uid = str(row.get("uid") or "")[:40]
    last = str(row.get("last_name") or "").strip()[:100]
    first = str(row.get("first_name") or "").strip()[:100]
    birth = _date(row.get("birth_date"))
    if not uid.startswith("m") or not uid[1:].isdigit() or not last or not first or not birth:
        return None
    origin = str(row.get("origin") or "")
    contact = row.get("contact") if isinstance(row.get("contact"), dict) else {}
    return {
        "uid": uid,
        "origin": int(origin) if origin.isdigit() else None,
        "current": bool(row.get("current")),
        "last_name": last,
        "first_name": first,
        "birth_date": birth,
        "gender": str(row.get("gender") or "")[:10],
        "type": str(row.get("type") or "")[:100],
        "entry": _date(row.get("entry")),
        "contact": {
            f: str(contact.get(f) or "").strip()[: LIMITS.get(f, 100)]
            for f in CONTACT
            if f in contact
        },
    }


def apply(coupling: Coupling, data: dict) -> None:
    from core.tenancy import unit_context

    placeholder = coupling.remote_unit
    club = placeholder.organization
    if club is None:
        return
    with unit_context(club.pk):
        if _spin(coupling) is None:
            return  # Nur nach einer Ausgliederung mit Weg A
        rows = [
            r
            for r in map(_clean, (data.get("rows") or [])[:LIMIT] if data.get("level") else [])
            if r
        ]
        apply_rows(coupling, club, rows)


def apply_rows(coupling: Coupling, club, rows: list[dict]) -> None:
    from changes.tracking import suppress

    seen, linked = set(), set()
    with suppress():
        for row in rows:
            seen.add(row["uid"])
            rm = RemoteMember.objects.filter(coupling=coupling, uid=row["uid"]).first()
            if rm is not None and rm.status == RemoteMember.Status.UNCLEAR:
                rm.data = {**(rm.data or {}), "row": _json(row)}
                rm.save(update_fields=["data", "updated_at"])
                continue
            membership = _linked(coupling, club, row, rm)
            if membership is None:
                if row["current"]:
                    _new(coupling, club, row)
                continue
            if not row["current"]:
                _release(coupling, membership, _rm(coupling, row), "hat die Untereinheit verlassen")
                continue
            linked.add(membership.pk)
            _update(club, membership, row)
        # Offene Klärfälle, die nicht mehr im Stand stehen, erledigen sich
        RemoteMember.objects.filter(coupling=coupling, status=RemoteMember.Status.UNCLEAR).exclude(
            uid__in=seen
        ).delete()
        # Fern geführt, aber nicht (mehr) im Stand: der Verein pflegt sie wieder selbst
        for membership in club.memberships.filter(managed_by=coupling).exclude(pk__in=linked):
            if membership.pk in _new_ids(coupling, seen):
                continue
            rm = RemoteMember.objects.filter(coupling=coupling, membership=membership).first()
            _release(coupling, membership, rm, "steht nicht mehr im Stand")


def _rm(coupling, row):
    return RemoteMember.objects.filter(coupling=coupling, uid=row["uid"]).first()


def _new_ids(coupling, seen) -> set[int]:
    """In diesem Durchgang neu angelegte Mitgliedschaften (stehen im Stand)."""
    return set(
        RemoteMember.objects.filter(
            coupling=coupling, uid__in=seen, status=RemoteMember.Status.ACTIVE
        ).values_list("membership_id", flat=True)
    )


def _json(row: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}


def _linked(coupling, club, row, rm):
    from members.models import Membership

    if rm is not None and rm.membership_id:
        m = Membership.objects.filter(pk=rm.membership_id, organization=club).first()
        if m is not None and m.managed_by_id == coupling.pk:
            return m
        return None
    if row["origin"] is None:
        return None
    m = Membership.objects.filter(pk=row["origin"], organization=club, managed_by=coupling).first()
    if m is None:
        return None
    RemoteMember.objects.update_or_create(
        coupling=coupling,
        uid=row["uid"],
        defaults={"membership": m, "status": RemoteMember.Status.ACTIVE, "data": {}},
    )
    return m


def _update(club, membership, row) -> None:
    from audit.log import diff, record, snapshot
    from members import services

    person = membership.person
    before = snapshot(person)
    genders = {"", *(c for c, _ in person._meta.get_field("gender").choices)}
    for field in PERSON_FIELDS:
        value = row[field]
        if field == "gender" and value not in genders:
            continue  # unbekannte Werte nicht übernehmen
        if value != getattr(person, field):
            setattr(person, field, value)
    changes = diff(before, snapshot(person))
    if changes:
        person.save()
    if row["contact"]:
        old = services.contact_for(person, club)
        old_data = snapshot(old) if old else {}
        new = services.save_contact(person, club, row["contact"])
        changes.update(diff(old_data, snapshot(new)))
    changes.pop("Verbandsbereich", None)
    changes.pop("person", None)
    if changes:
        changes["geändert durch"] = [None, f"{membership.managed_by.remote_unit.name} (Verbund)"]
        record(club, None, "update", membership, changes, person=person)


def _release(coupling, membership, rm, why: str) -> None:
    """Zuordnung zur fernen Untereinheit endet; der Verein pflegt die Person wieder selbst."""
    from audit.log import record
    from members.models import DepartmentMembership

    today = timezone.localdate()
    for link in DepartmentMembership.objects.filter(
        membership=membership, department_id=coupling.remote_unit_id
    ).filter(valid_until__isnull=True):
        link.valid_until = max(today, link.valid_from)
        link.save(update_fields=["valid_until"])
    membership.managed_by = None
    membership.save(update_fields=["managed_by"])
    if rm is not None:
        rm.status = RemoteMember.Status.WITHDRAWN
        rm.save(update_fields=["status", "updated_at"])
    record(
        membership.organization,
        None,
        "update",
        membership,
        {"fern geführt": [coupling.remote_unit.name, f"nein ({why})"]},
        person=membership.person,
    )


def _candidates(club, row) -> list[int]:
    from members import services

    found = services.persons_matching(
        services.scope_for(club).pk,
        row["last_name"],
        row["first_name"],
        row["birth_date"],
        limit=5,
    )
    return [p.pk for p in found]


def _new(coupling, club, row, person=None) -> None:
    """Neues Mitglied der Untereinheit: neue, fern geführte Mitgliedschaft im Verein."""
    if person is None:
        candidates = _candidates(club, row)
        if candidates:
            RemoteMember.objects.update_or_create(
                coupling=coupling,
                uid=row["uid"],
                defaults={
                    "membership": None,
                    "status": RemoteMember.Status.UNCLEAR,
                    "data": {"row": _json(row), "candidates": candidates},
                },
            )
            return
    from members import services
    from members.models import Membership, MemberType

    if person is not None:
        existing = Membership.objects.filter(organization=club, person=person).first()
        if existing is not None:
            _adopt(coupling, existing, row)
            return
    types = MemberType.objects.filter(organization=club, is_archived=False)
    member_type = types.filter(name__iexact=row["type"]).first() if row["type"] else None
    member_type = member_type or types.filter(active=True).order_by("sort_order", "pk").first()
    if member_type is None:
        return
    data = {
        "member_type": member_type,
        "entry_date": row["entry"] or timezone.localdate(),
        "person": person,
        "last_name": row["last_name"],
        "first_name": row["first_name"],
        "birth_date": row["birth_date"],
        "gender": row["gender"],
        "departments": [coupling.remote_unit],
        **row["contact"],
    }
    try:
        membership = services.admit(club, data)
    except ValidationError as exc:
        RemoteMember.objects.update_or_create(
            coupling=coupling,
            uid=row["uid"],
            defaults={
                "membership": None,
                "status": RemoteMember.Status.UNCLEAR,
                "data": {
                    "row": _json(row),
                    "candidates": [],
                    "active_elsewhere": "; ".join(exc.messages)[:200],
                },
            },
        )
        return
    membership.managed_by = coupling
    membership.save(update_fields=["managed_by"])
    RemoteMember.objects.update_or_create(
        coupling=coupling,
        uid=row["uid"],
        defaults={"membership": membership, "status": RemoteMember.Status.ACTIVE, "data": {}},
    )


def _adopt(coupling, membership, row) -> None:
    """Schon Vereinsmitglied: der Untereinheit zuordnen und fern führen."""
    from members.models import DepartmentMembership

    if not DepartmentMembership.objects.filter(
        membership=membership, department_id=coupling.remote_unit_id, valid_until__isnull=True
    ).exists():
        DepartmentMembership.objects.create(
            organization=membership.organization,
            membership=membership,
            department_id=coupling.remote_unit_id,
            valid_from=timezone.localdate(),
        )
    membership.managed_by = coupling
    membership.save(update_fields=["managed_by"])
    RemoteMember.objects.update_or_create(
        coupling=coupling,
        uid=row["uid"],
        defaults={"membership": membership, "status": RemoteMember.Status.ACTIVE, "data": {}},
    )
    _update(membership.organization, membership, row)


def resolve(rm: RemoteMember, person_id: int | None) -> RemoteMember:
    """Klärfall entscheiden: ``person_id`` = dieselbe Person, None = andere Person."""
    from changes.tracking import suppress
    from core.tenancy import unit_context
    from members import services
    from members.models import Person

    if rm.status != RemoteMember.Status.UNCLEAR:
        raise ValidationError("Kein offener Klärfall.")
    row = _clean({**((rm.data or {}).get("row") or {}), "uid": rm.uid})
    if row is None:
        raise ValidationError("Die gemeldeten Angaben sind unvollständig.")
    coupling = rm.coupling
    club = coupling.remote_unit.organization
    with unit_context(club.pk), suppress():
        if person_id is not None:
            if person_id not in (rm.data or {}).get("candidates", []):
                raise ValidationError("Diese Person steht nicht zur Auswahl.")
            person = Person.objects.get(pk=person_id, scope=services.scope_for(club))
        else:
            # „Andere Person“: trotz gleichem Namen eine neue Person anlegen
            person = Person.objects.create(
                scope=services.scope_for(club),
                last_name=row["last_name"],
                first_name=row["first_name"],
                birth_date=row["birth_date"],
            )
        _new(coupling, club, row, person=person)
    rm.refresh_from_db()
    return rm


register(
    Packet(
        KEY,
        "Mitglieder der ausgegliederten Untereinheit (Name, Geburtsdatum, Kontakt; "
        "nur wenn sie Vereinsmitglieder bleiben)",
        (UP,),
        personal="ja: Stammdaten und Kontakt der Mitglieder, die zugleich Vereinsmitglieder sind",
        default="on",
        build=build,
        apply=apply,
        persons=persons,
        only_club=True,
    )
)
