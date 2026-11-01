"""Fachlogik der Meldungen: Bausteine prüfen, Bedingungen prüfen, Fassungen festhalten,
Änderungen beschreiben und den fremden Wettbewerb nachführen."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework.exceptions import ValidationError

from members.models import (
    DepartmentMembership,
    Membership,
    MembershipPeriod,
    MemberTypeAssignment,
)
from organizations.models import Department

from .models import Call, CallBlock, Entry, EntryAnswer, EntryPerson, EntryTeam, EntryVersion

# Angaben je Person, die eine Ausschreibung verlangen kann (außer dem Namen)
PERSON_FIELDS = {
    "birth_date": "Geburtsdatum",
    "birth_year": "Geburtsjahr",
    "member_number": "Mitgliedsnummer",
    "entry_date": "Eintrittsdatum",
    "unit": "Untereinheit",
    "member_type": "Mitgliedsart",
}
FIELD_PREFIX = "feld:"  # Zusatzfeld, z. B. „feld:schuetzenpass“
MAX_BLOCKS = 20
MAX_PERSONS = 300
MAX_TEAMS = 50


def field_label(org, key: str) -> str:
    if key in PERSON_FIELDS:
        label = PERSON_FIELDS[key]
        if key == "unit":
            label = org.department_label or label
        return label
    if key.startswith(FIELD_PREFIX):
        from customfields.models import FieldDefinition

        d = FieldDefinition.objects.filter(
            organization=org, key=key[len(FIELD_PREFIX) :], repeatable=False
        ).first()
        return d.label if d else key[len(FIELD_PREFIX) :]
    return key


def clean_person_fields(org, value) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError({"person_fields": gettext("Ungültige Angabe.")})
    from customfields.models import FieldDefinition

    custom = set(
        FieldDefinition.objects.filter(
            organization=org, repeatable=False, is_archived=False
        ).values_list("key", flat=True)
    )
    out = []
    for key in value:
        key = str(key)
        ok = key in PERSON_FIELDS or (
            key.startswith(FIELD_PREFIX) and key[len(FIELD_PREFIX) :] in custom
        )
        if not ok:
            raise ValidationError(
                {"person_fields": gettext("Unbekannte Angabe „{key}“.").format(key=key)}
            )
        if key not in out:
            out.append(key)
    return out


def _int_or_none(value, name: str, low: int = 0, high: int = 10000) -> int | None:
    if value in (None, ""):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValidationError({name: gettext("Bitte eine ganze Zahl angeben.")}) from None
    if n < low or n > high:
        raise ValidationError(
            {
                name: gettext("Bitte eine Zahl von {low} bis {high} angeben.").format(
                    low=low, high=high
                )
            }
        )
    return n


def _positions(value) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > 10:
        raise ValidationError({"positions": gettext("Höchstens 10 Aufgaben.")})
    return [str(v).strip()[:100] for v in value if str(v).strip()]


def clean_conditions(org, value) -> dict:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValidationError({"conditions": gettext("Ungültige Angabe.")})
    from members.models import MemberType

    out: dict = {
        "active": bool(value.get("active", False)),
        "one_team": bool(value.get("one_team", False)),
        "guests": bool(value.get("guests", False)),
    }
    for key in ("min_age", "max_age"):
        n = _int_or_none(value.get(key), key, 0, 120)
        if n is not None:
            out[key] = n
    if out.get("min_age") is not None and out.get("max_age") is not None:
        if out["min_age"] > out["max_age"]:
            raise ValidationError(
                {"max_age": gettext("Das Höchstalter liegt unter dem Mindestalter.")}
            )
    types = value.get("member_types") or []
    units = value.get("units") or []
    if not isinstance(types, list) or not isinstance(units, list):
        raise ValidationError({"conditions": gettext("Ungültige Angabe.")})
    known_types = set(MemberType.objects.filter(organization=org).values_list("pk", flat=True))
    known_units = set(Department.objects.filter(organization=org).values_list("pk", flat=True))
    try:
        types = [int(t) for t in types]
        units = [int(u) for u in units]
    except (TypeError, ValueError):
        raise ValidationError({"conditions": gettext("Ungültige Angabe.")}) from None
    if not set(types) <= known_types:
        raise ValidationError({"member_types": gettext("Unbekannte Mitgliedsart.")})
    if not set(units) <= known_units:
        raise ValidationError({"units": gettext("Unbekannte Untereinheit.")})
    if types:
        out["member_types"] = types
    if units:
        out["units"] = units
    return out


def clean_block_settings(kind: str, value) -> dict:
    if value in (None, ""):
        value = {}
    if not isinstance(value, dict):
        raise ValidationError({"settings": gettext("Ungültige Angabe.")})
    out: dict = {}
    if kind == CallBlock.Kind.TEAMS:
        for key in ("min_teams", "max_teams", "min_size", "max_size", "substitutes"):
            n = _int_or_none(value.get(key), key, 0, 100)
            if n is not None:
                out[key] = n
        if out.get("max_teams") is not None and out["max_teams"] < out.get("min_teams", 0):
            raise ValidationError({"max_teams": gettext("Höchstzahl unter der Mindestzahl.")})
        if out.get("max_size") is not None and out["max_size"] < out.get("min_size", 0):
            raise ValidationError({"max_size": gettext("Höchstzahl unter der Mindestzahl.")})
        out["positions"] = _positions(value.get("positions"))
    elif kind == CallBlock.Kind.PERSONS:
        for key in ("min", "max"):
            n = _int_or_none(value.get(key), key, 0, MAX_PERSONS)
            if n is not None:
                out[key] = n
        if out.get("max") is not None and out["max"] < out.get("min", 0):
            raise ValidationError({"max": gettext("Höchstzahl unter der Mindestzahl.")})
        out["positions"] = _positions(value.get("positions"))
    elif kind == CallBlock.Kind.NUMBER:
        for key in ("min", "max"):
            n = _int_or_none(value.get(key), key, 0, 1_000_000)
            if n is not None:
                out[key] = n
    elif kind == CallBlock.Kind.CHOICE:
        options = value.get("options") or []
        if not isinstance(options, list):
            raise ValidationError({"options": gettext("Ungültige Angabe.")})
        options = [str(o).strip()[:100] for o in options if str(o).strip()]
        if not options or len(options) > 30:
            raise ValidationError({"options": gettext("Bitte 1 bis 30 Antworten angeben.")})
        out["options"] = list(dict.fromkeys(options))
        out["multiple"] = bool(value.get("multiple", False))
    elif kind == CallBlock.Kind.TEXT:
        out["multiline"] = bool(value.get("multiline", False))
    return out


def reference_date(call: Call) -> datetime.date:
    return call.reference_date or call.date or timezone.localdate()


# --- Angaben je Person ---


def _age(birth: datetime.date | None, on: datetime.date) -> int | None:
    if not birth:
        return None
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


@dataclass
class PersonInfo:
    birth_date: datetime.date | None
    birth_year_only: bool
    active_member: bool
    member_type: int | None
    member_type_name: str
    unit: int | None
    unit_name: str
    entry_date: datetime.date | None
    number: str


def person_infos(org, membership_ids: list[int], on: datetime.date) -> dict[int, PersonInfo]:
    """Angaben zu Mitgliedschaften am Stichtag (für Prüfung und Fassung)."""
    if not membership_ids:
        return {}
    ms = {
        m.pk: m
        for m in Membership.objects.filter(organization=org, pk__in=membership_ids).select_related(
            "person"
        )
    }
    active = set(
        MembershipPeriod.objects.filter(membership_id__in=ms, entry_date__lte=on)
        .filter(Q(exit_date__isnull=True) | Q(exit_date__gte=on))
        .values_list("membership_id", flat=True)
    )
    first_entry: dict[int, datetime.date] = {}
    for mid, d in MembershipPeriod.objects.filter(membership_id__in=ms).values_list(
        "membership_id", "entry_date"
    ):
        if mid not in first_entry or d < first_entry[mid]:
            first_entry[mid] = d
    types: dict[int, tuple[int, str]] = {}
    for a in (
        MemberTypeAssignment.objects.filter(membership_id__in=ms, valid_from__lte=on)
        .exclude(valid_until__lt=on)
        .select_related("member_type")
    ):
        types[a.membership_id] = (a.member_type_id, a.member_type.name)
    units: dict[int, set[int]] = {}
    for mid, dep in (
        DepartmentMembership.objects.filter(membership_id__in=ms, valid_from__lte=on)
        .exclude(valid_until__lt=on)
        .values_list("membership_id", "department_id")
    ):
        units.setdefault(mid, set()).add(dep)
    names = dict(Department.objects.filter(organization=org).values_list("pk", "name"))
    out = {}
    for mid, m in ms.items():
        deps = units.get(mid, set())
        unit = next(iter(deps)) if len(deps) == 1 else None
        type_id, type_name = types.get(mid, (None, ""))
        out[mid] = PersonInfo(
            birth_date=m.person.birth_date,
            birth_year_only=m.person.birth_year_only,
            active_member=mid in active,
            member_type=type_id,
            member_type_name=type_name,
            unit=unit,
            unit_name=", ".join(sorted(names.get(d, "") for d in deps)),
            entry_date=first_entry.get(mid),
            number=m.club_number,
        )
    return out


def _custom_values(org, persons: list[EntryPerson], keys: list[str]) -> dict:
    """{(membership_id, key): Text} für Zusatzfelder."""
    custom = [k[len(FIELD_PREFIX) :] for k in keys if k.startswith(FIELD_PREFIX)]
    if not custom:
        return {}
    from customfields.models import FieldValue

    person_of = {
        p.membership_id: p.membership.person_id for p in persons if p.membership_id is not None
    }
    by_person = {v: k for k, v in person_of.items()}
    out = {}
    for fv in FieldValue.objects.filter(
        organization=org, definition__key__in=custom, person_id__in=person_of.values()
    ).select_related("definition"):
        value = fv.value
        if isinstance(value, bool):
            value = "ja" if value else "nein"
        elif isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        out[(by_person[fv.person_id], FIELD_PREFIX + fv.definition.key)] = (
            "" if value is None else str(value)
        )
    return out


def _detail(info: PersonInfo | None, key: str) -> str:
    if info is None:
        return ""
    if key == "birth_date":
        if not info.birth_date:
            return ""
        return str(info.birth_date.year) if info.birth_year_only else f"{info.birth_date:%d.%m.%Y}"
    if key == "birth_year":
        return str(info.birth_date.year) if info.birth_date else ""
    if key == "member_number":
        return info.number
    if key == "entry_date":
        return f"{info.entry_date:%d.%m.%Y}" if info.entry_date else ""
    if key == "unit":
        return info.unit_name
    if key == "member_type":
        return info.member_type_name
    return ""


# --- Prüfen ---


@dataclass
class Hint:
    text: str
    block: int | None = None
    person: int | None = None
    team: int | None = None

    def as_dict(self) -> dict:
        return {"text": self.text, "block": self.block, "person": self.person, "team": self.team}


def _teams(n: int) -> str:
    return f"{n} {'Mannschaft' if n == 1 else 'Mannschaften'}"


def check(entry: Entry) -> list[Hint]:
    """Hinweise zur Meldung: Bausteine (Anzahlen, Pflicht) und Bedingungen je Person.

    Hinweise sind Warnungen (Ralf 2026-11-01): Abgeben bleibt möglich."""
    call = entry.call
    hints: list[Hint] = []
    blocks = list(call.blocks.all())
    teams = list(entry.teams.all())
    persons = list(entry.persons.select_related("membership__person"))
    answers = {a.block_id: a.value for a in entry.answers.all()}
    for b in blocks:
        s = b.settings or {}
        if b.kind == CallBlock.Kind.TEAMS:
            bt = [t for t in teams if t.block_id == b.pk]
            n = len(bt)
            if b.required and n == 0:
                hints.append(Hint(f"{b.label}: noch keine Mannschaft gemeldet.", block=b.pk))
            if s.get("min_teams") and n < s["min_teams"]:
                hints.append(
                    Hint(
                        f"{b.label}: mindestens {_teams(s['min_teams'])}.",
                        block=b.pk,
                    )
                )
            if s.get("max_teams") is not None and n > s["max_teams"]:
                hints.append(
                    Hint(
                        f"{b.label}: höchstens {_teams(s['max_teams'])}.",
                        block=b.pk,
                    )
                )
            for t in bt:
                tp = [p for p in persons if p.team_id == t.pk]
                regular = sum(1 for p in tp if not p.substitute)
                subs = len(tp) - regular
                if s.get("min_size") and regular < s["min_size"]:
                    hints.append(
                        Hint(
                            f"{t.name}: {regular} von mindestens {s['min_size']} Personen.",
                            block=b.pk,
                            team=t.pk,
                        )
                    )
                if s.get("max_size") is not None and regular > s["max_size"]:
                    hints.append(
                        Hint(
                            f"{t.name}: {regular} Personen, erlaubt sind {s['max_size']}.",
                            block=b.pk,
                            team=t.pk,
                        )
                    )
                limit = s.get("substitutes")
                if subs and (limit is not None and subs > limit):
                    hints.append(
                        Hint(
                            f"{t.name}: {subs} Ersatzleute, erlaubt sind {limit}.",
                            block=b.pk,
                            team=t.pk,
                        )
                    )
        elif b.kind == CallBlock.Kind.PERSONS:
            n = sum(1 for p in persons if p.block_id == b.pk)
            if b.required and n == 0:
                hints.append(Hint(f"{b.label}: noch niemand gemeldet.", block=b.pk))
            if s.get("min") and n < s["min"]:
                hints.append(Hint(f"{b.label}: mindestens {s['min']} Personen.", block=b.pk))
            if s.get("max") is not None and n > s["max"]:
                hints.append(Hint(f"{b.label}: höchstens {s['max']} Personen.", block=b.pk))
        else:
            value = answers.get(b.pk)
            if b.required and value in (None, "", []):
                hints.append(Hint(f"{b.label}: Angabe fehlt.", block=b.pk))
    hints += _check_persons(entry, persons)
    return hints


def _check_persons(entry: Entry, persons: list[EntryPerson]) -> list[Hint]:
    call = entry.call
    cond = call.conditions or {}
    on = reference_date(call)
    infos = person_infos(
        entry.organization, [p.membership_id for p in persons if p.membership_id], on
    )
    hints: list[Hint] = []
    seen_member: dict[int, int] = {}
    for p in persons:
        if p.membership_id is None:
            if not cond.get("guests"):
                hints.append(Hint(f"{p.name}: Gäste sind nicht vorgesehen.", person=p.pk))
            continue
        info = infos.get(p.membership_id)
        if p.membership_id in seen_member:
            if cond.get("one_team") or p.team_id is None:
                hints.append(Hint(f"{p.name} ist mehrfach gemeldet.", person=p.pk))
        seen_member[p.membership_id] = p.pk
        if info is None:
            continue
        if cond.get("active") and not info.active_member:
            hints.append(Hint(f"{p.name} ist am {on:%d.%m.%Y} kein aktives Mitglied.", person=p.pk))
        age = _age(info.birth_date, on)
        if cond.get("min_age") is not None and (age is None or age < cond["min_age"]):
            hints.append(
                Hint(
                    f"{p.name}: Mindestalter {cond['min_age']} am {on:%d.%m.%Y}"
                    + ("" if age is not None else " (Geburtsdatum fehlt)."),
                    person=p.pk,
                )
            )
        if cond.get("max_age") is not None and age is not None and age > cond["max_age"]:
            hints.append(
                Hint(f"{p.name}: Höchstalter {cond['max_age']} am {on:%d.%m.%Y}.", person=p.pk)
            )
        if cond.get("member_types") and info.member_type not in cond["member_types"]:
            hints.append(Hint(f"{p.name}: Mitgliedsart passt nicht.", person=p.pk))
        if cond.get("units") and info.unit not in cond["units"]:
            label = entry.organization.department_label or "Untereinheit"
            hints.append(Hint(f"{p.name}: {label} passt nicht.", person=p.pk))
    if entry.department_id and seen_member:
        # Ausschreibung von oben: dieselbe Person meldet schon eine andere Untereinheit
        others = (
            EntryPerson.objects.filter(entry__call=call, membership_id__in=list(seen_member))
            .exclude(entry=entry)
            .exclude(entry__status=Entry.Status.WITHDRAWN)
            .select_related("entry__department")
        )
        for o in others:
            unit = o.entry.department.name if o.entry.department else ""
            hints.append(
                Hint(
                    f"{o.name} ist auch von {unit} gemeldet.",
                    person=seen_member[o.membership_id],
                )
            )
    return hints


# --- Fassungen ---


def snapshot(entry: Entry) -> dict:
    """Stand der Meldung für Brief, Tabelle und Vergleich (mit Angaben je Person)."""
    call = entry.call
    org = entry.organization
    keys = list(call.person_fields or [])
    persons = list(entry.persons.select_related("membership__person"))
    infos = person_infos(
        org, [p.membership_id for p in persons if p.membership_id], reference_date(call)
    )
    custom = _custom_values(org, persons, keys)
    answers = {a.block_id: a.value for a in entry.answers.all()}

    def person(p: EntryPerson) -> dict:
        details = {}
        for k in keys:
            if p.membership_id is None:
                details[k] = ""
            elif k.startswith(FIELD_PREFIX):
                details[k] = custom.get((p.membership_id, k), "")
            else:
                details[k] = _detail(infos.get(p.membership_id), k)
        return {
            "id": p.pk,
            "name": p.name,
            "club": p.club,
            "guest": p.membership_id is None,
            "position": p.position,
            "substitute": p.substitute,
            "details": details,
        }

    blocks = []
    for b in call.blocks.all():
        item = {"id": b.pk, "kind": b.kind, "label": b.label}
        if b.kind == CallBlock.Kind.TEAMS:
            item["teams"] = [
                {
                    "id": t.pk,
                    "name": t.name,
                    "persons": [person(p) for p in persons if p.team_id == t.pk],
                }
                for t in entry.teams.filter(block=b)
            ]
        elif b.kind == CallBlock.Kind.PERSONS:
            item["persons"] = [person(p) for p in persons if p.block_id == b.pk]
        else:
            item["value"] = answers.get(b.pk)
        blocks.append(item)
    return {
        "fields": [{"key": k, "label": field_label(org, k)} for k in keys],
        "blocks": blocks,
        "fee": fee(call, entry),
    }


def fee(call: Call, entry: Entry) -> str | None:
    if call.fee_amount is None:
        return None
    amount = call.fee_amount
    if call.fee_per == Call.FeePer.TEAM:
        n = entry.teams.count()
        total = amount * n
        text = f"{n} × {money(amount)} = {money(total)}"
    elif call.fee_per == Call.FeePer.PERSON:
        n = entry.persons.count()
        total = amount * n
        text = f"{n} × {money(amount)} = {money(total)}"
    else:
        text = money(amount)
    return text


def money(value) -> str:
    s = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def _value_text(value) -> str:
    if value is None or value == "" or value == []:
        return "—"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def describe_changes(old: dict, new: dict) -> list[str]:
    """Änderungen zwischen zwei Fassungen in Worten (für die Änderungsmeldung)."""
    out: list[str] = []
    old_blocks = {b["id"]: b for b in old.get("blocks", [])}
    for b in new.get("blocks", []):
        ob = old_blocks.get(b["id"], {})
        if b["kind"] == CallBlock.Kind.TEAMS:
            old_teams = {t["id"]: t for t in ob.get("teams", [])}
            new_ids = set()
            for t in b.get("teams", []):
                new_ids.add(t["id"])
                ot = old_teams.get(t["id"])
                if ot is None:
                    names = ", ".join(p["name"] for p in t["persons"]) or "ohne Personen"
                    out.append(f"Neue Mannschaft {t['name']}: {names}.")
                    continue
                if ot["name"] != t["name"]:
                    out.append(f"Mannschaft {ot['name']} heißt jetzt {t['name']}.")
                out += _person_changes(ot["persons"], t["persons"], f"In {t['name']}")
            for tid, ot in old_teams.items():
                if tid not in new_ids:
                    out.append(f"Mannschaft {ot['name']} zurückgezogen.")
        elif b["kind"] == CallBlock.Kind.PERSONS:
            out += _person_changes(ob.get("persons", []), b.get("persons", []), b["label"])
        else:
            if ob.get("value") != b.get("value"):
                new_text = _value_text(b.get("value"))
                out.append(f"{b['label']}: {new_text} statt {_value_text(ob.get('value'))}.")
    return out


def _person_changes(old: list[dict], new: list[dict], where: str) -> list[str]:
    out = []
    old_by_id = {p["id"]: p for p in old}
    new_ids = set()
    for p in new:
        new_ids.add(p["id"])
        op = old_by_id.get(p["id"])
        if op is None:
            out.append(f"{where}: neu {p['name']}.")
        elif op["name"] != p["name"]:
            out.append(f"{where}: {p['name']} statt {op['name']}.")
        elif op.get("details") != p.get("details") or op.get("position") != p.get("position"):
            out.append(f"{where}: Angaben zu {p['name']} geändert.")
        elif op.get("substitute") != p.get("substitute"):
            role = "als Ersatz" if p.get("substitute") else "nicht mehr als Ersatz"
            out.append(f"{where}: {p['name']} {role}.")
    for pid, op in old_by_id.items():
        if pid not in new_ids:
            out.append(f"{where}: {op['name']} gestrichen.")
    return out


def editable(entry: Entry) -> bool:
    return entry.status in (Entry.Status.DRAFT, Entry.Status.SUBMITTED, Entry.Status.CONFIRMED)


def after_deadline(call: Call) -> bool:
    return bool(call.deadline and timezone.localdate() > call.deadline)


@transaction.atomic
def record_version(
    entry: Entry,
    user,
    channel: str,
    sent_to: str = "",
    signed_by: str = "",
    signed_function: str = "",
    reason: str = "",
    withdraw: bool = False,
) -> EntryVersion:
    """Hält den Stand fest und setzt den Zustand. Erste Fassung = Meldung, danach
    Änderungsmeldung, beim Zurückziehen Rückzug."""
    entry = Entry.objects.select_for_update().get(pk=entry.pk)
    last = entry.versions.order_by("-number").first()
    data = snapshot(entry)
    if withdraw:
        kind = EntryVersion.Kind.WITHDRAWAL
        changes = ["Die Meldung wird zurückgezogen."]
    elif last is None or last.kind == EntryVersion.Kind.WITHDRAWAL:
        # Nach einem Rückzug und „Wieder öffnen“ ist es wieder eine neue Meldung
        kind = EntryVersion.Kind.ENTRY
        changes = []
    else:
        kind = EntryVersion.Kind.CHANGE
        changes = describe_changes(last.data or {}, data)
        if not changes:
            raise ValidationError(gettext("Seit der letzten Fassung hat sich nichts geändert."))
    version = EntryVersion.objects.create(
        organization=entry.organization,
        entry=entry,
        number=(last.number + 1) if last else 1,
        kind=kind,
        channel=channel,
        sent_to=sent_to[:300],
        changes=changes,
        reason=reason[:300],
        data=data,
        signed_by=signed_by[:200],
        signed_function=signed_function[:200],
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    entry.status = Entry.Status.WITHDRAWN if withdraw else Entry.Status.SUBMITTED
    entry.changed = False
    entry.save(update_fields=["status", "changed", "updated_at"])
    return version


def mark_changed(entry: Entry) -> None:
    if entry.status != Entry.Status.DRAFT and not entry.changed:
        entry.changed = True
        entry.save(update_fields=["changed", "updated_at"])


# --- Fremder Wettbewerb (Konzept Abschnitt 15, Punkt 1) ---


def competitions_enabled(org) -> bool:
    return "competitions" in (org.enabled_modules or [])


@transaction.atomic
def sync_competition(entry: Entry) -> None:
    """Legt den fremden Wettbewerb an oder führt Mannschaften und Starter nach.

    Starter verweisen über ``EntryPerson.starter`` auf ihren Platz in der Meldung; ein
    Ersatz ändert den Namen des Starters. Ist der Wettbewerb endgültig oder läuft er
    schon, bleibt er unverändert (dann gilt die Starterliste dort)."""
    from competitions.models import (
        Competition,
        Placing,
        Score,
        Scoring,
        Starter,
        Team,
        TeamMember,
    )

    call = entry.call
    org = entry.organization
    if not call.create_competition or not competitions_enabled(org):
        return
    if not call.blocks.filter(kind__in=[CallBlock.Kind.TEAMS, CallBlock.Kind.PERSONS]).exists():
        return
    comp = entry.competition
    if comp is None:
        comp = Competition.objects.create(
            organization=org,
            title=call.title,
            own=False,
            organizer=call.organizer,
            location=call.location,
            date=call.date or timezone.localdate(),
            description=call.description,
        )
        Scoring.objects.create(
            organization=org,
            competition=comp,
            name="Einzelwertung",
            kind=Scoring.Kind.INDIVIDUAL,
            sort_order=1,
        )
        if entry.teams.exists():
            Scoring.objects.create(
                organization=org,
                competition=comp,
                name="Mannschaftswertung",
                kind=Scoring.Kind.TEAM,
                sort_order=2,
            )
        entry.competition = comp
        entry.save(update_fields=["competition", "updated_at"])
    if comp.status != Competition.Status.PREPARATION:
        return
    units = person_infos(
        org,
        [p.membership_id for p in entry.persons.all() if p.membership_id],
        reference_date(call),
    )
    # Starter: je Platz der Meldung einer
    keep_starters = set()
    for p in entry.persons.select_related("starter"):
        unit_id = units[p.membership_id].unit if p.membership_id in units else None
        s = p.starter if p.starter and p.starter.competition_id == comp.pk else None
        if s is None and p.membership_id:
            s = Starter.objects.filter(competition=comp, membership_id=p.membership_id).first()
        if s is None:
            s = Starter(organization=org, competition=comp)
        if p.membership_id and p.membership_id != s.membership_id:
            # Ersatz: Mitglied wechselt; falls es schon anderswo steht, dort lösen
            Starter.objects.filter(competition=comp, membership_id=p.membership_id).exclude(
                pk=s.pk
            ).update(membership=None)
        s.membership_id = p.membership_id
        s.name = p.name[:200]
        s.club = p.club[:200]
        s.unit_id = unit_id
        s.save()
        keep_starters.add(s.pk)
        if p.starter_id != s.pk:
            p.starter = s
            p.save(update_fields=["starter"])
    linked = set(
        EntryPerson.objects.filter(entry=entry, starter__isnull=False).values_list(
            "starter_id", flat=True
        )
    )
    # Starter, die aus der Meldung gefallen sind (ohne erfasste Werte)
    gone = Starter.objects.filter(competition=comp).exclude(pk__in=keep_starters | linked)
    for s in gone:
        if (
            not Score.objects.filter(starter=s).exists()
            and not Placing.objects.filter(starter=s).exists()
        ):
            s.delete()
    # Mannschaften
    keep_teams = set()
    for t in entry.teams.select_related("team"):
        team = t.team if t.team and t.team.competition_id == comp.pk else None
        if team is None:
            team = Team(organization=org, competition=comp)
        team.name = t.name[:100]
        team.sort_order = t.sort_order
        team.save()
        keep_teams.add(team.pk)
        if t.team_id != team.pk:
            t.team = team
            t.save(update_fields=["team"])
        members = [
            p.starter_id
            for p in EntryPerson.objects.filter(team=t, substitute=False, starter__isnull=False)
        ]
        TeamMember.objects.filter(team=team).exclude(starter_id__in=members).delete()
        have = set(TeamMember.objects.filter(team=team).values_list("starter_id", flat=True))
        TeamMember.objects.bulk_create(
            [
                TeamMember(organization=org, team=team, starter_id=sid)
                for sid in members
                if sid not in have
            ]
        )
    Team.objects.filter(competition=comp).exclude(pk__in=keep_teams).delete()


def internal_competition(call: Call):
    """Eigener Wettbewerb einer Ausschreibung an Untereinheiten (beim ersten Bestätigen
    angelegt, mit Einzel-, Einheiten- und, bei Mannschaften, Mannschaftswertung)."""
    from competitions.models import Competition, Scoring

    if call.competition_id:
        return call.competition
    org = call.organization
    if not call.create_competition or not competitions_enabled(org):
        return None
    if not call.blocks.filter(kind__in=[CallBlock.Kind.TEAMS, CallBlock.Kind.PERSONS]).exists():
        return None
    comp = Competition.objects.create(
        organization=org,
        title=call.title,
        own=True,
        location=call.location,
        date=call.date or timezone.localdate(),
        description=call.description,
    )
    kinds = [
        ("Einzelwertung", Scoring.Kind.INDIVIDUAL),
        ("Wertung der Untereinheiten", Scoring.Kind.UNIT),
    ]
    if call.blocks.filter(kind=CallBlock.Kind.TEAMS).exists():
        kinds.append(("Mannschaftswertung", Scoring.Kind.TEAM))
    for n, (name, kind) in enumerate(kinds, 1):
        Scoring.objects.create(
            organization=org, competition=comp, name=name, kind=kind, sort_order=n
        )
    call.competition = comp
    call.save(update_fields=["competition", "updated_at"])
    return comp


def sync_internal(entry: Entry) -> None:
    """Bestätigte Meldung einer Untereinheit: Personen werden Starter im eigenen Wettbewerb
    (Untereinheit = meldende Einheit), Mannschaften werden Mannschaften. Nur, was diese
    Meldung selbst angelegt hat, wird später geändert oder entfernt (``entry.synced``)."""
    from competitions.models import Competition, Placing, Score, Starter, Team, TeamMember

    if entry.status == Entry.Status.WITHDRAWN and not entry.synced:
        return
    comp = internal_competition(entry.call)
    if comp is None or comp.status != Competition.Status.PREPARATION:
        return
    org = entry.organization
    before = entry.synced or {}
    own_starters = set(before.get("starters", []))
    own_teams = set(before.get("teams", []))
    keep_starters: set[int] = set()
    # Zurückgezogen: alles, was die Meldung angelegt hat, fällt wieder heraus
    withdrawn = entry.status == Entry.Status.WITHDRAWN
    persons = [] if withdrawn else entry.persons.select_related("starter")
    for p in persons:
        s = p.starter if p.starter and p.starter.competition_id == comp.pk else None
        if s is None and p.membership_id:
            s = Starter.objects.filter(competition=comp, membership_id=p.membership_id).first()
        if s is None:
            s = Starter(organization=org, competition=comp)
        s.membership_id = p.membership_id
        s.name = p.name[:200]
        s.club = p.club[:200]
        s.unit_id = entry.department_id
        s.save()
        keep_starters.add(s.pk)
        if p.starter_id != s.pk:
            p.starter = s
            p.save(update_fields=["starter"])
    for s in Starter.objects.filter(pk__in=own_starters - keep_starters):
        if (
            not Score.objects.filter(starter=s).exists()
            and not Placing.objects.filter(starter=s).exists()
        ):
            s.delete()
    keep_teams: set[int] = set()
    for t in [] if withdrawn else entry.teams.select_related("team"):
        team = t.team if t.team and t.team.competition_id == comp.pk else None
        if team is None:
            team = Team(organization=org, competition=comp)
        team.name = t.name[:100]
        team.sort_order = t.sort_order
        team.save()
        keep_teams.add(team.pk)
        if t.team_id != team.pk:
            t.team = team
            t.save(update_fields=["team"])
        members = [
            p.starter_id
            for p in EntryPerson.objects.filter(team=t, substitute=False, starter__isnull=False)
        ]
        TeamMember.objects.filter(team=team).exclude(starter_id__in=members).delete()
        have = set(TeamMember.objects.filter(team=team).values_list("starter_id", flat=True))
        TeamMember.objects.bulk_create(
            [
                TeamMember(organization=org, team=team, starter_id=x)
                for x in members
                if x not in have
            ]
        )
    Team.objects.filter(pk__in=own_teams - keep_teams).delete()
    entry.synced = {"starters": sorted(keep_starters), "teams": sorted(keep_teams)}
    entry.save(update_fields=["synced", "updated_at"])


# --- Kopieren und Kürzen ---


@transaction.atomic
def copy_call(call: Call, *, title: str = "") -> Call:
    """Kopie für das nächste Jahr: Datum und Fristen um ein Jahr weiter."""

    def next_year(d):
        if d is None:
            return None
        try:
            return d.replace(year=d.year + 1)
        except ValueError:  # 29. Februar
            return d.replace(year=d.year + 1, day=28)

    old_blocks = list(call.blocks.all())
    new = Call.objects.get(pk=call.pk)
    new.pk = None
    new.id = None
    new.copied_from = call
    new.event = None
    new.competition = None
    new.title = title or _next_title(call.title, call.date)
    new.date = next_year(call.date)
    new.deadline = next_year(call.deadline)
    new.reference_date = next_year(call.reference_date)
    new.save()
    for b in old_blocks:
        b.pk = None
        b.id = None
        b.call = new
        b.save()
    return new


def _next_title(title: str, date) -> str:
    if date and str(date.year) in title:
        return title.replace(str(date.year), str(date.year + 1))
    return title


RETENTION_DAYS = 365


def shorten_old(today: datetime.date | None = None) -> int:
    """Ein Jahr nach dem Anlass: Fassungen auf Name und Mannschaft kürzen (Frage 7)."""
    today = today or timezone.localdate()
    limit = today - datetime.timedelta(days=RETENTION_DAYS)
    n = 0
    versions = EntryVersion.objects.filter(shortened_at__isnull=True).filter(
        Q(entry__call__date__lt=limit)
        | Q(entry__call__date__isnull=True, created_at__date__lt=limit)
    )
    for v in versions.iterator():
        v.data = shortened(v.data or {})
        v.shortened_at = timezone.now()
        v.save(update_fields=["data", "shortened_at"])
        n += 1
    return n


def shortened(data: dict) -> dict:
    def person(p: dict) -> dict:
        return {
            "id": p.get("id"),
            "name": p.get("name", ""),
            "club": p.get("club", ""),
            "guest": p.get("guest", False),
            "position": p.get("position", ""),
            "substitute": p.get("substitute", False),
            "details": {},
        }

    blocks = []
    for b in data.get("blocks", []):
        b = dict(b)
        if "teams" in b:
            b["teams"] = [{**t, "persons": [person(p) for p in t["persons"]]} for t in b["teams"]]
        if "persons" in b:
            b["persons"] = [person(p) for p in b["persons"]]
        blocks.append(b)
    return {**data, "fields": [], "blocks": blocks}


def clear_answers_for(block: CallBlock) -> None:
    EntryAnswer.objects.filter(block=block).delete()


def teams_of(entry: Entry, block: CallBlock) -> list[EntryTeam]:
    return list(entry.teams.filter(block=block))


# --- Ausschreibung an Untereinheiten (Schritt 3) ---


def unit_choices(org) -> list[Department]:
    """Untereinheiten, die angeschrieben werden können (alle aktiven im Baum)."""
    return list(
        Department.objects.filter(organization=org, is_active=True).order_by("sort_order", "name")
    )


def clean_units(org, raw) -> list[int]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValidationError({"units": gettext("Ungültige Angabe.")})
    allowed = {d.pk for d in unit_choices(org)}
    out = []
    for v in raw:
        try:
            pk = int(v)
        except (TypeError, ValueError):
            raise ValidationError({"units": gettext("Ungültige Angabe.")}) from None
        if pk not in allowed:
            raise ValidationError({"units": gettext("Unbekannte Untereinheit.")})
        if pk not in out:
            out.append(pk)
    return out


def addressed_units(call: Call) -> list[int]:
    """Angeschriebene Untereinheiten: ausgewählt oder alle direkt darunter."""
    if not call.internal:
        return []
    active = {d.pk: d for d in unit_choices(call.organization)}
    if call.units:
        return [pk for pk in call.units if pk in active]
    return [d.pk for d in active.values() if d.parent_id == call.organization_id]


def unit_counts(call: Call) -> dict:
    units = addressed_units(call)
    done = Entry.objects.filter(
        call=call,
        department_id__in=units,
        status__in=(Entry.Status.SUBMITTED, Entry.Status.CONFIRMED),
    ).count()
    return {"addressed": len(units), "submitted": done}


def unit_contacts(org, department) -> list[str]:
    """E-Mail-Adressen der Personen, die für die Untereinheit melden dürfen (Rolle der
    Untereinheit oder einer darüber, mit Zugang zur Anmeldung)."""
    from access.catalog import DEPT_ENTRIES_SUBMIT
    from members.models import DepartmentRoleHolder
    from organizations.tree import UnitTree
    from portal.models import PortalAccess

    line = UnitTree.of(org.pk).ancestors(department.pk) or [department.pk]
    today = timezone.localdate()
    holders = (
        DepartmentRoleHolder.objects.filter(
            role__department_id__in=line,
            role__department__self_managed=True,
            valid_from__lte=today,
        )
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        .select_related("role")
    )
    memberships = {
        h.membership_id for h in holders if DEPT_ENTRIES_SUBMIT in (h.role.permissions or [])
    }
    emails = (
        PortalAccess.objects.filter(organization=org, membership_id__in=memberships)
        .select_related("user")
        .values_list("user__email", flat=True)
    )
    return sorted({e for e in emails if e})


def unit_member_ids(org, department, on: datetime.date):
    """Mitgliedschaften der Untereinheit samt Teilbaum am Stichtag (für die Auswahl im
    Bereich der Untereinheit)."""
    from members.models import DepartmentMembership
    from organizations.tree import UnitTree

    ids = UnitTree.of(org.pk).subtree(department.pk)
    return (
        DepartmentMembership.objects.filter(department_id__in=ids, valid_from__lte=on)
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
        .values("membership_id")
    )
