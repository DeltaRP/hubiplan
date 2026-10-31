"""Einheiten: Untereinheiten (früher Abteilungen) stehen in der Organisationstabelle."""

import pytest

from core.tenancy import tenant_context
from organizations.models import Department, Organization

JSON = "application/json"


@pytest.mark.django_db
class TestUntereinheit:
    def test_abteilung_ist_einheit(self, orgs):
        club = orgs["a"]
        with tenant_context(club.pk):
            zug = Department.objects.create(organization=club, name="Herolde", founding_year=1925)
        unit = Organization.objects.get(pk=zug.pk)
        assert unit.type == Organization.Type.UNIT
        assert unit.parent == club
        assert unit.organization == club
        assert unit.label == club.department_label
        # Genauigkeit leer: wie die übergeordnete Einheit
        assert unit.date_precision == ""
        assert unit.effective_date_precision == club.date_precision

    def test_nur_untereinheiten_im_proxy(self, orgs):
        assert not Department.objects.filter(pk=orgs["a"].pk).exists()
        assert set(Department.objects.values_list("type", flat=True)) <= {"unit"}

    def test_bezeichnung_folgt_der_vorgabe(self, orgs):
        club = orgs["a"]
        zug = Department.objects.create(organization=club, name="Herolde", founding_year=1925)
        club.department_label, club.department_label_plural = "Zug", "Züge"
        club.department_label_gender = "m"
        club.save()
        zug.refresh_from_db()
        assert (zug.label, zug.label_plural, zug.label_gender) == ("Zug", "Züge", "m")

    def test_neue_einheiten_haben_bezeichnung(self, orgs):
        assert orgs["a"].label == "Verein"
        assert orgs["federation"].label == "Dachverband"

    def test_name_je_einheit_eindeutig(self, api, orgs, board_a):
        c = api(board_a)
        base = f"/api/orgs/{orgs['a'].pk}/departments/"
        assert (
            c.post(base, {"name": "Herolde", "founding_year": 1925}, content_type=JSON).status_code
            == 201
        )
        assert (
            c.post(base, {"name": "herolde", "founding_year": 1925}, content_type=JSON).status_code
            == 400
        )
        # Gleicher Name in einem anderen Verein ist erlaubt
        assert Department.objects.create(
            organization=orgs["b"], name="Herolde", founding_year=1925
        ).pk

    def test_kein_zugriff_ueber_einheiten_api(self, api, orgs, board_a):
        """Untereinheiten sind (noch) keine eigenen Arbeitsbereiche."""
        zug = Department.objects.create(organization=orgs["a"], name="Herolde", founding_year=1925)
        assert api(board_a).get(f"/api/orgs/{zug.pk}/").status_code == 404
