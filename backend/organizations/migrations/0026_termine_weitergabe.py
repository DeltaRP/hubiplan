from django.db import migrations, models


def units_share_up(apps, schema_editor):
    # Bisher erschienen Termine von Untereinheiten immer auch darüber
    Organization = apps.get_model("organizations", "Organization")
    Organization.objects.filter(type="unit").update(events_share_up=True)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0025_imprint_registered")]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="events_share_up",
            field=models.BooleanField(
                default=False,
                help_text="Die eigenen Termine erscheinen im Kalender der übergeordneten Einheit.",
                verbose_name="eigene Termine nach oben freigeben",
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="events_share_down",
            field=models.BooleanField(
                default=True,
                help_text="Die eigenen Termine erscheinen bei den Untereinheiten und ihren "
                "Mitgliedern.",
                verbose_name="eigene Termine nach unten freigeben",
            ),
        ),
        migrations.RunPython(units_share_up, migrations.RunPython.noop),
    ]
