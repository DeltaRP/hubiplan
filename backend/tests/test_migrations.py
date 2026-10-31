"""Modelle und Migrationen stimmen überein."""

import io

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_keine_fehlenden_migrationen():
    out = io.StringIO()
    try:
        call_command("makemigrations", check=True, dry_run=True, stdout=out)
    except SystemExit as exc:  # makemigrations --check beendet sich mit Code 1
        pytest.fail(f"Fehlende Migrationen:\n{out.getvalue()}\n{exc}")
