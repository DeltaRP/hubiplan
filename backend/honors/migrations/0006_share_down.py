"""Würde an Untereinheiten weitergeben; Herkunft des Würdenträgers (Ralf 2026-10-31)."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("honors", "0005_count_each_reign"),
        ("organizations", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="dignity",
            name="share_down",
            field=models.BooleanField("an Untereinheiten weitergeben", default=False),
        ),
        migrations.AddField(
            model_name="reign",
            name="origin",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="organizations.organization",
                verbose_name="aus Einheit",
            ),
        ),
        migrations.AddField(
            model_name="reign",
            name="origin_name",
            field=models.CharField("aus (frei)", max_length=200, blank=True),
        ),
    ]
