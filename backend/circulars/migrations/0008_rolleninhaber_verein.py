from django.db import migrations, models


class Migration(migrations.Migration):
    # Führt auch die beiden parallel entstandenen 0007 zusammen
    dependencies = [
        ("circulars", "0007_zusaetzlich_mail"),
        ("circulars", "0007_status_abgearbeitet"),
    ]

    operations = [
        migrations.AlterField(
            model_name="circular",
            name="audience",
            field=models.CharField(
                choices=[
                    ("members", "Mitglieder"),
                    ("boards", "Vorstände der Vereine"),
                    ("departments", "Rolleninhaber der Abteilungen"),
                    ("roles", "Rolleninhaber des Vereins"),
                ],
                default="members",
                max_length=12,
                verbose_name="Empfängerkreis",
            ),
        ),
    ]
