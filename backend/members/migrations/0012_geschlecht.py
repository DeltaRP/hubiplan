"""Festes Feld Geschlecht an der Person; Werte aus einem Zusatzfeld „Geschlecht“ übernehmen."""

from django.db import migrations, models


def take_over(apps, schema_editor):
    from core.tenancy import rls_bypass
    from members.gender import take_over_field

    with rls_bypass():
        take_over_field(
            apps.get_model("members", "Person"),
            apps.get_model("customfields", "FieldDefinition"),
            apps.get_model("customfields", "FieldValue"),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0011_webseite"),
        ("customfields", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="gender",
            field=models.CharField(
                blank=True,
                choices=[("männlich", "männlich"), ("weiblich", "weiblich"), ("divers", "divers")],
                default="",
                max_length=10,
                verbose_name="Geschlecht",
            ),
        ),
        migrations.RunPython(take_over, migrations.RunPython.noop),
    ]
