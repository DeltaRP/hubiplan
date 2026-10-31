"""Ämter in Untereinheiten: Mitglied bekommt eine Rolle ohne Konto und ohne E-Mail."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core import mail

from core.tenancy import tenant_context
from organizations.models import Department, DepartmentRole

from .factories import make_member

JSON = "application/json"


@pytest.fixture
def zug(orgs):
    with tenant_context(orgs["a"].pk):
        return Department.objects.create(organization=orgs["a"], name="Jäger", founding_year=1950)


def test_amt_ohne_konto_und_ohne_mail(api, orgs, zug, board_a):
    erika = make_member(orgs["a"], "Erika", "Muster", departments=[zug])
    with tenant_context(orgs["a"].pk):
        role = DepartmentRole.objects.create(department=zug, name="Fahnenträger")
    users_before = get_user_model().objects.count()
    c = api(board_a)
    base = f"/api/orgs/{orgs['a'].pk}"
    resp = c.post(
        f"{base}/members/{erika.pk}/department-roles/",
        {"role": role.pk, "valid_from": "2026-01-01"},
        content_type=JSON,
    )
    assert resp.status_code == 201, resp.content
    assert get_user_model().objects.count() == users_before
    assert mail.outbox == []

    # Die Seite der Untereinheit nennt die Zuordnung (zum Beenden) und den Beginn
    deps = c.get(f"{base}/departments/").json()
    holder = next(d for d in deps if d["id"] == zug.pk)["roles"][0]["holders"][0]
    assert holder == {
        "id": resp.json()["id"],
        "membership": erika.pk,
        "name": "Erika Muster",
        "valid_from": "2026-01-01",
    }
    end = c.patch(
        f"{base}/members/{erika.pk}/department-roles/{holder['id']}/",
        {"valid_until": "2026-06-30"},
        content_type=JSON,
    )
    assert end.status_code == 200, end.content
    assert mail.outbox == []
