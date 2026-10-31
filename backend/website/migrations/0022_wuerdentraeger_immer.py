"""Schalter „Würden und Ehrungen unter einem Menüpunkt“ entfällt (Ralf 2026-10-31):
Würden und Ehrungen sind immer eigene Menüpunkte, angeordnet per Ziehen und
einzeln ausschaltbar."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("website", "0021_menu")]

    operations = [migrations.RemoveField(model_name="website", name="honors_grouped")]
