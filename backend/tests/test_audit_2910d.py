"""Lizenzaudit 29.10.2026 Teil d: Serverseite (F07, F08)."""

from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings


@pytest.mark.django_db
class TestApiDoku:
    """F08/Fachfrage 3: Swagger-Oberfläche lädt fremden Code, im Betrieb abschaltbar."""

    def test_abgeschaltet(self, client, django_user_model):
        user = django_user_model.objects.create_user(email="doku@example.org", password="x")
        client.force_login(user)
        with override_settings(API_DOCS_ENABLED=False):
            assert client.get("/api/docs/").status_code == 404
            # Das Schema selbst kommt ohne fremden Code aus und bleibt
            assert client.get("/api/schema/").status_code == 200
        assert client.get("/api/docs/").status_code == 200

    def test_feste_version(self):
        dist = settings.SPECTACULAR_SETTINGS["SWAGGER_UI_DIST"]
        assert "latest" not in dist
        assert "latest" not in settings.SPECTACULAR_SETTINGS["SWAGGER_UI_FAVICON_HREF"]
        assert "@5." in dist


def test_image_ohne_testwerkzeuge():
    """F07: Das Server-Image installiert standardmäßig nur die Laufzeit-Abhängigkeiten."""
    dockerfile = (Path(settings.BASE_DIR) / "Dockerfile").read_text()
    assert "ARG REQUIREMENTS=requirements.txt" in dockerfile
    runtime = (Path(settings.BASE_DIR) / "requirements.txt").read_text()
    assert "pytest" not in runtime and "ruff" not in runtime
