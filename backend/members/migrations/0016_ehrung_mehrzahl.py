"""Ehrung: Mehrzahl für die Überschrift auf der Webseite (leer: abgeleitet)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("members", "0015_ehrungen")]

    operations = [
        migrations.AddField(
            model_name="honorarytitle",
            name="name_plural",
            field=models.CharField("Mehrzahl", max_length=100, blank=True),
        ),
    ]
