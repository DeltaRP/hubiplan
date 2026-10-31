from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0005_veranstaltungen"),
    ]

    operations = [
        migrations.AddField(
            model_name="debitrun",
            name="xml",
            field=models.TextField(blank=True, default="", verbose_name="SEPA-Datei"),
        ),
    ]
