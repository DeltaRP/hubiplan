from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0034_farbpalette"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="fee_exempt",
            field=models.BooleanField(
                default=False,
                help_text="Mitglieder dieser Einheit und der Einheiten darunter zahlen keinen Beitrag.",
                verbose_name="Mitglieder beitragsfrei",
            ),
        ),
    ]
