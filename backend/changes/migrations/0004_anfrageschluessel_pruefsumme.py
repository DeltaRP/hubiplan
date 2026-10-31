from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("changes", "0003_anfrageschluessel"),
    ]

    operations = [
        migrations.AddField(
            model_name="requestkey",
            name="fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
