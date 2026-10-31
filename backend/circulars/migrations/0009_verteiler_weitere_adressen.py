from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("circulars", "0008_rolleninhaber_verein")]

    operations = [
        migrations.AddField(
            model_name="mailinglist",
            name="aliases",
            field=models.JSONField(blank=True, default=list, verbose_name="weitere Adressen"),
        ),
    ]
