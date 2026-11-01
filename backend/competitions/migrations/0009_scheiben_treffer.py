"""Schießscheiben Schritt 1: Scheibe, Wertungsart und Gleichstandskette je Wertung,
Trefferpunkte (mit Row-Level Security)."""

import django.db.models.deletion
from django.db import migrations, models

from core.rls import disable_rls_sql, enable_rls_sql


def rls_on(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(enable_rls_sql("competitions_hit"))


def rls_off(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(disable_rls_sql("competitions_hit"))


class Migration(migrations.Migration):
    dependencies = [
        ("competitions", "0008_stechen_ohne_empfang"),
    ]

    operations = [
        migrations.AddField(
            model_name="scoring",
            name="target",
            field=models.CharField(blank=True, max_length=30, verbose_name="Scheibe"),
        ),
        migrations.AddField(
            model_name="scoring",
            name="custom_target",
            field=models.JSONField(blank=True, default=dict, verbose_name="eigene Scheibe"),
        ),
        migrations.AddField(
            model_name="scoring",
            name="method",
            field=models.CharField(
                choices=[
                    ("frei", "Wert frei eingeben"),
                    ("ringe", "Ringe"),
                    ("zehntel", "Zehntel"),
                    ("teiler", "Teiler"),
                ],
                default="frei",
                max_length=10,
                verbose_name="Wertungsart",
            ),
        ),
        migrations.AddField(
            model_name="scoring",
            name="tie_breaks",
            field=models.JSONField(blank=True, default=list, verbose_name="bei Gleichstand"),
        ),
        migrations.AddField(
            model_name="scoring",
            name="series_size",
            field=models.PositiveSmallIntegerField(default=10, verbose_name="Schüsse je Serie"),
        ),
        migrations.CreateModel(
            name="Hit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("number", models.PositiveSmallIntegerField(verbose_name="Schuss Nr.")),
                ("x", models.DecimalField(decimal_places=3, max_digits=8, verbose_name="x (mm)")),
                ("y", models.DecimalField(decimal_places=3, max_digits=8, verbose_name="y (mm)")),
                (
                    "spot",
                    models.PositiveSmallIntegerField(
                        blank=True, null=True, verbose_name="Spiegel"
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("tippen", "angetippt"),
                            ("foto", "aus Foto erkannt"),
                            ("hand", "von Hand"),
                        ],
                        default="tippen",
                        max_length=10,
                        verbose_name="Quelle",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="organizations.organization",
                    ),
                ),
                (
                    "scoring",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="hits",
                        to="competitions.scoring",
                    ),
                ),
                (
                    "starter",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="hits",
                        to="competitions.starter",
                    ),
                ),
            ],
            options={
                "verbose_name": "Treffer",
                "verbose_name_plural": "Treffer",
                "ordering": ["number"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("scoring", "starter", "number"), name="competitions_treffer_nr"
                    )
                ],
            },
        ),
        migrations.RunPython(rls_on, rls_off),
    ]
