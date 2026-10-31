"""Die Liste der Dateifelder für den Rücksicherungstest passt zu den Modellen."""

from pathlib import Path

import pytest
from django.apps import apps
from django.conf import settings
from django.db import models

# Im Testcontainer bindet scripts/test.sh die Datei unter /deploy/backup/ ein
LISTE = Path(__file__).resolve().parents[2] / "deploy" / "backup" / "dateifelder.txt"


def eingetragen():
    lines = LISTE.read_text(encoding="utf-8").splitlines()
    return {tuple(line.split()) for line in lines if line.strip() and not line.startswith("#")}


def aus_den_modellen():
    roots = {Path(settings.MEDIA_ROOT): "media", Path(settings.PRIVATE_ROOT): "private"}
    found = set()
    for model in apps.get_models():
        for field in model._meta.concrete_fields:
            if isinstance(field, models.FileField):
                root = roots[Path(field.storage.location)]
                found.add((model._meta.db_table, field.column, root))
    return found


# Ältere Fassungen von scripts/test.sh binden die Datei noch nicht ein (WSL-Klon nicht
# aktualisiert). Dann fehlt nur dieser Abgleich, die übrigen Tests laufen normal.
@pytest.mark.skipif(not LISTE.exists(), reason="dateifelder.txt nicht eingebunden")
def test_jedes_dateifeld_steht_in_der_liste():
    assert eingetragen() == aus_den_modellen()
