"""Untereinheiten können selbst Untereinheiten haben; diese heißen zunächst „Gruppe“."""

from django.db import migrations


def forwards(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Organization.objects.filter(type="unit", department_label="Abteilung").update(
        department_label="Gruppe",
        department_label_plural="Gruppen",
        department_label_gender="f",
        department_label_genitive="",
    )


def backwards(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Organization.objects.filter(type="unit").update(
        department_label="Abteilung",
        department_label_plural="Abteilungen",
        department_label_gender="f",
        department_label_genitive="",
    )


class Migration(migrations.Migration):
    dependencies = [("organizations", "0016_bezeichnung_untereinheiten")]

    operations = [migrations.RunPython(forwards, backwards)]
