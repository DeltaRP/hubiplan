"""Verschlüsselt: Änderungsprotokoll, Rückgängig-Daten und Postausgang (Stufe 1, Teil 3)."""

import io
import json

import pytest
from django.core.management import call_command
from django.db import connection

from audit.chain import seal, verify
from audit.log import record
from audit.models import AuditEntry
from changes.models import ChangeRecord
from core import crypto
from core.models import DataKey
from core.tenancy import rls_bypass
from exchange.models import private_storage
from outbox.mail import send
from outbox.models import EMPTIED, OutgoingMail
from outbox.purge import purge_sent

from .factories import make_member


@pytest.fixture(autouse=True)
def _private_root(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"
    settings.EMAIL_BACKEND = "outbox.backend.OutboxBackend"


def _raw(table: str, column: str, pk):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {column}::text FROM {table} WHERE id = %s", [pk])  # noqa: S608
        return cursor.fetchone()[0]


def _raw_file(name: str) -> bytes:
    with open(private_storage().path(name), "rb") as handle:
        return handle.read()


@pytest.mark.django_db
class TestProtokoll:
    def test_aenderungen_nur_als_chiffrat(self, orgs):
        m = make_member(orgs["c"], "Erika", "Muster")
        entry = record(orgs["c"], None, "update", m, {"Straße": ["Altweg 1", "Lindenweg 4"]})
        roh = json.loads(_raw("audit_auditentry", "changes", entry.pk))
        assert set(roh) == {"enc1"}
        assert "Lindenweg" not in roh["enc1"]
        with rls_bypass():
            assert AuditEntry.objects.get(pk=entry.pk).changes == {
                "Straße": ["Altweg 1", "Lindenweg 4"]
            }

    def test_kette_bleibt_pruefbar(self, orgs):
        m = make_member(orgs["c"], "Erika", "Muster")
        record(orgs["c"], None, "update", m, {"Telefon": ["1", "2"]})
        seal(orgs["c"].pk)
        assert verify(orgs["c"].pk)["ok"]

    def test_bestand_verschluesseln_kette_bleibt(self, orgs):
        m = make_member(orgs["c"], "Erika", "Muster")
        entry = record(orgs["c"], None, "update", m, {"Telefon": ["1", "2"]})
        seal(orgs["c"].pk)
        # Stand von vor der Umstellung: Klartext in der Spalte
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE audit_auditentry SET changes = %s::jsonb WHERE id = %s",
                ['{"Telefon": ["1", "2"]}', entry.pk],
            )
        call_command("daten_verschluesseln", stdout=io.StringIO())
        assert set(json.loads(_raw("audit_auditentry", "changes", entry.pk))) == {"enc1"}
        assert verify(orgs["c"].pk)["ok"]
        call_command("daten_verschluesseln", "--entschluesseln", stdout=io.StringIO())
        assert json.loads(_raw("audit_auditentry", "changes", entry.pk)) == {"Telefon": ["1", "2"]}
        assert verify(orgs["c"].pk)["ok"]

    def test_leeren_bleibt_moeglich(self, orgs):
        m = make_member(orgs["c"], "Erika", "Muster")
        entry = record(orgs["c"], None, "update", m, {"Telefon": ["1", "2"]})
        with rls_bypass():
            AuditEntry.objects.filter(pk=entry.pk).update(changes={}, cleared=True)
        assert json.loads(_raw("audit_auditentry", "changes", entry.pk)) == {}

    def test_rueckgaengig_daten_verschluesselt(self, api, orgs, board_c):
        m = make_member(orgs["c"], "Erika", "Muster")
        r = api(board_c).patch(
            f"/api/orgs/{orgs['c'].pk}/members/{m.pk}/",
            {"city": "Geheimstadt"},
            content_type="application/json",
        )
        assert r.status_code == 200, r.content
        with rls_bypass():
            records = list(ChangeRecord.objects.filter(organization=orgs["c"]))
        assert records
        for rec in records:
            for column in ("before", "after"):
                roh = _raw("changes_changerecord", column, rec.pk)
                assert roh is None or set(json.loads(roh)) == {"enc1"}
                assert roh is None or "Geheimstadt" not in roh


@pytest.mark.django_db
class TestPostausgang:
    def test_text_und_anhang_verschluesselt(self, orgs):
        send(
            ["erika@example.org"],
            "Rechnung",
            "Ihr Beitrag: 30 Euro, IBAN DE02120300000000202051",
            organization=orgs["c"],
            attachments=[("rechnung.pdf", b"%PDF-geheim", "application/pdf")],
        )
        with rls_bypass():
            mail = OutgoingMail.objects.get(subject="Rechnung")
        assert _raw("outbox_outgoingmail", "body", mail.pk).startswith("enc1:")
        assert "IBAN" in mail.body
        name = mail.attachments[0]["path"]
        assert name.startswith("outbox/")
        assert _raw_file(name).startswith(crypto.MAGIC)
        with private_storage().open(name, "rb") as handle:
            assert handle.read() == b"%PDF-geheim"
        assert DataKey.objects.filter(organization=orgs["c"]).exists()

    def test_anhang_ueber_die_api(self, api, orgs, board_c):
        send(
            ["erika@example.org"],
            "Mit Anhang",
            "Text",
            organization=orgs["c"],
            attachments=[("liste.csv", b"a;b", "text/csv")],
        )
        with rls_bypass():
            mail = OutgoingMail.objects.get(subject="Mit Anhang")
        r = api(board_c).get(f"/api/orgs/{orgs['c'].pk}/outbox/{mail.pk}/attachments/0/")
        assert r.status_code == 200
        assert b"".join(r.streaming_content) == b"a;b"

    def test_ohne_verein_mit_plattformschluessel(self, orgs):
        from organizations.models import Organization

        send(["erika@example.org"], "Passwort", "Hallo")
        with rls_bypass():
            mail = OutgoingMail.objects.get(subject="Passwort")
        assert _raw("outbox_outgoingmail", "body", mail.pk).startswith("enc1:")
        assert mail.body.startswith("Hallo")
        assert DataKey.objects.filter(organization=Organization.platform()).exists()

    def test_geleerte_mails_bleiben_lesbar_markiert(self, orgs, settings):
        import datetime

        from django.utils import timezone

        settings.OUTBOX_RETENTION_DAYS = 1
        send(["erika@example.org"], "Alt", "Inhalt", organization=orgs["c"])
        with rls_bypass():
            mail = OutgoingMail.objects.get(subject="Alt")
            OutgoingMail.objects.filter(pk=mail.pk).update(
                status=OutgoingMail.Status.SENT,
                created_at=timezone.now() - datetime.timedelta(days=5),
            )
        assert purge_sent() == 1
        assert _raw("outbox_outgoingmail", "body", mail.pk) == EMPTIED
        # Zweiter Lauf findet nichts mehr (Filter auf den Klartextwert geht)
        assert purge_sent() == 0

    def test_alte_anhaenge_verschluesseln(self, orgs):
        send(
            ["erika@example.org"],
            "Alt",
            "Text",
            organization=orgs["c"],
            attachments=[("a.txt", b"klartext", "text/plain")],
        )
        with rls_bypass():
            name = OutgoingMail.objects.get(subject="Alt").attachments[0]["path"]
        # Wie vor der Umstellung: Klartext auf der Platte
        with open(private_storage().path(name), "wb") as handle:
            handle.write(b"klartext")
        call_command("dateien_verschluesseln", stdout=io.StringIO())
        assert _raw_file(name).startswith(crypto.MAGIC)
        with private_storage().open(name, "rb") as handle:
            assert handle.read() == b"klartext"
