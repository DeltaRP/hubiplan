from django.db import migrations, models

CHOICES = [("day", "tagesgenau"), ("month", "monatsgenau"), ("year", "jahresgenau")]


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0009_abteilungsrolle_reihenfolge"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="date_precision",
            field=models.CharField(
                choices=CHOICES,
                default="day",
                max_length=10,
                verbose_name="Genauigkeit für Mitgliedschaften und Jubiläen",
            ),
        ),
        migrations.AddField(
            model_name="department",
            name="date_precision",
            field=models.CharField(
                blank=True,
                choices=CHOICES,
                default="",
                help_text="Leer: wie der Verein.",
                max_length=10,
                verbose_name="Genauigkeit für Mitgliedschaften",
            ),
        ),
    ]
