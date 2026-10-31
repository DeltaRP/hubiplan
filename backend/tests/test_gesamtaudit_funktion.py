"""Gesamtaudit 25.10.2026, Paket 3: Funktion und Betrieb (B-F03, B-P01, A-S06)."""

import datetime

import pytest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from billing import services as billing_services
from billing.models import FeeRate
from core.ratelimit import client_ip, too_many
from core.tenancy import tenant_context
from members.models import MemberType

from .factories import make_member

pytestmark = pytest.mark.django_db


def test_vollstaendiger_export_enthaelt_rundschreiben(orgs):
    from circulars.models import Circular, CircularTemplate
    from datatransfer.tables import dump_tables

    club = orgs["c"]
    with tenant_context(club.pk):
        Circular.objects.create(organization=club, subject="Einladung", body="Hallo")
        CircularTemplate.objects.create(organization=club, name="Vorlage", subject="Betreff")

        class Packer:
            def add(self, *args):
                return None

        tables = dump_tables(club, Packer())
    assert [r["subject"] for r in tables["circulars.circular"]] == ["Einladung"]
    assert tables["circulars.circulartemplate"][0]["name"] == "Vorlage"


def test_beitragsvorschau_abfragen_wachsen_nicht_je_mitglied(orgs):
    club = orgs["c"]
    with tenant_context(club.pk):
        member_type = MemberType.objects.create(organization=club, name="Beitragsart")
        FeeRate.objects.create(organization=club, member_type=member_type, amount=60)
        period = billing_services.period(club, 2025, "yearly", 1)
        counts = []
        for total in (5, 25):
            start = 0 if total == 5 else 5
            for index in range(start, total):
                make_member(club, f"Name{index}", "Beitrag", member_type=member_type)
            with CaptureQueriesContext(connection) as captured:
                plan = billing_services.plan_run(club, period)
            assert len(plan.member_items) == total
            counts.append(len(captured))
    assert counts[1] - counts[0] <= 3, counts


def test_ratenbegrenzung_zaehlt_atomar():
    key = "probe:ratelimit"
    assert [too_many(key, 3, 60) for _ in range(5)] == [False, False, False, True, True]


def test_client_ip_nimmt_den_eintrag_des_proxys():
    request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 10.0.0.9")
    assert client_ip(request) == "10.0.0.9"
    assert client_ip(RequestFactory().get("/", REMOTE_ADDR="10.1.1.1")) == "10.1.1.1"


def test_serie_seit_2010_bleibt_sichtbar(orgs):
    from django.utils import timezone

    from events.models import Event
    from events.recurrence import occurrences

    start = timezone.make_aware(datetime.datetime(2010, 1, 4, 10))
    event = Event(
        pk=1,
        organization=orgs["c"],
        title="Übungsabend",
        starts_at=start,
        ends_at=start + datetime.timedelta(hours=1),
        repeat="weekly",
        repeat_interval=1,
    )
    window = timezone.make_aware(datetime.datetime(2026, 10, 1))
    with tenant_context(orgs["c"].pk):
        found = occurrences([event], window, window + datetime.timedelta(days=30))
    assert len(found) >= 4
