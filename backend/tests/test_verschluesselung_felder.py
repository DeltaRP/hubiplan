"""Verschlüsselte Felder (core/encfields.py): Kontakt, Mandate, IBAN, Zusatzfelder."""

import io

import pytest
from django.core.exceptions import FieldError
from django.core.management import call_command
from django.db import connection, transaction

from core import crypto
from core.models import DataKey
from core.tenancy import rls_bypass
from members.models import ContactDetails

from .factories import make_member


def _raw(table: str, column: str, pk: int):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {column} FROM {table} WHERE id = %s", [pk])  # noqa: S608
        return cursor.fetchone()[0]


@pytest.mark.django_db
class TestKontakt:
    def test_in_der_datenbank_nur_chiffrat(self, orgs):
        m = make_member(orgs["c"], "Erika", "Muster", email="erika@example.org")
        with rls_bypass():
            contact = ContactDetails.objects.get(person=m.person)
        roh = _raw("members_contactdetails", "email", contact.pk)
        assert roh.startswith("enc1:")
        assert "erika" not in roh
        assert _raw("members_contactdetails", "street", contact.pk).startswith("enc1:")
        assert _raw("members_contactdetails", "postal_code", contact.pk) == "12345"
        assert contact.email == "erika@example.org"
        assert contact.street == "Lindenweg 4"

    def test_schluessel_des_verbandsbereichs(self, orgs):
        make_member(orgs["a"], "Anna", "Bund")
        # Gemeinsamer Kontakt gehört zum Verbandsbereich (Dachverband)
        assert DataKey.objects.filter(organization=orgs["federation"]).exists()

    def test_abfragen_auf_verschluesselte_felder_scheitern_laut(self, orgs):
        make_member(orgs["c"], "Erika", "Muster")
        with rls_bypass():
            # Je ein eigener Block: Ein Fehler mitten in update() verdirbt sonst die Transaktion
            with pytest.raises(FieldError), transaction.atomic():
                list(ContactDetails.objects.filter(email__icontains="erika"))
            with pytest.raises(FieldError), transaction.atomic():
                list(ContactDetails.objects.filter(email="erika@example.org"))
            with pytest.raises(FieldError), transaction.atomic():
                ContactDetails.objects.update(phone="0123")
            # Leeren geht
            ContactDetails.objects.update(phone="")
            assert ContactDetails.objects.filter(phone="").exists()

    def test_suche_nach_email_in_der_mitgliederliste(self, api, orgs, board_c):
        make_member(orgs["c"], "Erika", "Muster", email="erika.sonder@example.org")
        make_member(orgs["c"], "Hans", "Anders", email="hans@example.org")
        r = api(board_c).get(f"/api/orgs/{orgs['c'].pk}/members/?suche=sonder")
        assert r.status_code == 200
        names = [row["last_name"] for row in r.json()["results"]]
        assert names == ["Muster"]


@pytest.mark.django_db
class TestBestand:
    def test_verschluesseln_und_rueckweg(self, orgs):
        m = make_member(orgs["c"], "Erika", "Muster", email="erika@example.org")
        with rls_bypass():
            contact = ContactDetails.objects.get(person=m.person)
        # Stand von vor der Umstellung: Klartext in der Spalte
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE members_contactdetails SET email = 'alt@example.org' WHERE id = %s",
                [contact.pk],
            )
        with rls_bypass():
            assert ContactDetails.objects.get(pk=contact.pk).email == "alt@example.org"
        out = io.StringIO()
        call_command("daten_verschluesseln", stdout=out)
        assert _raw("members_contactdetails", "email", contact.pk).startswith("enc1:")
        with rls_bypass():
            assert ContactDetails.objects.get(pk=contact.pk).email == "alt@example.org"
        call_command("daten_verschluesseln", "--entschluesseln", stdout=out)
        assert _raw("members_contactdetails", "email", contact.pk) == "alt@example.org"
        assert _raw("members_contactdetails", "street", contact.pk) == "Lindenweg 4"

    def test_verein_geloescht_wert_leer(self, orgs):
        m = make_member(orgs["c"], "Erika", "Muster")
        DataKey.objects.filter(organization=orgs["c"]).delete()
        crypto.reset()
        with rls_bypass():
            assert ContactDetails.objects.get(person=m.person).email == ""
