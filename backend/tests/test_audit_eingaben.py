"""Regressionstests zum Datenaudit vom 25.10.2026: Feldstrukturen (DS03), veraltete
Bearbeitungsstände (K02)."""

from types import SimpleNamespace

import pytest

from core.tenancy import tenant_context
from customfields.models import FieldValue
from finance.models import Category
from finance.serializers import CategorySerializer
from finance.views import CategoryViewSet
from members.models import ContactDetails, Person

from .test_m2_members import admit, make_types

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def types(orgs):
    return make_types(orgs["a"])


@pytest.fixture
def award(api, orgs, types, board_a):
    """Wiederholbares Feld mit einem ausgefüllten Wert."""
    c = api(board_a)
    base = f"/api/orgs/{orgs['a'].pk}"
    field = c.post(
        f"{base}/fields/",
        {
            "label": "Auszeichnung",
            "repeatable": True,
            "subfields": [
                {"label": "Bezeichnung", "type": "text"},
                {"label": "Datum", "type": "date"},
            ],
        },
        content_type=JSON,
    ).json()
    member = admit(c, orgs["a"], types["aktiv"]).json()
    resp = c.put(
        f"{base}/members/{member['id']}/fields/",
        {"values": {str(field["id"]): [{"bezeichnung": "Nadel", "datum": "2020-05-01"}]}},
        content_type=JSON,
    )
    assert resp.status_code == 200, resp.json()
    return {"c": c, "base": base, "field": field, "member": member}


def subfields(*items):
    return [{"key": k, "label": label, "type": t} for k, label, t in items]


class TestFeldstruktur:
    def test_ds03_benutztes_unterfeld_nicht_still_entfernen(self, award):
        c, base, field = award["c"], award["base"], award["field"]
        url = f"{base}/fields/{field['id']}/"
        resp = c.patch(
            url, {"subfields": subfields(("bezeichnung", "Bezeichnung", "text"))}, content_type=JSON
        )
        assert resp.status_code == 400
        assert "Datum" in str(resp.json())
        assert FieldValue.objects.get().value == [{"bezeichnung": "Nadel", "datum": "2020-05-01"}]

    def test_ds03_entfernen_samt_werten_nach_bestaetigung(self, award):
        c, base, field = award["c"], award["base"], award["field"]
        url = f"{base}/fields/{field['id']}/?mit_werten=1"
        resp = c.patch(
            url, {"subfields": subfields(("bezeichnung", "Bezeichnung", "text"))}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        assert FieldValue.objects.get().value == [{"bezeichnung": "Nadel"}]

    def test_ds03_umbenennen_und_neues_unterfeld_erlaubt(self, award):
        c, base, field = award["c"], award["base"], award["field"]
        resp = c.patch(
            f"{base}/fields/{field['id']}/",
            {
                "subfields": subfields(
                    ("bezeichnung", "Name der Auszeichnung", "text"),
                    ("datum", "Verliehen am", "date"),
                )
                + [{"label": "Ort", "type": "text"}]
            },
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        # Nächstes Speichern behält die Werte
        resp = c.put(
            f"{base}/members/{award['member']['id']}/fields/",
            {"values": {str(field["id"]): FieldValue.objects.get().value}},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        assert FieldValue.objects.get().value == [
            {"bezeichnung": "Nadel", "datum": "2020-05-01", "ort": None}
        ]

    def test_ds03_typ_eines_benutzten_unterfelds_bleibt(self, award):
        c, base, field = award["c"], award["base"], award["field"]
        resp = c.patch(
            f"{base}/fields/{field['id']}/",
            {
                "subfields": subfields(
                    ("bezeichnung", "Bezeichnung", "text"), ("datum", "Datum", "number")
                )
            },
            content_type=JSON,
        )
        assert resp.status_code == 400

    def test_ds03_wiederholbar_umstellen_nur_ohne_werte(self, award):
        c, base, field = award["c"], award["base"], award["field"]
        resp = c.patch(
            f"{base}/fields/{field['id']}/",
            {"repeatable": False, "field_type": "text"},
            content_type=JSON,
        )
        assert resp.status_code == 400
        FieldValue.objects.all().delete()
        resp = c.patch(
            f"{base}/fields/{field['id']}/",
            {"repeatable": False, "field_type": "text"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()


class TestVeralteteStaende:
    def test_k02_veraltete_instanz_ueberschreibt_andere_felder_nicht(self, orgs, board_a):
        club = orgs["a"]
        with tenant_context(club.pk):
            cat = Category.objects.create(organization=club, name="Spenden", kind="income")
            stale = Category.objects.get(pk=cat.pk)
            # Jemand anderes archiviert die Kategorie in der Zwischenzeit
            Category.objects.filter(pk=cat.pk).update(is_active=False)
            view = CategoryViewSet()
            view.org = club
            view.request = SimpleNamespace(user=board_a)
            ser = CategorySerializer(
                stale, data={"name": "Spenden allgemein"}, partial=True, context={"org": club}
            )
            assert ser.is_valid(), ser.errors
            view.perform_update(ser)
            cat.refresh_from_db()
        assert cat.name == "Spenden allgemein"
        assert cat.is_active is False

    def test_k02_kontakt_teilweise_aendern(self, api, orgs, types, board_a):
        c = api(board_a)
        member = admit(c, orgs["a"], types["aktiv"]).json()
        url = f"/api/orgs/{orgs['a'].pk}/members/{member['id']}/"
        # Zwei Bearbeiter ändern je ein anderes Kontaktfeld
        assert c.patch(url, {"email": "neu@example.org"}, content_type=JSON).status_code == 200
        assert c.patch(url, {"phone": "0999"}, content_type=JSON).status_code == 200
        with tenant_context(orgs["a"].pk):
            contact = ContactDetails.objects.get(person__last_name="Muster")
            assert (contact.email, contact.phone, contact.city) == (
                "neu@example.org",
                "0999",
                "Musterstadt",
            )

    def test_k02_veraltete_person_im_mitglied(self, api, orgs, types, board_a):
        c = api(board_a)
        member = admit(c, orgs["a"], types["aktiv"]).json()
        url = f"/api/orgs/{orgs['a'].pk}/members/{member['id']}/"
        with tenant_context(orgs["a"].pk):
            Person.objects.filter(last_name="Muster").update(first_name="Erika Maria")
        assert c.patch(url, {"last_name": "Muster-Neu"}, content_type=JSON).status_code == 200
        with tenant_context(orgs["a"].pk):
            person = Person.objects.get(last_name="Muster-Neu")
        assert person.first_name == "Erika Maria"
