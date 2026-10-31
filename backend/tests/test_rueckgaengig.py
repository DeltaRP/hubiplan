"""Rückgängig, Wiederherstellen und Papierkorb (Änderungspakete)."""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from changes.models import ChangeRecord, ChangeSet
from changes.purge import purge_old
from core.tenancy import rls_bypass, tenant_context
from events.models import Event, EventCategory
from members.models import ContactDetails, Membership, MemberType, Person

from .factories import give_role, make_user

JSON = "application/json"


@pytest.fixture
def types(orgs):
    with tenant_context(orgs["a"].pk):
        return {
            "aktiv": MemberType.objects.create(organization=orgs["a"], name="aktiv", active=True)
        }


def admit(client, org, member_type):
    return client.post(
        f"/api/orgs/{org.pk}/members/admit/",
        {
            "last_name": "Muster",
            "first_name": "Erika",
            "birth_date": "1980-05-17",
            "email": "erika@example.org",
            "street": "Lindenweg 4",
            "postal_code": "12345",
            "city": "Musterstadt",
            "entry_date": "2015-03-01",
            "member_type": member_type.pk,
        },
        content_type=JSON,
    )


def undo(client, org, change_set, **data):
    return client.post(f"/api/orgs/{org.pk}/changes/{change_set}/undo/", data, content_type=JSON)


@pytest.fixture
def member(api, orgs, types, board_a):
    return admit(api(board_a), orgs["a"], types["aktiv"]).json()


def member_url(orgs, member):
    return f"/api/orgs/{orgs['a'].pk}/members/{member['id']}/"


class TestAendern:
    def test_rueckgaengig_und_wiederherstellen(self, api, orgs, member, board_a):
        c = api(board_a)
        resp = c.patch(member_url(orgs, member), {"city": "Neustadt"}, content_type=JSON)
        assert resp["X-Change-Undoable"] == "1"
        assert resp["X-Change-Kind"] == "update"
        from urllib.parse import unquote

        assert "Muster, Erika" in unquote(resp["X-Change-Label"])
        change_set = resp["X-Change-Set"]

        resp = undo(c, orgs["a"], change_set)
        assert resp.status_code == 200, resp.json()
        assert c.get(member_url(orgs, member)).json()["contact"]["city"] == "Musterstadt"
        redo_set = resp.json()["change_set"]
        assert resp["X-Change-Set"] == redo_set

        # Wiederherstellen = Rückgängig des Rückgängig
        resp = undo(c, orgs["a"], redo_set)
        assert resp.status_code == 200
        assert c.get(member_url(orgs, member)).json()["contact"]["city"] == "Neustadt"
        with tenant_context(orgs["a"].pk):
            assert ChangeSet.objects.get(pk=change_set).reverted_by is None
            assert ChangeSet.objects.get(pk=redo_set).reverted_by is not None

    def test_nicht_zweimal(self, api, orgs, member, board_a):
        c = api(board_a)
        change_set = c.patch(member_url(orgs, member), {"city": "Neustadt"}, content_type=JSON)[
            "X-Change-Set"
        ]
        assert undo(c, orgs["a"], change_set).status_code == 200
        resp = undo(c, orgs["a"], change_set)
        assert resp.status_code == 409
        assert resp.json()["can_force"] is False

    def test_inzwischen_geaendert_nur_mit_trotzdem(self, api, orgs, member, board_a):
        c = api(board_a)
        first = c.patch(member_url(orgs, member), {"city": "Neustadt"}, content_type=JSON)[
            "X-Change-Set"
        ]
        c.patch(member_url(orgs, member), {"city": "Altstadt"}, content_type=JSON)
        resp = undo(c, orgs["a"], first)
        assert resp.status_code == 409
        assert resp.json()["can_force"] is True
        assert "erneut geändert" in resp.json()["problems"][0]
        assert c.get(member_url(orgs, member)).json()["contact"]["city"] == "Altstadt"

        assert undo(c, orgs["a"], first, force=True).status_code == 200
        assert c.get(member_url(orgs, member)).json()["contact"]["city"] == "Musterstadt"

    def test_protokoll_zeigt_rueckgaengig(self, api, orgs, member, board_a):
        c = api(board_a)
        change_set = c.patch(member_url(orgs, member), {"city": "Neustadt"}, content_type=JSON)[
            "X-Change-Set"
        ]
        entry = c.get(f"/api/orgs/{orgs['a'].pk}/audit/").json()["results"][0]
        assert entry["undo"] == {
            "change_set": change_set,
            "state": "possible",
            "reason": "",
            "is_undo": False,
        }
        undo(c, orgs["a"], change_set)
        entries = c.get(f"/api/orgs/{orgs['a'].pk}/audit/").json()["results"]
        assert entries[0]["undo"]["is_undo"] is True
        assert entries[0]["changes"]["Ort"] == ["Neustadt", "Musterstadt"]
        assert {e["undo"]["state"] for e in entries if e["undo"]} >= {"done"}
        # Auch im Verlauf der Mitgliedsakte
        history = c.get(member_url(orgs, member) + "history/").json()
        assert history[0]["undo"]["is_undo"] is True


class TestAnlegenUndLoeschen:
    def test_aufnahme_rueckgaengig(self, api, orgs, types, board_a):
        c = api(board_a)
        resp = admit(c, orgs["a"], types["aktiv"])
        assert resp.status_code == 201
        assert resp["X-Change-Undoable"] == "1", resp.get("X-Change-Undoable")
        assert "create" in resp["X-Change-Kind"]
        resp = undo(c, orgs["a"], resp["X-Change-Set"])
        assert resp.status_code == 200, resp.json()
        with rls_bypass():
            assert not Membership.objects.exists()
            assert not Person.objects.exists()
            assert not ContactDetails.objects.exists()

        # Wiederherstellen legt alles mit denselben IDs wieder an
        assert undo(c, orgs["a"], resp.json()["change_set"]).status_code == 200
        with rls_bypass():
            assert Membership.objects.count() == 1
            assert ContactDetails.objects.count() == 1

    def test_termin_loeschen_und_wiederherstellen(self, api, orgs, board_a):
        orgs["a"].enabled_modules = ["members", "events"]
        orgs["a"].save()
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}/events/"
        start = timezone.now().replace(microsecond=0) + datetime.timedelta(days=3)
        event = c.post(
            base,
            {
                "title": "Versammlung",
                "starts_at": start.isoformat(),
                "ends_at": (start + datetime.timedelta(hours=2)).isoformat(),
            },
            content_type=JSON,
        )
        assert event.status_code == 201, event.json()
        event_id = event.json()["id"]
        resp = c.delete(f"{base}{event_id}/")
        assert resp.status_code == 204
        assert resp["X-Change-Kind"] == "delete"
        assert undo(c, orgs["a"], resp["X-Change-Set"]).status_code == 200
        with tenant_context(orgs["a"].pk):
            restored = Event.objects.get(pk=event_id)
        assert restored.title == "Versammlung"
        assert restored.starts_at == start

    def test_termin_anlegen_rueckgaengig_mit_zeitzone(self, api, orgs, board_a):
        """Eingabe mit Ortszeit (+01:00), gelesen in UTC: gilt nicht als „inzwischen geändert“."""
        orgs["a"].enabled_modules = ["members", "events"]
        orgs["a"].save()
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}/events/"
        resp = c.post(
            base,
            {"title": "Versammlung", "starts_at": "2026-12-01T19:00:00+01:00"},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        assert undo(c, orgs["a"], resp["X-Change-Set"]).status_code == 200
        with tenant_context(orgs["a"].pk):
            assert not Event.objects.filter(pk=resp.json()["id"]).exists()

    def test_kategorie_loeschen_stellt_verweise_wieder_her(self, api, orgs, board_a):
        orgs["a"].enabled_modules = ["members", "events"]
        orgs["a"].save()
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}/events/"
        cat = c.post(f"{base}categories/", {"name": "Fest", "color": "#123456"}, content_type=JSON)
        assert cat.status_code == 201, cat.json()
        start = timezone.now() + datetime.timedelta(days=3)
        event_id = c.post(
            base,
            {
                "title": "Sommerfest",
                "starts_at": start.isoformat(),
                "ends_at": (start + datetime.timedelta(hours=2)).isoformat(),
                "category": cat.json()["id"],
            },
            content_type=JSON,
        ).json()["id"]
        resp = c.delete(f"{base}categories/{cat.json()['id']}/")
        assert resp.status_code == 204
        assert resp["X-Change-Undoable"] == "1"
        with tenant_context(orgs["a"].pk):
            assert Event.objects.get(pk=event_id).category_id is None
        assert undo(c, orgs["a"], resp["X-Change-Set"]).status_code == 200
        with tenant_context(orgs["a"].pk):
            assert EventCategory.objects.filter(pk=cat.json()["id"]).exists()
            assert Event.objects.get(pk=event_id).category_id == cat.json()["id"]

    def test_anlegen_nicht_rueckgaengig_wenn_spaeter_daten_daran(self, api, orgs, types, board_a):
        c = api(board_a)
        dept = c.post(
            f"/api/orgs/{orgs['a'].pk}/departments/",
            {"name": "1. Zug", "founding_year": 1950},
            content_type=JSON,
        )
        assert dept.status_code == 201, dept.json()
        member = admit(c, orgs["a"], types["aktiv"]).json()
        resp = c.post(
            f"/api/orgs/{orgs['a'].pk}/members/{member['id']}/departments/",
            {"department": dept.json()["id"], "valid_from": "2020-01-01"},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        resp = undo(c, orgs["a"], dept["X-Change-Set"], force=True)
        assert resp.status_code == 409
        assert resp.json()["can_force"] is False


class TestGrenzen:
    def test_konto_anlegen_rueckgaengig(self, api, orgs, board_a):
        orgs["a"].enabled_modules = ["members", "finance"]
        orgs["a"].save()
        c = api(board_a)
        resp = c.post(
            f"/api/orgs/{orgs['a'].pk}/finance/accounts/",
            {"name": "Kasse", "kind": "cash", "opening_balance": "0", "opening_date": "2025-01-01"},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        assert resp["X-Change-Undoable"] == "1"
        assert undo(c, orgs["a"], resp["X-Change-Set"]).status_code == 200

    def test_fremde_aenderung_braucht_protokollrecht(self, api, orgs, member, board_a):
        change_set = api(board_a).patch(
            member_url(orgs, member), {"city": "Neustadt"}, content_type=JSON
        )["X-Change-Set"]
        editor = make_user("schriftfuehrer@example.org")
        give_role(editor, orgs["a"], ["members.view", "members.edit"], name="Schriftführer")
        resp = undo(api(editor), orgs["a"], change_set)
        assert resp.status_code == 403
        # Eigene Änderungen darf er zurücknehmen
        own = api(editor).patch(member_url(orgs, member), {"city": "Altstadt"}, content_type=JSON)
        assert undo(api(editor), orgs["a"], own["X-Change-Set"]).status_code == 200

    def test_anderer_verein_sieht_paket_nicht(self, api, orgs, member, board_a, board_b):
        change_set = api(board_a).patch(
            member_url(orgs, member), {"city": "Neustadt"}, content_type=JSON
        )["X-Change-Set"]
        assert undo(api(board_b), orgs["b"], change_set).status_code == 404

    def test_nach_30_tagen_geloescht(self, api, orgs, member, board_a):
        api(board_a).patch(member_url(orgs, member), {"city": "Neustadt"}, content_type=JSON)
        with rls_bypass():
            assert ChangeSet.objects.exists()
        purge_old(timezone.now() + datetime.timedelta(days=31))
        with rls_bypass():
            assert not ChangeSet.objects.exists()
            assert not ChangeRecord.objects.exists()

    def test_loeschfrist_entfernt_pakete_der_person(self, api, orgs, member, board_a):
        from members.workflows import purge_membership

        api(board_a).patch(member_url(orgs, member), {"city": "Neustadt"}, content_type=JSON)
        with tenant_context(orgs["a"].pk):
            purge_membership(Membership.objects.get(pk=member["id"]))
        with rls_bypass():
            assert not ChangeRecord.objects.filter(person_id=member["person_id"]).exists()

    def test_ohne_anfrage_nichts_mitgeschrieben(self, orgs, types):
        with tenant_context(orgs["a"].pk):
            MemberType.objects.create(organization=orgs["a"], name="passiv")
        with rls_bypass():
            assert not ChangeRecord.objects.exists()


class TestBeschriftung:
    """Liste der letzten Schritte: lesbare Objektarten (Ralf 31.10.)."""

    def _label(self, org, object_type, repr_="Hubertus"):
        from audit.models import AuditEntry
        from changes.middleware import label

        with rls_bypass():
            cs = ChangeSet.objects.create(organization=org)
            AuditEntry.objects.create(
                organization=org,
                action="update",
                object_type=object_type,
                object_id="1",
                object_repr=repr_,
                change_set=cs.pk,
            )
            return label(cs)

    def test_technischer_name_wird_lesbar(self, orgs):
        assert self._label(orgs["a"], "imprint") == "Impressum „Hubertus“ geändert"

    def test_eigene_bezeichnung_der_untereinheit(self, orgs):
        org = orgs["a"]
        org.department_label = "Zug"
        org.department_label_plural = "Züge"
        org.department_label_gender = "m"
        org.save()
        assert self._label(org, "Abteilung", "Jäger") == "Zug „Jäger“ geändert"
