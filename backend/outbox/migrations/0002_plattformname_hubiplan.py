"""Plattform-Organisation von „hubiplan“ in „HUBIplan“ umbenennen.

Liegt bewusst in ``outbox`` statt in ``organizations``, damit sie nicht mit
dem laufenden Umbau der Organisationseinheiten um Migrationsnummern streitet.
Ein selbst vergebener anderer Name bleibt unangetastet.
"""

from django.db import migrations


def rename(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Organization.objects.filter(type="platform", name="hubiplan").update(name="HUBIplan")


def rename_back(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Organization.objects.filter(type="platform", name="HUBIplan").update(name="hubiplan")


class Migration(migrations.Migration):
    dependencies = [
        ("outbox", "0001_initial"),
        ("organizations", "0013_dachverband_name_grammatik"),
    ]

    operations = [migrations.RunPython(rename, rename_back)]
