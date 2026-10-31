from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("website", "0016_ohne_konto_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="websiteimage",
            name="decorative",
            field=models.BooleanField(default=False, verbose_name="nur Schmuck"),
        ),
    ]
