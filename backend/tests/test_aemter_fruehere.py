"""Mitglieder › Ämter: frühere Amtsinhaber ohne Konto und ohne Mitgliedschaft,
jahresgenau erfassen und importieren (Ralf 2026-10-31). Alle Namen erfunden."""

import datetime
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from openpyxl import Workbook

from access.models import Role, RoleAssignment
from access.permissions import permissions_in
from organizations.models import Department
from website.public import SiteView

from .factories import make_member

pytestmark = pytest.mark.django_db(transaction=True)

THIS_YEAR = timezone.localdate().year


def url(org, rest=""):
    return f"/api/orgs/{org.pk}/offices/{rest}"


def xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile("aemter.xlsx", buf.getvalue())


@pytest.fixture
def chair(orgs):
    return Role.objects.create(organization=orgs["a"], name="1. Vorsitzender", in_chronicle=True)


@pytest.fixture
def zug(orgs):
    unit = Department.objects.create(organization=orgs["a"], parent=orgs["a"], name="Zug 1")
    role = Role.all_objects.create(organization=orgs["a"], department=unit, name="Zugführer")
    return unit, role


class TestErfassen:
    def test_anlegen_aendern_loeschen(self, orgs, board_a, api, chair):
        c = api(board_a)
        resp = c.post(
            url(orgs["a"]),
            {"role": chair.pk, "name": "Wilhelm Vorzeit", "from_year": 1955, "until_year": 1972},
            "application/json",
        )
        assert resp.status_code == 201, resp.content
        entry = RoleAssignment.all_objects.get(name="Wilhelm Vorzeit")
        assert entry.user is None and entry.membership is None
        assert entry.valid_from == datetime.date(1955, 1, 1)
        assert entry.valid_until == datetime.date(1972, 1, 1)
        assert entry.is_former_entry and not entry.is_active

        roles = c.get(url(orgs["a"])).json()
        holders = next(r for r in roles if r["id"] == chair.pk)["holders"]
        assert holders == [
            {
                "id": entry.pk,
                "role": chair.pk,
                "name": "Wilhelm Vorzeit",
                "person": None,
                "from_year": 1955,
                "until_year": 1972,
                "current": False,
                "former_entry": True,
            }
        ]

        resp = c.put(
            url(orgs["a"], f"{entry.pk}/"),
            {"role": chair.pk, "name": "Wilhelm Vorzeit", "from_year": 1956, "until_year": 1972},
            "application/json",
        )
        assert resp.status_code == 200, resp.content
        entry.refresh_from_db()
        assert entry.valid_from.year == 1956

        assert c.delete(url(orgs["a"], f"{entry.pk}/")).status_code == 204
        assert not RoleAssignment.all_objects.filter(pk=entry.pk).exists()

    def test_nur_freie_eintraege_aenderbar(self, orgs, board_a, api):
        """Konten ändert man unter Rollen, nicht hier."""
        own = RoleAssignment.objects.get(user=board_a)
        resp = api(board_a).delete(url(orgs["a"], f"{own.pk}/"))
        assert resp.status_code == 404

    def test_zeitraum_pruefen(self, orgs, board_a, api, chair):
        c = api(board_a)
        for data in (
            {"from_year": 1990},  # Endjahr fehlt
            {"from_year": 1990, "until_year": 1980},
            {"from_year": 1990, "until_year": THIS_YEAR + 1},
            {"from_year": THIS_YEAR + 1, "until_year": THIS_YEAR + 2},
        ):
            resp = c.post(
                url(orgs["a"]), {"role": chair.pk, "name": "A B", **data}, "application/json"
            )
            assert resp.status_code == 400, data
        resp = c.post(
            url(orgs["a"]),
            {"role": chair.pk, "name": "", "from_year": 1990, "until_year": 1991},
            "application/json",
        )
        assert resp.status_code == 400

    def test_fremde_rolle_und_fremdes_mitglied(self, orgs, board_a, api, chair):
        other = Role.objects.create(organization=orgs["b"], name="Vorsitz B")
        stranger = make_member(orgs["b"], "Fremd", "Person")
        c = api(board_a)
        resp = c.post(
            url(orgs["a"]),
            {"role": other.pk, "name": "A B", "from_year": 1990, "until_year": 1991},
            "application/json",
        )
        assert resp.status_code == 404
        resp = c.post(
            url(orgs["a"]),
            {"role": chair.pk, "person": stranger.person_id, "from_year": 1990, "until_year": 1991},
            "application/json",
        )
        assert resp.status_code == 400

    def test_ehemaliges_mitglied_verknuepfen(self, orgs, board_a, api, chair):
        otto = make_member(orgs["a"], "Otto", "Muster")
        resp = api(board_a).post(
            url(orgs["a"]),
            {"role": chair.pk, "person": otto.person_id, "from_year": 1980, "until_year": 1990},
            "application/json",
        )
        assert resp.status_code == 201, resp.content
        entry = RoleAssignment.all_objects.get(person=otto.person)
        assert entry.name == "Otto Muster"
        # In der Akte unter den Vorstandsrollen
        file = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/members/{otto.pk}/").json()
        assert [r["role_name"] for r in file["board_roles"]] == ["1. Vorsitzender"]

    def test_nicht_unter_rollen_und_ohne_rechte(self, orgs, board_a, api, chair):
        RoleAssignment.all_objects.create(
            organization=orgs["a"],
            role=chair,
            name="Wilhelm Vorzeit",
            valid_from=datetime.date(1955, 1, 1),
            valid_until=datetime.date(1972, 1, 1),
        )
        rows = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/assignments/").json()
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        assert all(r.get("user_email") for r in rows)
        assert permissions_in(board_a, orgs["a"])  # unverändert

    def test_lesen_nur_mit_recht(self, orgs, api, chair):
        from .factories import give_role, make_user

        viewer = make_user("leser@example.org")
        give_role(viewer, orgs["a"], permissions=["members.view"], name="Leser")
        c = api(viewer)
        assert c.get(url(orgs["a"])).status_code == 200
        resp = c.post(
            url(orgs["a"]),
            {"role": chair.pk, "name": "A B", "from_year": 1990, "until_year": 1991},
            "application/json",
        )
        assert resp.status_code == 403


class TestImport:
    def test_vorschau_und_uebernehmen(self, orgs, board_a, api, chair, zug):
        unit, zugfuehrer = zug
        otto = make_member(orgs["a"], "Otto", "Muster")
        file = xlsx(
            [
                ["Amt", "Zug", "Name", "von", "bis"],
                ["1. Vorsitzender", "", "Wilhelm Vorzeit", 1955, 1972],
                ["Zugführer", "Zug 1", "Muster, Otto", 1980, 1990],
                ["Ehrenvorsitzender", "", "Karl Alt", 1973, ""],
                ["1. Vorsitzender", "", "Kein Ende", 1990, THIS_YEAR + 3],
                ["Zugführer", "Zug 9", "Niemand", 1980, 1981],
            ]
        )
        c = api(board_a)
        resp = c.post(url(orgs["a"], "import/preview/"), {"file": file})
        assert resp.status_code == 200, resp.content
        data = resp.json()
        rows = data["rows"]
        assert rows[0]["role_id"] == chair.pk and not rows[0]["errors"]
        assert rows[1]["role_id"] == zugfuehrer.pk and rows[1]["unit_id"] == unit.pk
        assert rows[1]["person_id"] == otto.person_id
        assert rows[2]["until_year"] == 1973  # nur ein Jahr
        assert rows[3]["errors"] and rows[4]["errors"]
        assert data["new_roles"] == ["Ehrenvorsitzender"]
        assert not RoleAssignment.all_objects.filter(name__gt="").exists()

        chosen = [
            {
                "role": r["role"],
                "unit_id": r["unit_id"],
                "name": r["name"],
                "person_id": r["person_id"],
                "from_year": r["from_year"],
                "until_year": r["until_year"],
            }
            for r in rows[:3]
        ]
        resp = c.post(url(orgs["a"], "import/"), {"rows": chosen}, "application/json")
        assert resp.status_code == 201, resp.content
        assert resp.json() == {"created": 3, "roles_created": ["Ehrenvorsitzender"]}
        new_role = Role.objects.get(name="Ehrenvorsitzender")
        assert new_role.permissions == [] and not new_role.in_chronicle and not new_role.is_board
        held = RoleAssignment.all_objects.get(role=zugfuehrer)
        assert held.person_id == otto.person_id and held.membership_id is None

        # Gleiche Datei noch einmal: als vorhanden markiert
        again = c.post(
            url(orgs["a"], "import/preview/"),
            {
                "file": xlsx(
                    [
                        ["Amt", "Name", "von", "bis"],
                        ["1. Vorsitzender", "Wilhelm Vorzeit", 1955, 1972],
                    ]
                )
            },
        ).json()
        assert again["rows"][0]["duplicate"] is True

    def test_fehlende_spalten(self, orgs, board_a, api):
        file = xlsx([["Name", "bis"], ["A B", 1990]])
        resp = api(board_a).post(url(orgs["a"], "import/preview/"), {"file": file})
        assert resp.status_code == 400 and "Amt" in str(resp.json())


class TestWebseite:
    def test_aemter_mit_frueherem_inhaber(self, orgs, chair):
        from website.models import Website

        site = Website.objects.create(organization=orgs["a"])
        RoleAssignment.all_objects.create(
            organization=orgs["a"],
            role=chair,
            name="Wilhelm Vorzeit",
            valid_from=datetime.date(1955, 1, 1),
            valid_until=datetime.date(1972, 1, 1),
        )
        chairs = SiteView(site).chairs()
        assert chairs[0]["holders"][0]["name"] == "Wilhelm Vorzeit"
        assert chairs[0]["holders"][0]["current"] is False
        # Kein heutiger Vorstand
        assert not SiteView(site).board()
