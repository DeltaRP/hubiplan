"""Startseite: offene Aufgaben (Änderungsmeldungen, Wechsel, Fotos, Rückmeldungen)."""

import datetime

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from core.tenancy import tenant_context
from events.models import Event, EventResponse
from members.models import MemberType, TransferRequest
from members.photo_models import MemberPhoto
from portal.models import ChangeRequest

from .factories import give_role, make_member, make_user

pytestmark = pytest.mark.django_db


def url(org):
    return f"/api/orgs/{org.pk}/open-tasks/"


@pytest.fixture
def erika(orgs):
    return make_member(orgs["a"], "Erika", "Muster")


def test_sammelt_offene_vorgaenge(api, orgs, board_a, erika):
    a = orgs["a"]
    a.enabled_modules = ["members", "events"]
    a.save()
    with tenant_context(a.pk):
        ChangeRequest.objects.create(organization=a, membership=erika, data={"city": "X"})
        ChangeRequest.objects.create(
            organization=a, membership=erika, data={}, status=ChangeRequest.Status.ACCEPTED
        )
        MemberPhoto.objects.create(
            organization=a,
            membership=erika,
            status=MemberPhoto.Status.PENDING,
            image=ContentFile(b"\xff\xd8bild", name="b.jpg"),
            thumbnail=ContentFile(b"\xff\xd8klein", name="t.jpg"),
        )
        soon = timezone.now() + datetime.timedelta(days=3)
        event = Event.objects.create(
            organization=a,
            title="Sommerfest",
            starts_at=soon,
            ends_at=soon + datetime.timedelta(hours=3),
            rsvp_enabled=True,
        )
        EventResponse.objects.create(
            organization=a, event=event, membership=erika, status="yes", source="member"
        )
        Event.objects.create(
            organization=a,
            title="Später",
            starts_at=soon + datetime.timedelta(days=60),
            ends_at=soon + datetime.timedelta(days=60, hours=1),
            rsvp_enabled=True,
        )
    b_type = MemberType.objects.create(organization=orgs["b"], name="aktiv", active=True)
    TransferRequest.objects.create(
        scope=orgs["federation"],
        person=erika.person,
        from_org=a,
        to_org=orgs["b"],
        member_type=b_type,
        entry_date=datetime.date(2026, 1, 1),
    )

    items = api(board_a).get(url(a)).json()["items"]
    kinds = sorted(i["kind"] for i in items)
    assert kinds == ["change_request", "event", "photo", "transfer"]
    event_item = next(i for i in items if i["kind"] == "event")
    assert "1 Zusagen" in event_item["detail"]
    assert event_item["link"].startswith(f"/termine?termin={event.pk}&datum=")
    photo = next(i for i in items if i["kind"] == "photo")
    assert photo["link"] == f"/mitglieder/{erika.pk}"


def test_nur_mit_passendem_recht(api, orgs, erika):
    a = orgs["a"]
    with tenant_context(a.pk):
        ChangeRequest.objects.create(organization=a, membership=erika, data={"city": "X"})
    reader = make_user("lesen@example.org")
    give_role(reader, a, permissions=["members.view"], name="Lesen")
    assert api(reader).get(url(a)).json()["items"] == []
