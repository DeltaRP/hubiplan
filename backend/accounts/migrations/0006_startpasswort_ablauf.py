from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_unterschrift"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="initial_password_expires",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Startpasswort gültig bis"
            ),
        ),
    ]
