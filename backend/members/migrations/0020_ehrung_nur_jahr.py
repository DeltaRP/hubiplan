from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0019_fern_gefuehrt"),
    ]

    operations = [
        migrations.AddField(
            model_name="honorarytitle",
            name="year_only",
            field=models.BooleanField(
                db_default=False, default=False, verbose_name="nur Jahr der Verleihung"
            ),
        ),
    ]
