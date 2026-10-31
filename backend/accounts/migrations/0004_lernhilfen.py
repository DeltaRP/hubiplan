"""Lernhilfen: Schalter und ausgeblendete Erklärungen am Konto.

Bestehende Konten bekommen den Schalter AUS (sie kennen die Anwendung ohne
Lernhilfen), neue Konten starten mit EIN.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_mfa_geheimnisse_verschluesseln")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="learning_aids",
            field=models.BooleanField(default=False, verbose_name="Lernhilfen zeigen"),
        ),
        migrations.AlterField(
            model_name="user",
            name="learning_aids",
            field=models.BooleanField(default=True, verbose_name="Lernhilfen zeigen"),
        ),
        migrations.AddField(
            model_name="user",
            name="learning_hidden",
            field=models.JSONField(
                blank=True, null=True, verbose_name="ausgeblendete Erklärungen"
            ),
        ),
    ]
