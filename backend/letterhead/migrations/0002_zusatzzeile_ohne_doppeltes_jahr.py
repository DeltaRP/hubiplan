"""Vorbelegung „gegründet …“ entfernen, wenn das Jahr schon im Namen steht."""

from django.db import migrations


def forwards(apps, schema_editor):
    Letterhead = apps.get_model("letterhead", "Letterhead")
    for lh in Letterhead.objects.select_related("organization").exclude(tagline=""):
        org = lh.organization
        year = org.founding_year
        if year and lh.tagline.strip() == f"gegründet {year}" and str(year) in org.name:
            lh.tagline = ""
            lh.save(update_fields=["tagline"])


class Migration(migrations.Migration):
    dependencies = [("letterhead", "0001_initial")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
