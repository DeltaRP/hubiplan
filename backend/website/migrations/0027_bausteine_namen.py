from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("website", "0026_zusammenfuehrung"),
    ]

    operations = [
        migrations.AddField(
            model_name="website",
            name="block_names",
            field=models.JSONField(
                blank=True, default=dict, verbose_name="Eigene Namen der Bausteine"
            ),
        ),
    ]
