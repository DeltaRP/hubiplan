"""Ein Benutzer mit mehreren Rollen: Rechte addieren sich, Webseite fasst zusammen."""

from __future__ import annotations

import datetime

import pytest

from access.catalog import FINANCE_EDIT, MEMBERS_VIEW, ROLES_MANAGE
from access.models import Role, RoleAssignment
from access.permissions import permissions_in
from website.public import SiteView

from .factories import give_role, make_user
from .test_webseite_schnittstelle import get, setup  # noqa: F401  (Fixture)

pytestmark = pytest.mark.django_db(transaction=True)


def test_rechte_sind_die_summe_aller_aktiven_rollen(orgs):
    org = orgs["a"]
    user = make_user("doppelt@example.org")
    give_role(user, org, [MEMBERS_VIEW], name="Adjutant")
    give_role(user, org, [FINANCE_EDIT], name="1. Kassierer")
    give_role(
        user,
        org,
        [ROLES_MANAGE],
        name="Alter Vorstand",
        valid_until=datetime.date(2021, 12, 31),
    )
    perms = permissions_in(user, org)
    assert {MEMBERS_VIEW, FINANCE_EDIT} <= perms
    # Beendete Rollen zählen nicht mehr
    assert ROLES_MANAGE not in perms


def test_namen_zusammenfassen():
    assert SiteView.join_names(["A"]) == "A"
    assert SiteView.join_names(["A", "B"]) == "A & B"
    assert SiteView.join_names(["A", "B", "C"]) == "A, B & C"


def test_webseite_fasst_rollen_derselben_person_zusammen(setup):  # noqa: F811
    org, erika = setup["org"], setup["erika"]
    for i, name in enumerate(["Adjutant", "Schriftführerin"], start=2):
        role = Role.objects.create(
            organization=org, name=name, on_website=True, position=i, website_position=i
        )
        RoleAssignment.objects.create(organization=org, role=role, person=erika.person)
    shared = Role.objects.create(
        organization=org, name="Beisitzer", on_website=True, position=9, website_position=9
    )
    RoleAssignment.objects.create(organization=org, role=shared, person=erika.person)
    RoleAssignment.objects.create(organization=org, role=shared, person=setup["otto"].person)

    roles = get("schluessel-a/board/").json()["roles"]
    names = [r["name"] for r in roles]
    assert names == ["1. Vorsitzende, Adjutant & Schriftführerin", "Beisitzer"]
    assert [h["name"] for h in roles[0]["holders"]] == ["Erika Beispiel"]
    assert len(roles[1]["holders"]) == 2

    recipients = [r["name"] for r in get("schluessel-a/contact/").json()["recipients"]]
    assert "1. Vorsitzende, Adjutant & Schriftführerin" in recipients
    # „Nachricht schreiben“ zeigt auf genau den zusammengefassten Empfänger
    ids = {r["id"] for r in get("schluessel-a/contact/").json()["recipients"]}
    assert all(r["id"] in ids for r in roles if r["contact_form"])
