from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("oidc", "0002_rls")]

    operations = [
        migrations.AddField(
            model_name="client",
            name="usernames",
            field=models.TextField(blank=True, default="", verbose_name="bisherige Benutzernamen"),
        ),
    ]
