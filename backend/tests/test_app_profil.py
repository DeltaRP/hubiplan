"""Android-App, Schritt A5: eigenes Foto im Mitgliederbereich (App) mit Einwilligung."""
# ruff: noqa: F811  (Fixtures aus test_m12_events als Parameter)

import io
import json

import pytest
from PIL import Image

from audit.models import AuditEntry
from members.models import MemberPhoto, Membership

from .test_app_devices import app, pair, pairing_code
from .test_app_push import (  # noqa: F401  (Fixtures)
    Receiver,
    allow_endpoint,
    push_outbox,
    register,
)
from .test_m12_events import (  # noqa: F401  (Fixtures)
    cal,
    member_with_access,
)
from .test_photos import image_file

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def anna(cal, api):
    m, user, access = member_with_access(cal["a"], "Anna")
    token = pair(pairing_code(api(user))).json()["token"]
    return {
        "m": m,
        "user": user,
        "access": access,
        "token": token,
        "url": f"/api/portal/{access.pk}/photo/",
    }


def upload(anna, consent=True):
    data = {"file": image_file()}
    if consent:
        data["consent"] = "true"
    return app(anna["token"]).post(anna["url"], data)


class TestEigenesFoto:
    def test_hochladen_wartet_auf_freigabe(self, anna):
        assert app(anna["token"]).get(anna["url"]).json()["pending"] is None
        resp = upload(anna)
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["pending"] and data["approved"] is None
        photo = MemberPhoto.objects.get()
        assert photo.status == "pending" and photo.source == "app"
        m = Membership.objects.get(pk=anna["m"].pk)
        assert m.photo_consent_at and m.photo_consent_source == "app"
        assert AuditEntry.objects.filter(organization=anna["access"].organization).exists()
        # Bild abrufbar, ohne Ortsangaben
        img = app(anna["token"]).get(data["pending"]["url"])
        assert img.status_code == 200 and img["Content-Type"] == "image/jpeg"
        loaded = Image.open(io.BytesIO(b"".join(img.streaming_content)))
        assert 0x8825 not in loaded.getexif()

    def test_ohne_einwilligung(self, anna):
        resp = upload(anna, consent=False)
        assert resp.status_code == 400 and "consent" in resp.json()
        assert not MemberPhoto.objects.exists()

    def test_widerrufen_loescht_alles(self, anna):
        upload(anna)
        resp = app(anna["token"]).delete(anna["url"])
        assert resp.status_code == 200
        assert not MemberPhoto.objects.exists()
        m = Membership.objects.get(pk=anna["m"].pk)
        assert m.photo_consent_at is None and m.photo_consent_source == ""

    def test_fremder_zugang(self, cal, anna, api):
        _, other, _ = member_with_access(cal["a"], "Otto")
        token = pair(pairing_code(api(other))).json()["token"]
        assert app(token).get(anna["url"]).status_code == 404
        assert (
            app(token).post(anna["url"], {"file": image_file(), "consent": "true"}).status_code
            == 404
        )

    def test_kein_bild(self, anna):
        resp = app(anna["token"]).post(anna["url"], {"consent": "true"})
        assert resp.status_code == 400


class TestBescheidPerPush:
    @pytest.fixture
    def with_push(self, anna, allow_endpoint, push_outbox, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        receiver = Receiver()
        assert register(anna["token"], receiver).status_code == 200
        return receiver

    def test_foto_freigegeben(
        self, cal, anna, with_push, push_outbox, board_a, api, django_capture_on_commit_callbacks
    ):
        upload(anna)
        with django_capture_on_commit_callbacks(execute=True):
            resp = api(board_a).post(
                f"/api/orgs/{cal['a'].pk}/members/{anna['m'].pk}/photo/approve/",
                {"decision": "approve"},
                content_type="application/json",
            )
        assert resp.status_code == 200, resp.content
        msg = json.loads(with_push.decrypt(push_outbox[-1]["body"]))
        assert msg["t"] == "info" and msg["title"] == "Dein Foto wurde freigegeben"
        assert msg["access"] == anna["access"].pk

    def test_aenderung_entschieden(
        self, cal, anna, with_push, push_outbox, board_a, api, django_capture_on_commit_callbacks
    ):
        cal["a"].contact_changes_need_approval = True
        cal["a"].save()
        resp = app(anna["token"]).post(
            f"/api/portal/{anna['access'].pk}/change-requests/",
            {"city": "Altstadt"},
            content_type="application/json",
        )
        assert resp.status_code in (200, 201), resp.json()
        from portal.models import ChangeRequest

        cr = ChangeRequest.objects.get()
        with django_capture_on_commit_callbacks(execute=True):
            resp = api(board_a).post(
                f"/api/orgs/{cal['a'].pk}/change-requests/{cr.pk}/decide/",
                {"accept": True},
                content_type="application/json",
            )
        assert resp.status_code == 200, resp.json()
        msg = json.loads(with_push.decrypt(push_outbox[-1]["body"]))
        assert msg["title"] == "Deine Änderung wurde übernommen"

    def test_ohne_push_kein_versand(
        self, cal, anna, push_outbox, board_a, api, django_capture_on_commit_callbacks
    ):
        upload(anna)
        with django_capture_on_commit_callbacks(execute=True):
            api(board_a).post(
                f"/api/orgs/{cal['a'].pk}/members/{anna['m'].pk}/photo/approve/",
                {"decision": "approve"},
                content_type="application/json",
            )
        assert push_outbox == []
