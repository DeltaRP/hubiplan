from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0008_sprache"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="help_done",
            field=models.JSONField(blank=True, null=True, verbose_name="erledigte erste Schritte"),
        ),
    ]
