from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("circulars", "0010_rundschreiben_an_verteiler")]

    operations = [
        migrations.AddField(
            model_name="mailinglist",
            name="open_senders",
            field=models.BooleanField(default=False, verbose_name="jeder darf schreiben"),
        ),
    ]
