"""Geburtsdatum verschlüsselt (core/encfields.EncryptedDateField)."""

import datetime
import io

import pytest
from django.core.exceptions import FieldError
from django.core.management import call_command
from django.db import connection, transaction

from core.tenancy import rls_bypass
from members import services
from members.models import Person

from .factories import make_member

GEBOREN = datetime.date(1980, 5, 17)


def _raw(pk: int):
    with connection.cursor() as cursor:
        cursor.execute("SELECT birth_date FROM members_person WHERE id = %s", [pk])
        return cursor.fetchone()[0]


@pytest.mark.django_db
class TestGeburtsdatum:
    def test_in_der_datenbank_nur_chiffrat(self, orgs):
        m = make_member(orgs["c"], "Erika", "Muster", birth_date=GEBOREN)
        roh = _raw(m.person_id)
        assert roh.startswith("enc1:")
        assert "1980" not in roh
        with rls_bypass():
            assert Person.objects.get(pk=m.person_id).birth_date == GEBOREN

    def test_abfragen_scheitern_laut(self, orgs):
        make_member(orgs["c"], "Erika", "Muster", birth_date=GEBOREN)
        with rls_bypass():
            with pytest.raises(FieldError), transaction.atomic():
                list(Person.objects.filter(birth_date=GEBOREN))
            with pytest.raises(FieldError), transaction.atomic():
                list(Person.objects.filter(birth_date__year=1980))
            with pytest.raises(FieldError), transaction.atomic():
                list(Person.objects.filter(birth_date__lte=GEBOREN))

    def test_dubletten_auch_bei_nur_geburtsjahr(self, orgs):
        m = make_member(orgs["c"], "Erika", "Muster", birth_date=GEBOREN)
        with rls_bypass():
            assert [p.pk for p in services.find_duplicates(orgs["c"], "Muster", "X", GEBOREN)] == [
                m.person_id
            ]
            assert (
                services.find_duplicates(orgs["c"], "Muster", "X", datetime.date(1981, 1, 1)) == []
            )
            person = Person.objects.get(pk=m.person_id)
            person.birth_date = datetime.date(1980, 1, 1)
            person.birth_year_only = True
            person.save()
            found = services.find_duplicates(orgs["c"], "Muster", "X", GEBOREN)
            assert [p.pk for p in found] == [m.person_id]

    def test_genaue_treffer(self, orgs):
        m = make_member(orgs["c"], "Erika", "Muster", birth_date=GEBOREN)
        scope = services.scope_for(orgs["c"]).pk
        with rls_bypass():
            found = services.persons_matching(scope, " muster", "ERIKA", GEBOREN, limit=5)
            assert [p.pk for p in found] == [m.person_id]
            assert services.persons_matching(scope, "Muster", "Erika", None, limit=5) == []

    def test_bestand_verschluesseln_und_rueckweg(self, orgs):
        m = make_member(orgs["c"], "Erika", "Muster", birth_date=GEBOREN)
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE members_person SET birth_date = '1980-05-17' WHERE id = %s", [m.person_id]
            )
        with rls_bypass():
            assert Person.objects.get(pk=m.person_id).birth_date == GEBOREN
        call_command("daten_verschluesseln", stdout=io.StringIO())
        assert _raw(m.person_id).startswith("enc1:")
        call_command("daten_verschluesseln", "--entschluesseln", stdout=io.StringIO())
        assert _raw(m.person_id) == "1980-05-17"
        with rls_bypass():
            assert Person.objects.get(pk=m.person_id).birth_date == GEBOREN

    def test_mitgliederliste_nach_geburtsdatum(self, api, orgs, board_c):
        make_member(orgs["c"], "Alt", "Aa", birth_date=datetime.date(1950, 1, 1))
        make_member(orgs["c"], "Jung", "Bb", birth_date=datetime.date(2001, 1, 1))
        make_member(orgs["c"], "Mitte", "Cc", birth_date=datetime.date(1975, 6, 1))
        base = f"/api/orgs/{orgs['c'].pk}/members/"
        r = api(board_c).get(base + "?sortierung=geburtsdatum")
        assert [row["last_name"] for row in r.json()["results"]] == ["Aa", "Cc", "Bb"]
        r = api(board_c).get(base + "?sortierung=-geburtsdatum")
        assert [row["last_name"] for row in r.json()["results"]] == ["Bb", "Cc", "Aa"]
