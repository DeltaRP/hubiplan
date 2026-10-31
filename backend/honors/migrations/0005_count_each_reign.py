"""Ordnungszahl: einstellbar, ob dieselbe Person bei jeder Regentschaft neu gezählt wird."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("honors", "0004_ordinal")]

    operations = [
        migrations.AddField(
            model_name="dignity",
            name="count_each_reign",
            field=models.BooleanField("bei mehrfacher Würde neu zählen", default=False),
        ),
    ]
