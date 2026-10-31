from django.db import migrations, models

import website.models


class Migration(migrations.Migration):
    dependencies = [
        ("website", "0010_bilderkarussell"),
    ]

    operations = [
        migrations.AddField(
            model_name="website",
            name="home_sections",
            field=models.JSONField(
                blank=True,
                default=website.models.default_home_sections,
                verbose_name="Bausteine der Startseite",
            ),
        ),
    ]
