from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("circulars", "0006_verteiler_absender")]

    operations = [
        migrations.AddField(
            model_name="circular",
            name="also_mail",
            field=models.BooleanField(default=False, verbose_name="zusätzlich per E-Mail"),
        ),
    ]
