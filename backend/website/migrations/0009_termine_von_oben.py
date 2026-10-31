from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("website", "0008_datenschutz_entwurf"),
    ]

    operations = [
        migrations.AddField(
            model_name="website",
            name="include_parent_events",
            field=models.BooleanField(
                default=False,
                verbose_name="Termine der übergeordneten Einheiten im Kalender der Webseite",
            ),
        ),
    ]
