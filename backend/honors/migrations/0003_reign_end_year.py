"""Regentschaft: optionales Endjahr (Startjahr/Endjahr ohne genaues Datum)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("honors", "0002_rls")]

    operations = [
        migrations.AddField(
            model_name="reign",
            name="end_year",
            field=models.PositiveSmallIntegerField("bis Jahr", null=True, blank=True),
        ),
    ]
