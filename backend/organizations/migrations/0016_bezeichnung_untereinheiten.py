"""Bezeichnung der Untereinheiten auch für Dachverband und Plattform.

Im Dachverband heißen die Untereinheiten bisher fest „Vereine“, auf der
Plattform „Dachverbände und Vereine“. Jetzt stehen sie wie im Verein in den
Feldern ``department_label*`` und lassen sich in der App ändern.
"""

from django.db import migrations

CHILD_LABELS = {
    "federation": ("Verein", "Vereine", "m", "Vereins"),
    "platform": ("Einheit", "Einheiten", "f", ""),
}


def forwards(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    for org_type, (label, plural, gender, genitive) in CHILD_LABELS.items():
        Organization.objects.filter(type=org_type, department_label="Abteilung").update(
            department_label=label,
            department_label_plural=plural,
            department_label_gender=gender,
            department_label_genitive=genitive,
        )


def backwards(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Organization.objects.filter(type__in=list(CHILD_LABELS)).update(
        department_label="Abteilung",
        department_label_plural="Abteilungen",
        department_label_gender="f",
        department_label_genitive="",
    )


class Migration(migrations.Migration):
    dependencies = [("organizations", "0015_einheiten_rueckverweise")]

    operations = [migrations.RunPython(forwards, backwards)]
