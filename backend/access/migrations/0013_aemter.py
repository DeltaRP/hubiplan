"""Rollen: „in der Chronik zeigen“ heißt jetzt „unter „Ämter“ zeigen“ (Ralf 2026-10-31)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("access", "0012_eine_reihenfolge")]

    operations = [
        migrations.AlterField(
            model_name="role",
            name="in_chronicle",
            field=models.BooleanField(
                default=False,
                help_text="Heutige und frühere Inhaber erscheinen auf der Webseite unter "
                "Geschichte › Ämter (z. B. Vorsitzende seit …).",
                verbose_name="unter „Ämter“ zeigen",
            ),
        ),
    ]
