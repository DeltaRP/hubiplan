"""Ordnungszahl je Vorname (Schalter an der Würde, Zahl von Hand an der Regentschaft)
und Mehrzahl der Würde für die Webseite."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("honors", "0003_reign_end_year")]

    operations = [
        migrations.AddField(
            model_name="dignity",
            name="name_plural",
            field=models.CharField("Mehrzahl", max_length=100, blank=True),
        ),
        migrations.AddField(
            model_name="dignity",
            name="numbered",
            field=models.BooleanField("Ordnungszahl je Vorname", default=False),
        ),
        migrations.AddField(
            model_name="reign",
            name="ordinal",
            field=models.PositiveSmallIntegerField("Ordnungszahl", null=True, blank=True),
        ),
    ]
