"""Menü der Webseite als Baum (Reihenfolge und Unterpunkte per Ziehen, Ralf 2026-10-31)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("website", "0020_chronik_aemter")]

    operations = [
        migrations.AddField(
            model_name="website",
            name="menu",
            field=models.JSONField(blank=True, default=list, verbose_name="Menü"),
        ),
    ]
