from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("oidc", "0003_bisherige_benutzernamen")]

    operations = [
        migrations.AlterField(
            model_name="client",
            name="audience",
            field=models.CharField(
                choices=[
                    ("board", "Vorstand und Rollen"),
                    ("roles", "nur Rollen dieser Einheit"),
                    ("members", "zusätzlich Mitglieder mit Zugang"),
                ],
                default="board",
                max_length=10,
                verbose_name="Wer darf sich anmelden",
            ),
        ),
    ]
