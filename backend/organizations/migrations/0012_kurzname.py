from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0011_abteilungsbezeichnung_genus"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="short_name",
            field=models.CharField(
                blank=True,
                help_text="Optional, für Navigation, Listen und Auswahlfelder.",
                max_length=50,
                verbose_name="Kurzname",
            ),
        ),
        migrations.AddField(
            model_name="department",
            name="short_name",
            field=models.CharField(
                blank=True,
                help_text="Optional, für Navigation, Listen und Auswahlfelder.",
                max_length=50,
                verbose_name="Kurzname",
            ),
        ),
    ]
