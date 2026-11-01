import pytest
from django.test import override_settings

from core.tasks import ping


@pytest.mark.django_db
def test_health(client):
    response = client.get("/api/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "keys": "ok"}


@pytest.mark.django_db
def test_health_ohne_hauptschluessel(client, settings, tmp_path):
    from core import crypto

    settings.DATA_ENCRYPTION_KEY_FILE = str(tmp_path / "fehlt")
    crypto.reset()
    response = client.get("/api/health/")
    assert response.status_code == 503
    assert response.json()["keys"] == "fehler"


def test_me_ohne_anmeldung(client, db):
    assert client.get("/api/me/").status_code == 403


@pytest.mark.django_db
def test_openapi_schema(client, django_user_model):
    # Ohne Anmeldung gibt es weder Schema noch Swagger-Seite
    assert client.get("/api/schema/").status_code == 403
    assert client.get("/api/docs/").status_code == 403
    user = django_user_model.objects.create_user(email="doku@example.org", password="x")
    client.force_login(user)
    response = client.get("/api/schema/")
    assert response.status_code == 200
    assert b"HUBIplan API" in response.content
    assert client.get("/api/docs/").status_code == 200


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def test_celery_task_eager():
    assert ping.delay().get(timeout=5) == "pong"


@pytest.mark.django_db
def test_benutzer_mit_email(django_user_model):
    user = django_user_model.objects.create_user(email="A@Example.ORG", password="x")
    assert user.email == "a@example.org"
    assert str(user) == "a@example.org"
    admin = django_user_model.objects.create_superuser(email="admin@example.org", password="x")
    assert admin.is_staff and admin.is_superuser
