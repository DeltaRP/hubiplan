from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("circulars", "0011_verteiler_offen")]

    operations = [
        migrations.AlterField(
            model_name="mailinglist",
            name="mode",
            field=models.CharField(
                choices=[
                    ("confirm", "Absender bestätigt per Link"),
                    ("draft", "als Entwurf in HUBIplan ablegen"),
                    ("direct", "direkt versenden (ohne Bestätigung)"),
                ],
                default="confirm",
                max_length=10,
                verbose_name="Versand",
            ),
        ),
    ]
