from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("events", "0003_veranstaltungen")]

    operations = [
        migrations.AddField(
            model_name="event",
            name="share_up",
            field=models.BooleanField(blank=True, null=True, verbose_name="nach oben freigeben"),
        ),
        migrations.AddField(
            model_name="event",
            name="share_down",
            field=models.BooleanField(blank=True, null=True, verbose_name="nach unten freigeben"),
        ),
    ]
