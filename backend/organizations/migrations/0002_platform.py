from django.db import migrations


def create_platform(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    PlatformSettings = apps.get_model("organizations", "PlatformSettings")
    Organization.objects.get_or_create(type="platform", defaults={"name": "hubiplan"})
    PlatformSettings.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0001_initial")]

    operations = [migrations.RunPython(create_platform, migrations.RunPython.noop)]
