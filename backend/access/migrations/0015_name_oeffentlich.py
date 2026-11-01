"""Freie Namen früherer Inhaber nur mit Häkchen auf der Webseite (FQ-19, Ralf 01.11.2026).

Bestehende Einträge behalten ihren bisherigen Stand (sichtbar), damit die Webseite nicht
plötzlich Lücken hat; neue Einträge brauchen das Häkchen."""

from django.db import migrations, models


def bisherige_sichtbar(apps, schema_editor):
    RoleAssignment = apps.get_model("access", "RoleAssignment")
    RoleAssignment.objects.filter(
        user__isnull=True, membership__isnull=True, person__isnull=True
    ).exclude(name="").update(name_public=True)


class Migration(migrations.Migration):
    dependencies = [("access", "0014_fruehere_inhaber")]

    operations = [
        migrations.AddField(
            model_name="roleassignment",
            name="name_public",
            field=models.BooleanField(
                db_default=False,
                default=False,
                verbose_name="Name darf auf der Webseite erscheinen",
            ),
        ),
        migrations.RunPython(bisherige_sichtbar, migrations.RunPython.noop),
    ]
