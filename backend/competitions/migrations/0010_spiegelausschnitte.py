"""Schießscheiben Schritt 6: bestätigte Spiegelausschnitte sammeln (nur mit Einwilligung
des Vereins), mit Row-Level Security."""

import django.db.models.deletion
from django.db import migrations, models

from core.rls import disable_rls_sql, enable_rls_sql

TABLES = ("competitions_photosample", "competitions_photosampleconsent")


def rls_on(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(enable_rls_sql(table))


def rls_off(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for table in TABLES:
            schema_editor.execute(disable_rls_sql(table))


class Migration(migrations.Migration):
    dependencies = [
        ("competitions", "0009_scheiben_treffer"),
        ("organizations", "0042_dokumentbudget"),
    ]

    operations = [
        migrations.CreateModel(
            name="PhotoSample",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("target", models.CharField(max_length=30, verbose_name="Scheibe")),
                (
                    "target_data",
                    models.JSONField(default=dict, verbose_name="Maße der Scheibe"),
                ),
                ("image", models.BinaryField(verbose_name="Ausschnitt (JPEG)")),
                (
                    "px_per_mm",
                    models.DecimalField(
                        decimal_places=2, max_digits=6, verbose_name="Bildpunkte je mm"
                    ),
                ),
                (
                    "hits",
                    models.JSONField(default=list, verbose_name="bestätigte Treffer (mm)"),
                ),
                (
                    "detected",
                    models.JSONField(default=list, verbose_name="erkannte Treffer (mm)"),
                ),
                (
                    "created_on",
                    models.DateField(auto_now_add=True, verbose_name="gesammelt am"),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={
                "verbose_name": "Spiegelausschnitt",
                "verbose_name_plural": "Spiegelausschnitte",
                "ordering": ["-id"],
            },
        ),
        migrations.CreateModel(
            name="PhotoSampleConsent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "enabled",
                    models.BooleanField(default=False, verbose_name="Spiegelausschnitte sammeln"),
                ),
                ("changed_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={
                "verbose_name": "Einwilligung Spiegelausschnitte",
                "verbose_name_plural": "Einwilligungen Spiegelausschnitte",
            },
        ),
        migrations.RunPython(rls_on, rls_off),
    ]
