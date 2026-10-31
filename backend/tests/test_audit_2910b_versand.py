# ruff: noqa: F811  (Fixtures aus anderen Testmodulen)
"""Gesamtaudit 29.10.2026 Teil b, B-V04: hängende Rundschreiben-Mails."""

import datetime

import pytest
from django.utils import timezone

from circulars import services as circular_services
from circulars.models import Circular, CircularRecipient

from .test_m12_events import JSON, cal, private_root, zug, zug2  # noqa: F401
from .test_rundschreiben import base, draft, members, send  # noqa: F401

pytestmark = pytest.mark.django_db


def resp_counts(c, url, pk):
    return c.get(f"{url}{pk}/recipients/").json()["counts"]


class TestVersandUnklar:
    """B-V04: hängende Mails als „Versand unklar“, erneut sendbar."""

    def test_unklar_und_erneut_senden(
        self, cal, board_a, members, api, settings, django_capture_on_commit_callbacks
    ):
        c = api(board_a)
        url = base(cal["a"])
        data = draft(c, url)
        send(c, url, data["id"], django_capture_on_commit_callbacks, settings)
        circular = Circular.objects.get(pk=data["id"])
        mails = circular.recipients.filter(channel="mail").order_by("pk")
        assert mails.count() >= 2
        first, second = mails[0], mails[1]
        old = timezone.now() - datetime.timedelta(minutes=20)
        # Absturz mitten im Versand: beansprucht, aber ohne Ergebnis
        CircularRecipient.objects.filter(pk=first.pk).update(status="sending", sent_at=old)
        CircularRecipient.objects.filter(pk=second.pk).update(
            status="sending", sent_at=timezone.now()
        )
        first.refresh_from_db()
        second.refresh_from_db()
        assert circular_services.is_unclear(first)
        assert not circular_services.is_unclear(second)
        rows = {r["key"]: r for r in c.get(f"{url}{data['id']}/recipients/").json()["items"]}
        assert rows[f"r{first.pk}"]["status_label"] == "Versand unklar"
        assert resp_counts(c, url, data["id"])["unclear"] == 1
        settings.CELERY_TASK_ALWAYS_EAGER = True
        with django_capture_on_commit_callbacks(execute=True):
            resp = c.post(f"{url}{data['id']}/resend/", content_type=JSON)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["resent"] == 1
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.status == "sent"
        assert second.status == "sending"  # noch nicht unklar: nicht doppelt senden

    def test_entwurf_nicht_erneut(self, cal, board_a, members, api):
        c = api(board_a)
        url = base(cal["a"])
        data = draft(c, url)
        assert c.post(f"{url}{data['id']}/resend/", content_type=JSON).status_code == 400
