from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0039_ruecklagen"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="website_on_site",
            field=models.BooleanField(
                db_default=False,
                default=False,
                verbose_name="Homepage auf der Webseite verlinken",
            ),
        ),
    ]
