"""Zuwendungsbestätigungen hängen am Schalter „steuerbegünstigt mit eigenem Bescheid“
statt am Registereintrag. Einheiten, die bisher als e.V. Bestätigungen ausstellen
konnten, bekommen den Schalter eingeschaltet."""

from django.db import migrations, models


def enable_registered(apps, schema_editor):
    Imprint = apps.get_model("organizations", "Imprint")
    DonationSettings = apps.get_model("finance", "DonationSettings")
    schema_editor.execute("SET LOCAL app.bypass_rls = 'on'")
    for imprint in Imprint.objects.filter(registered=True).exclude(
        organization__type="platform"
    ):
        DonationSettings.objects.update_or_create(
            organization_id=imprint.organization_id, defaults={"enabled": True}
        )


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0010_kontoumsatz_einzelposten"),
        ("organizations", "0033_mit_einheit_stillgelegt"),
    ]

    operations = [
        migrations.AddField(
            model_name="donationsettings",
            name="enabled",
            field=models.BooleanField(
                default=False, verbose_name="steuerbegünstigt mit eigenem Bescheid"
            ),
        ),
        migrations.RunPython(enable_registered, migrations.RunPython.noop),
    ]
