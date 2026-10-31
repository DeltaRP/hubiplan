"""Webseite: weitergegebene Würden zeigen, Menü „Würdenträger“ (Ralf 2026-10-31)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("website", "0018_design")]

    operations = [
        migrations.AddField(
            model_name="website",
            name="include_parent_honors",
            field=models.BooleanField(
                "weitergegebene Würden der übergeordneten Einheiten zeigen", default=False
            ),
        ),
        migrations.AddField(
            model_name="website",
            name="honors_grouped",
            field=models.BooleanField(
                "Würden und Ehrungen unter einem Menüpunkt „Würdenträger“", default=False
            ),
        ),
    ]
