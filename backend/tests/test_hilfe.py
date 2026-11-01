"""Hilfe: Ansprechpartner und Hinweise der Einheit, abgehakte erste Schritte."""

from __future__ import annotations

import pytest

from access.catalog import MEMBERS_VIEW, ORG_EDIT, ROLES_MANAGE, ROLES_PREVIEW
from access.models import Role
from audit.models import AuditEntry
from core.tenancy import tenant_context
from organizations.help_views import clean_contacts, clean_notes

from .factories import give_role, make_user

JSON = "application/json"
pytestmark = pytest.mark.django_db


def test_bereinigen():
    assert clean_contacts("x") == []
    assert clean_contacts([{"name": " Anna ", "email": "a@example.org", "x": 1}, {"name": ""}]) == [
        {"name": "Anna", "hint": "", "email": "a@example.org"}
    ]
    assert clean_contacts([{"name": str(i)} for i in range(20)])[-1]["name"] == "9"
    raw = {"guide.a": " x ", "page.b": "y", "guide.c": " ", 3: "z"}
    assert clean_notes(raw) == {"guide.a": "x"}


def test_lesen_jede_rolle_aendern_nur_mit_recht(orgs, api):
    org = orgs["a"]
    leser = make_user("leser@example.org")
    give_role(leser, org, [MEMBERS_VIEW], name="Leser")
    chef = make_user("chef@example.org")
    give_role(chef, org, [ORG_EDIT, ROLES_MANAGE], name="Geschäftsführung")
    fremd = make_user("fremd@example.org")
    give_role(fremd, orgs["b"], [ORG_EDIT])
    url = f"/api/orgs/{org.pk}/help/"

    state = api(leser).get(url).json()
    assert state["contacts"] == [] and state["contacts_from"] is None
    assert state["can_edit"] is False
    assert state["admin_roles"] == ["Geschäftsführung"]
    assert MEMBERS_VIEW in state["rights"] and state["rights"][MEMBERS_VIEW]

    assert api(fremd).get(url).status_code == 404
    contacts = [{"name": "Anna Beispiel", "hint": "Mitglieder", "email": "anna@example.org"}]
    assert api(leser).patch(url, {"contacts": contacts}, content_type=JSON).status_code == 403

    res = api(chef).patch(url, {"contacts": contacts}, content_type=JSON)
    assert res.status_code == 200
    assert res.json()["contacts"] == contacts
    assert res.json()["contacts_from"] == {"name": org.display_name, "own": True}
    assert api(leser).get(url).json()["contacts"] == contacts

    bad = api(chef).patch(url, {"contacts": [{"name": "X", "email": "kein"}]}, content_type=JSON)
    assert bad.status_code == 400
    with tenant_context(org.pk):
        assert (
            AuditEntry.objects.filter(
                organization=org, changes__has_key="Ansprechpartner für Fragen zu HUBIplan"
            ).count()
            == 1
        )


def test_ansprechpartner_und_hinweise_von_oben(orgs, api):
    fed, org = orgs["federation"], orgs["a"]
    fed.help_contacts = [{"name": "Bund-Hilfe", "hint": "", "email": ""}]
    fed.help_notes = {"guide.member_new": "Bitte Formular B nutzen."}
    fed.save()
    chef = make_user("chef@example.org")
    give_role(chef, org, [ORG_EDIT])
    client = api(chef)

    state = client.get(f"/api/orgs/{org.pk}/help/").json()
    assert state["contacts"][0]["name"] == "Bund-Hilfe"
    assert state["contacts_from"] == {"name": fed.display_name, "own": False}
    assert state["own_contacts"] == []

    url = f"/api/orgs/{org.pk}/help/notes/guide.member_new/"
    res = client.put(url, {"text": "Bei uns: Kassierer fragen."}, content_type=JSON)
    assert res.status_code == 200
    notes = res.json()["notes"]["guide.member_new"]
    assert [(n["text"], n["own"]) for n in notes] == [
        ("Bitte Formular B nutzen.", False),
        ("Bei uns: Kassierer fragen.", True),
    ]
    # Leerer Text entfernt nur den eigenen Hinweis
    res = client.put(url, {"text": " "}, content_type=JSON)
    assert [n["own"] for n in res.json()["notes"]["guide.member_new"]] == [False]
    bad = client.put(f"/api/orgs/{org.pk}/help/notes/page.x/", {"text": "x"}, content_type=JSON)
    assert bad.status_code == 403


def test_hinweise_nur_mit_recht(orgs, api):
    org = orgs["a"]
    leser = make_user("leser@example.org")
    give_role(leser, org, [MEMBERS_VIEW])
    url = f"/api/orgs/{org.pk}/help/notes/guide.member_new/"
    assert api(leser).put(url, {"text": "x"}, content_type=JSON).status_code == 403


def test_erste_schritte_abhaken(orgs, api):
    user = make_user("neu@example.org")
    client = api(user)
    assert client.get("/api/me/help/").json() == {"help_done": []}
    assert client.post("/api/me/help/start.profile/").json() == {"help_done": ["start.profile"]}
    client.post("/api/me/help/start.password/")
    assert client.get("/api/me/help/").json()["help_done"] == ["start.password", "start.profile"]
    assert client.delete("/api/me/help/start.profile/").json() == {"help_done": ["start.password"]}
    assert client.post("/api/me/help/Böse Sache/").status_code == 404
    assert client.delete("/api/me/help/").json() == {"help_done": []}
    user.refresh_from_db()
    assert user.help_done is None


def test_abhaken_in_ansicht_als_rolle_gesperrt(orgs, api):
    org = orgs["a"]
    chef = make_user("chef@example.org")
    give_role(chef, org, [MEMBERS_VIEW, ROLES_PREVIEW], name="Chef")
    rolle = Role.objects.create(organization=org, name="Leser", permissions=[MEMBERS_VIEW])
    client = api(chef)
    ok = client.post(f"/api/orgs/{org.pk}/ansicht/", {"role": rolle.pk}, content_type=JSON)
    assert ok.status_code == 200
    assert client.post("/api/me/help/start.profile/").status_code == 403
    assert client.get(f"/api/orgs/{org.pk}/help/").status_code == 200
