"""Ansicht als Rolle: nur lesen, nie mehr als die eigenen Rechte, im Protokoll."""

from __future__ import annotations

import pytest

from access.catalog import (
    AUDIT_VIEW,
    FINANCE_VIEW,
    MEMBERS_EDIT,
    MEMBERS_VIEW,
    ROLES_MANAGE,
    ROLES_PREVIEW,
)
from access.models import Role
from audit.models import AuditEntry
from core.tenancy import tenant_context

from .factories import give_role, make_user


@pytest.fixture
def setup(orgs):
    org = orgs["a"]
    chef = make_user("chef@example.org")
    give_role(chef, org, [MEMBERS_VIEW, MEMBERS_EDIT, ROLES_PREVIEW, AUDIT_VIEW], name="Chef")
    # Die Rolle hat auch die Kasse, die der Chef selbst nicht hat
    kassierer = Role.objects.create(
        organization=org, name="Kassierer", permissions=[MEMBERS_VIEW, FINANCE_VIEW]
    )
    return {"org": org, "chef": chef, "kassierer": kassierer}


def _mine(client, org):
    data = client.get("/api/me/organizations/").json()
    return next(o for o in data if o["id"] == org.pk)


@pytest.mark.django_db
def test_ansicht_zeigt_schnittmenge_und_ist_nur_lesen(setup, api):
    org, client = setup["org"], api(setup["chef"])
    url = f"/api/orgs/{org.pk}/ansicht/"

    state = client.get(url).json()
    assert state["available"] is True
    assert {r["name"] for r in state["roles"]} == {"Chef", "Kassierer"}
    assert state["active"] is None

    res = client.post(url, {"role": setup["kassierer"].pk}, content_type="application/json")
    assert res.status_code == 200
    assert res.json()["active"]["name"] == "Kassierer"

    mine = _mine(client, org)
    # Nur, was der Chef selbst hat und die Rolle hat: keine Kasse, kein Bearbeiten
    assert mine["permissions"] == [MEMBERS_VIEW]
    assert mine["role_preview"] == {
        "available": True,
        "active": {"id": setup["kassierer"].pk, "name": "Kassierer"},
    }
    assert client.get(f"/api/orgs/{org.pk}/members/").status_code == 200
    assert client.get(f"/api/orgs/{org.pk}/audit/").status_code == 403

    # Schreiben ist gesperrt, auch was die Rolle dürfte
    res = client.post(f"/api/orgs/{org.pk}/roles/", {"name": "X"}, content_type="application/json")
    assert res.status_code == 403
    assert res.json()["ansicht"] is True

    # Beenden geht, danach gelten wieder die eigenen Rechte
    res = client.delete(url)
    assert res.status_code == 200
    assert res.json()["active"] is None
    assert MEMBERS_EDIT in _mine(client, org)["permissions"]

    with tenant_context(org.pk):
        changes = [
            e.changes
            for e in AuditEntry.objects.filter(organization=org, action="view").order_by("pk")
        ]
    assert changes == [
        {"Ansicht als Rolle": ["", "begonnen"]},
        {"Ansicht als Rolle": ["begonnen", "beendet"]},
    ]


@pytest.mark.django_db
def test_ohne_recht_keine_ansicht(setup, api):
    org = setup["org"]
    user = make_user("ohne@example.org")
    give_role(user, org, [MEMBERS_VIEW, ROLES_MANAGE], name="Schriftführer")
    client = api(user)
    url = f"/api/orgs/{org.pk}/ansicht/"
    assert client.get(url).json() == {"available": False, "roles": [], "active": None}
    res = client.post(url, {"role": setup["kassierer"].pk}, content_type="application/json")
    assert res.status_code == 403
    assert _mine(client, org)["role_preview"] == {"available": False, "active": None}


@pytest.mark.django_db
def test_nur_rollen_der_eigenen_einheit(setup, orgs, api):
    fremd = Role.objects.create(organization=orgs["b"], name="Fremd", permissions=[MEMBERS_VIEW])
    client = api(setup["chef"])
    res = client.post(
        f"/api/orgs/{setup['org'].pk}/ansicht/", {"role": fremd.pk}, content_type="application/json"
    )
    assert res.status_code == 400
    # Fremde Einheit: nicht einmal sichtbar
    assert client.get(f"/api/orgs/{orgs['b'].pk}/ansicht/").status_code == 404


@pytest.mark.django_db
def test_ansicht_endet_wenn_das_recht_entzogen_wird(setup, api):
    org, chef = setup["org"], setup["chef"]
    client = api(chef)
    client.post(
        f"/api/orgs/{org.pk}/ansicht/",
        {"role": setup["kassierer"].pk},
        content_type="application/json",
    )
    with tenant_context(org.pk):
        role = Role.objects.get(organization=org, name="Chef")
        role.permissions = [MEMBERS_VIEW, MEMBERS_EDIT]
        role.save()
    mine = _mine(client, org)
    assert mine["role_preview"] == {"available": False, "active": None}
    assert MEMBERS_EDIT in mine["permissions"]
    # Sitzung ist wieder frei: Schreiben geht wieder durch die normale Prüfung
    res = client.post(f"/api/orgs/{org.pk}/roles/", {"name": "X"}, content_type="application/json")
    assert res.status_code == 403
    assert "ansicht" not in res.json()
