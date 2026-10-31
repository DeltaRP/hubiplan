"""Erfundene Mitglieder für die Demodaten der Pilotorganisationen (deterministisch)."""

from __future__ import annotations

import datetime
import random

from django.db import models

from access.models import Role, RoleAssignment
from accounts.models import User
from organizations.models import Department, DepartmentRole, Organization

from . import services
from .models import (
    DepartmentRoleHolder,
    ExitReason,
    Membership,
    MemberType,
)

FIRST = [
    "Anton",
    "Bernd",
    "Christian",
    "Dirk",
    "Elmar",
    "Frank",
    "Georg",
    "Heinz",
    "Jens",
    "Klaus",
    "Lars",
    "Markus",
    "Norbert",
    "Oliver",
    "Peter",
    "Rainer",
    "Stefan",
    "Thomas",
    "Uwe",
    "Volker",
    "Werner",
    "Andrea",
    "Birgit",
    "Claudia",
    "Doris",
    "Elke",
    "Gabi",
    "Heike",
    "Jutta",
    "Karin",
    "Lena",
    "Monika",
    "Nina",
    "Petra",
    "Sabine",
    "Tanja",
]
LAST = [
    "Musterhoff",
    "Beispielmann",
    "Probeling",
    "Testgen",
    "Erdacht",
    "Ausgedachter",
    "Platzhalter",
    "Fiktivus",
    "Annahme",
    "Vorlagen",
    "Entwurfs",
    "Schablonski",
    "Modellmann",
    "Exemplar",
    "Simulatus",
    "Muster-Kamp",
    "Proband",
    "Skizzer",
]
STREETS = [
    "Hubertusweg",
    "Am Rheindeich",
    "Kapellenstraße",
    "Schützenstraße",
    "Erftweg",
    "Kirchgasse",
]

TYPES = [
    # (Name, gemeldet, aktiv, zählt für Dauer)
    ("aktiv", True, True, True),
    ("passiv", True, False, True),
    ("Ehrenmitglied", True, False, True),
    ("Jungschütze", True, True, True),
]

MEMBERS_PER_ZUG = (8, 15)


def seed_members(orgs: dict[str, Organization]) -> None:
    club = orgs["club"]
    rnd = random.Random(1920)  # noqa: S311 – nur Testdaten
    types = []
    for order, (name, reported, active, counts) in enumerate(TYPES):
        obj, _ = MemberType.objects.get_or_create(
            organization=club,
            name=name,
            defaults={
                "reported": reported,
                "active": active,
                "counts_for_duration": counts,
                "sort_order": order,
            },
        )
        types.append(obj)
    if not Membership.objects.filter(organization=club).exists():
        number = 1000
        for zug in Department.objects.filter(organization=club).order_by("sort_order"):
            for _ in range(rnd.randint(*MEMBERS_PER_ZUG)):
                number += 1
                _admit(club, zug, types, rnd, number)
        # Einige Mitglieder ohne Zug (passive Mitglieder, Ehrenmitglieder)
        for _ in range(12):
            number += 1
            _admit(club, None, types[1:3], rnd, number)
    _link_board_member(orgs)
    _assign_zug_roles(club)
    _seed_fields(orgs, rnd)


def _assign_zug_roles(club) -> None:
    """Zugrollen mit Mitgliedern des Zugs besetzen.

    Wiederholbar: besetzte Rollen bleiben, wie sie sind. In manchen Zügen hat eine
    Person zwei Rollen (Spieß und Kassierer, Leutnant und Schriftführer), in
    manchen bleibt der Schriftführer frei.
    """
    on = datetime.date.today()
    for index, zug in enumerate(
        Department.objects.filter(organization=club).order_by("sort_order")
    ):
        members = [
            m
            for m in Membership.objects.filter(
                organization=club,
                department_memberships__department=zug,
                department_memberships__valid_until__isnull=True,
            )
            .order_by("pk")
            .distinct()
            if m.current_period()
        ]
        roles = list(DepartmentRole.objects.filter(department=zug).order_by("position"))
        assigned: dict[str, Membership | None] = {}
        for role in roles:
            current = (
                role.holders.filter(valid_from__lte=on)
                .filter(models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=on))
                .select_related("membership")
                .first()
            )
            if current:
                assigned[role.name] = current.membership
        # Wer schon eine Rolle hat, bekommt eine weitere nur gezielt (siehe unten)
        taken = {m.pk for m in assigned.values() if m}
        for role in roles:
            if role.name in assigned:
                continue
            if role.name == "Kassierer" and index % 3 == 0:
                holder = assigned.get("Spieß")
            elif role.name == "Schriftführer" and index % 4 == 1:
                holder = None  # bleibt unbesetzt
            elif role.name == "Schriftführer" and index % 5 == 2:
                holder = assigned.get("Leutnant")
            else:
                holder = next((m for m in members if m.pk not in taken), None)
            assigned[role.name] = holder
            if holder is not None:
                taken.add(holder.pk)
                DepartmentRoleHolder.objects.create(
                    organization=club,
                    membership=holder,
                    role=role,
                    valid_from=max(holder.current_period().entry_date, datetime.date(2015, 1, 1)),
                )


def _admit(club, zug, types, rnd, number) -> Membership | None:
    first, last = rnd.choice(FIRST), rnd.choice(LAST)
    birth = datetime.date(rnd.randint(1945, 2008), rnd.randint(1, 12), rnd.randint(1, 28))
    entry = datetime.date(rnd.randint(max(1970, birth.year + 14), 2025), rnd.randint(1, 12), 1)
    if zug is not None:
        young = birth.year >= 2004
        member_type = types[3] if young else (types[0] if rnd.random() < 0.75 else types[1])
    else:
        member_type = rnd.choice(types)
    try:
        membership = services.admit(
            club,
            {
                "last_name": last,
                "first_name": first,
                "birth_date": birth,
                "member_type": member_type,
                "entry_date": entry,
                "club_number": str(number),
                "email": f"{first.lower()}.{last.lower()}{number}@beispiel.test",
                "phone": f"02131 {rnd.randint(100000, 999999)}" if rnd.random() < 0.6 else "",
                "street": f"{rnd.choice(STREETS)} {rnd.randint(1, 60)}",
                "postal_code": "41468",
                "city": "Neuss",
                "departments": [zug] if zug else [],
            },
        )
    except Exception:  # noqa: BLE001 – Zufallsdaten: Konflikte überspringen
        return None
    # Etwa jedes zwölfte Mitglied ist schon ausgetreten (Archiv)
    if rnd.random() < 1 / 12:
        period = membership.periods.first()
        exit_date = min(
            entry + datetime.timedelta(days=rnd.randint(400, 6000)), datetime.date(2025, 12, 31)
        )
        if exit_date > period.entry_date:
            period.exit_date = exit_date
            period.exit_reason = rnd.choice([ExitReason.EXIT, ExitReason.STRIKE_OFF])
            period.save()
            membership.type_assignments.update(valid_until=exit_date)
            membership.department_memberships.update(valid_until=exit_date)
    return membership


def _link_board_member(orgs) -> None:
    """Der Vorstand des Vereins hat auch eine Mitgliedsakte (Vorstandsrollen-Historie)."""
    club = orgs["club"]
    user = User.objects.filter(email="vorstand@hubertus-grimlinghausen.test").first()
    if user is None:
        return
    assignment = RoleAssignment.objects.filter(
        organization=club, user=user, role=Role.objects.get(organization=club, name="Vorstand")
    ).first()
    if assignment is None or assignment.person_id:
        return
    membership = services.admit(
        club,
        {
            "last_name": "Hubertus",
            "first_name": "Hanna",
            "birth_date": datetime.date(1972, 11, 3),
            "member_type": MemberType.objects.get(organization=club, name="aktiv"),
            "entry_date": datetime.date(1995, 5, 1),
            "email": "vorstand@hubertus-grimlinghausen.test",
            "phone": "02131 123456",
            "street": "Hubertusweg 1",
            "postal_code": "41468",
            "city": "Neuss",
            "departments": [Department.objects.get(organization=club, name="Herolde")],
        },
    )
    assignment.person = membership.person
    assignment.save()
    if club.contact_source != Organization.ContactSource.ROLE:
        club.contact_source = Organization.ContactSource.ROLE
        club.contact_role = assignment.role
        club.save()


def _seed_fields(orgs, rnd) -> None:
    """Zusatzfelder: verbandsweite Ehrennadel, Auszeichnungen, Uniformgröße."""
    from customfields.models import FieldDefinition, FieldValue

    federation, club = orgs["federation"], orgs["club"]
    needle, _ = FieldDefinition.objects.get_or_create(
        organization=federation,
        key="verbandsehrennadel",
        defaults={
            "label": "Verbandsehrennadel",
            "field_type": "choice",
            "choices": ["Bronze", "Silber", "Gold"],
            "federation_wide": True,
        },
    )
    awards, _ = FieldDefinition.objects.get_or_create(
        organization=club,
        key="auszeichnung",
        defaults={
            "label": "Auszeichnung",
            "repeatable": True,
            "subfields": [
                {"key": "bezeichnung", "label": "Bezeichnung", "type": "text", "choices": []},
                {"key": "datum", "label": "Datum", "type": "date", "choices": []},
                {"key": "verliehen-von", "label": "verliehen von", "type": "text", "choices": []},
            ],
        },
    )
    FieldDefinition.objects.get_or_create(
        organization=club,
        key="uniformgroesse",
        defaults={
            "label": "Uniformgröße",
            "field_type": "choice",
            "choices": ["46", "48", "50", "52", "54", "56", "58"],
        },
    )
    if FieldValue.objects.filter(definition__in=[needle, awards]).exists():
        return
    current = [
        m
        for m in Membership.objects.filter(organization=club).select_related("person")
        if m.current_period()
    ]
    for m in rnd.sample(current, min(25, len(current))):
        FieldValue.objects.create(
            organization=club,
            definition=awards,
            person=m.person,
            value=[
                {
                    "bezeichnung": rnd.choice(["Königsschuss", "Verdienstorden", "Zugkönig"]),
                    "datum": f"{rnd.randint(1995, 2025)}-08-{rnd.randint(10, 28)}",
                    "verliehen-von": "Hubertus-Schützenverein",
                }
            ],
        )
        if rnd.random() < 0.5:
            FieldValue.objects.create(
                organization=federation,
                definition=needle,
                person=m.person,
                value=rnd.choice(["Bronze", "Silber", "Gold"]),
            )
