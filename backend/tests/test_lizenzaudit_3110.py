"""Lizenzaudit 31.10.2026: Lizenzbeilagen und keine fremden Browserdateien ohne Hinweis."""

from pathlib import Path

from django.conf import settings
from rest_framework.settings import api_settings

BACKEND = Path(settings.BASE_DIR)


def test_api_antwortet_nur_mit_json():
    """L06: Ohne Browsable API gehen Bootstrap, jQuery und Font Awesome nicht an den Browser."""
    renderers = [r.__module__ + "." + r.__name__ for r in api_settings.DEFAULT_RENDERER_CLASSES]
    assert renderers == ["rest_framework.renderers.JSONRenderer"]


def test_dockerfile_sammelt_drf_dateien_nicht_ein():
    dockerfile = (BACKEND / "Dockerfile").read_text()
    assert "collectstatic" in dockerfile
    assert "--ignore rest_framework" in dockerfile


def test_passwortliste_hat_ihren_lizenztext():
    """L04: Der MIT-Text von SecLists liegt neben der übernommenen Liste."""
    data = BACKEND / "accounts" / "data"
    lizenz = (data / "LICENSE-SecLists.txt").read_text()
    assert "MIT License" in lizenz
    assert "Copyright (c) 2018 Daniel Miessler" in lizenz
    readme = (data / "README.md").read_text()
    assert "1a7bb9127eca9e6ff2fc0301c597fe6e16a0cb56" in readme
    assert "LICENSE-SecLists.txt" in readme
