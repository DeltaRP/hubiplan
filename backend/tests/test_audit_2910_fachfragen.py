# ruff: noqa: F811  (Fixtures aus anderen Testmodulen)
"""Fachfragen zum Audit vom 29.10.2026, von Ralf „wie empfohlen“ entschieden."""

import datetime
import uuid

import pytest
from django.utils import timezone

from billing import sepa
from billing.models import AgeRate, DebitRun, Invoice, Mandate
from core.tenancy import tenant_context
from events import recurrence
from events.models import Event, EventException
from members.models import ContactDetails
from portal.models import ChangeRequest, PortalAccess

from .factories import make_member
from .test_audit_finanzen import invoice, pay  # noqa: F401
from .test_m9_billing import _private, base, c, club, members, setup, start_run, zug  # noqa: F401
from .test_m12_events import JSON, cal, org_base, private_root  # noqa: F401

pytestmark = pytest.mark.django_db
TZ = timezone.get_current_timezone()


def local(y, m, d, h=0):
    return timezone.make_aware(datetime.datetime(y, m, d, h), TZ)


class TestBeitraege:
    def test_1_storno_und_neu_berechnen_legt_neuen_entwurf_an(self, c, base, invoice):
        run = invoice.run_id
        assert c.post(f"{base}/invoices/{invoice.pk}/cancel/").status_code == 200
        resp = c.post(f"{base}/runs/{run}/rebuild/")
        assert resp.status_code == 200, resp.json()
        drafts = Invoice.objects.filter(membership=invoice.membership, status=Invoice.Status.DRAFT)
        assert drafts.count() == 1

    def test_2_keine_negativen_saetze(self, c, base, setup):
        for field in ("club_rate_active", "club_rate_passive", "club_base_amount"):
            resp = c.patch(f"{base}/settings/", {field: "-5.00"}, content_type=JSON)
            assert resp.status_code == 400 and field in resp.json()

    def test_3_ueberlappende_altersstufen_abgelehnt(self, club, c, base, setup):
        existing = AgeRate.objects.filter(organization=club, member_type=None).first()
        if existing is None:
            ok = c.post(
                f"{base}/age-rates/",
                {"name": "Jugend", "max_age": 17, "discount_percent": "50"},
                content_type=JSON,
            )
            assert ok.status_code == 201, ok.json()
            existing = AgeRate.objects.get(pk=ok.json()["id"])
        low = existing.min_age or 0
        resp = c.post(
            f"{base}/age-rates/",
            {"name": "Doppelt", "min_age": low, "max_age": low + 1, "discount_percent": "10"},
            content_type=JSON,
        )
        assert resp.status_code == 400 and existing.name in str(resp.json())
        # Ohne Überschneidung geht es
        resp = c.post(
            f"{base}/age-rates/",
            {"name": "Senioren", "min_age": 90, "discount_percent": "10"},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()

    def test_4_neu_berechnen_fragt_bei_handaenderungen(self, c, base, members):
        run = start_run(c, base).json()
        erika = Invoice.objects.get(membership=members["erika"])
        Invoice.objects.filter(pk=erika.pk).update(
            updated_at=erika.created_at + datetime.timedelta(minutes=5)
        )
        resp = c.post(f"{base}/runs/{run['id']}/rebuild/")
        assert resp.status_code == 409 and resp.json()["edited"] == 1
        assert Invoice.objects.filter(pk=erika.pk).exists()
        resp = c.post(f"{base}/runs/{run['id']}/rebuild/?bestaetigt=1")
        assert resp.status_code == 200, resp.json()

    def test_5_sepa_datei_wird_unveraendert_wieder_ausgeliefert(self, club, c, base, setup):
        resp = c.patch(
            f"{base}/settings/",
            {"sepa_enabled": True, "creditor_id": "DE98ZZZ09999999999"},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        with tenant_context(club.pk):
            run = DebitRun.objects.create(
                organization=club,
                collection_date=datetime.date(2025, 3, 3),
                account_id=setup["bank"],
                message_id="HUBI-TEST",
                xml='<?xml version="1.0"?><Document>damals</Document>',
            )
        resp = c.get(f"{base}/debits/{run.pk}/xml/")
        assert resp.status_code == 200
        assert b"damals" in resp.content

    def test_6_mandatsfrist_taggenau(self, club):
        m = Mandate(
            organization=club,
            reference="X",
            holder="E",
            iban="DE02120300000000202051",
            signed_on=datetime.date(2023, 1, 31),
            source="paper",
        )
        assert not sepa.mandate_expired(m, datetime.date(2026, 1, 1))
        assert not sepa.mandate_expired(m, datetime.date(2026, 1, 30))
        assert sepa.mandate_expired(m, datetime.date(2026, 1, 31))

    def test_7_zahlung_ohne_schluessel_abgelehnt(self, c, base, setup, invoice):
        resp = c.post(
            f"{base}/invoices/{invoice.pk}/payments/",
            {"date": "2025-02-10", "method": "transfer", "account": setup["bank"]},
            content_type=JSON,
        )
        assert resp.status_code == 400 and "Idempotency-Key" in str(resp.json())
        assert pay(c, base, invoice, setup, key=str(uuid.uuid4())).status_code == 200


class TestAenderungsmeldung:
    def test_8_neuere_vereinsaenderung_nicht_still_ueberschreiben(self, orgs, api, board_a):
        club = orgs["a"]
        club.member_portal_enabled = True
        club.contact_changes_need_approval = True
        club.save()
        m = make_member(club, "Erika", "Muster", "erika@example.org")
        api(board_a).post(f"/api/orgs/{club.pk}/members/{m.pk}/access/")
        access = PortalAccess.objects.get()
        resp = api(access.user).post(
            f"/api/portal/{access.pk}/change-requests/", {"city": "Altstadt"}, content_type=JSON
        )
        assert resp.status_code == 201, resp.json()
        cr = ChangeRequest.objects.get()
        # Der Vorstand ändert den Ort inzwischen selbst
        with tenant_context(club.pk):
            ContactDetails.objects.filter(person=m.person).update(city="Neustadt")
        url = f"/api/orgs/{club.pk}/change-requests/{cr.pk}/decide/"
        resp = api(board_a).post(url, {"accept": True}, content_type=JSON)
        assert resp.status_code == 409 and resp.json()["conflicts"] == ["city"]
        with tenant_context(club.pk):
            assert ContactDetails.objects.get(person=m.person).city == "Neustadt"
        resp = api(board_a).post(url, {"accept": True, "overwrite": True}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        with tenant_context(club.pk):
            assert ContactDetails.objects.get(person=m.person).city == "Altstadt"


class TestSerien:
    def test_9_absage_entfaellt_wenn_abstand_geaendert(self, cal, board_a, api):
        event = Event.objects.create(
            organization=cal["a"],
            title="Übung",
            starts_at=local(2026, 3, 3, 19),
            ends_at=local(2026, 3, 3, 21),
            repeat="weekly",
        )
        EventException.objects.create(
            event=event, original_start=local(2026, 3, 10, 19), is_cancelled=True
        )
        resp = api(board_a).patch(
            f"{org_base(cal['a'])}events/{event.pk}/", {"repeat_interval": 2}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        assert not EventException.objects.exists()
        event.refresh_from_db()
        event.repeat_interval = 1
        assert not any(
            o.is_cancelled
            for o in recurrence.occurrences([event], local(2026, 3, 9), local(2026, 3, 12))
        )
