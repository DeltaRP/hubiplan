"""UI/UX-Audit: Aufnahme ohne E-Mail, Protokoll und Postausgang mit Suche und Seiten."""

import pytest
from django.test import override_settings

from audit.models import AuditEntry
from outbox.models import OutgoingMail

from .test_m2_members import admit, make_types

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def types(orgs):
    return {key: make_types(orgs[key]) for key in ("a", "b")}


class TestAufnahmeOhneEmail:
    def test_aufnahme_ohne_email(self, api, orgs, types, board_a):
        resp = admit(api(board_a), orgs["a"], types["a"]["aktiv"], email="")
        assert resp.status_code == 201, resp.json()
        assert resp.json()["contact"]["email"] == ""

    def test_email_entfernen(self, api, orgs, types, board_a):
        member = admit(api(board_a), orgs["a"], types["a"]["aktiv"]).json()
        resp = api(board_a).patch(
            f"/api/orgs/{orgs['a'].pk}/members/{member['id']}/",
            {"email": ""},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["contact"]["email"] == ""

    def test_anschrift_bleibt_pflicht(self, api, orgs, types, board_a):
        resp = admit(api(board_a), orgs["a"], types["a"]["aktiv"], email="", street="")
        assert resp.status_code == 400
        assert "street" in resp.json()


def _entries(org, n):
    AuditEntry.objects.bulk_create(
        AuditEntry(
            organization=org,
            user_email="vorstand@example.org",
            action="update",
            object_type="Mitglied",
            object_id=str(i),
            object_repr=f"Person {i:03d}",
        )
        for i in range(n)
    )


class TestProtokoll:
    def test_blaettern_ueber_200(self, api, orgs, board_a):
        _entries(orgs["a"], 230)
        c = api(board_a)
        url = f"/api/orgs/{orgs['a'].pk}/audit/"
        first = c.get(url).json()
        assert first["count"] == 230
        assert first["pages"] == 5
        assert len(first["results"]) == 50
        last = c.get(url, {"seite": 5}).json()
        assert len(last["results"]) == 30
        assert last["page"] == 5

    def test_suche_findet_alten_eintrag(self, api, orgs, board_a):
        _entries(orgs["a"], 230)
        data = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/audit/", {"q": "Person 001"}).json()
        assert data["count"] == 1
        assert data["results"][0]["object_repr"] == "Person 001"

    def test_papierkorb_und_zeitraum(self, api, orgs, board_a):
        _entries(orgs["a"], 3)
        AuditEntry.objects.create(
            organization=orgs["a"],
            action="delete",
            object_type="Mitglied",
            object_id="x",
            object_repr="Gelöscht",
        )
        c = api(board_a)
        url = f"/api/orgs/{orgs['a'].pk}/audit/"
        assert c.get(url, {"aktion": "delete"}).json()["count"] == 1
        assert c.get(url, {"bis": "2000-01-01"}).json()["count"] == 0
        assert c.get(url, {"von": "2000-01-01"}).json()["count"] == 4


class TestPostausgang:
    @override_settings(EMAIL_BACKEND="outbox.backend.OutboxBackend")
    def test_suche_und_seiten(self, api, orgs, board_a, django_user_model):
        OutgoingMail.objects.bulk_create(
            OutgoingMail(
                organization=orgs["a"], to=f"m{i}@example.org", subject=f"Rechnung {i}", body="x"
            )
            for i in range(120)
        )
        OutgoingMail.objects.create(organization=orgs["b"], to="b@example.org", subject="B")
        c = api(board_a)
        url = f"/api/orgs/{orgs['a'].pk}/outbox/"
        data = c.get(url).json()
        assert data["count"] == 120 and data["pages"] == 3
        assert c.get(url, {"q": "m7@example.org"}).json()["count"] == 1
        assert c.get(url, {"status": "failed"}).json()["count"] == 0
        admin = django_user_model.objects.create_superuser("admin@example.org", "x")
        platform = api(admin).get("/api/platform/outbox/", {"q": "b@example"}).json()
        assert platform["count"] == 1
        assert platform["results"][0]["subject"] == "B"
