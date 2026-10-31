import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("circulars", "0009_verteiler_weitere_adressen")]

    operations = [
        migrations.AddField(
            model_name="circular",
            name="mailing_list",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="circulars.mailinglist",
                verbose_name="Verteiler",
            ),
        ),
    ]
