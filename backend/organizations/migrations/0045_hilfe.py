from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0044_englische_bezeichnung"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="help_contacts",
            field=models.JSONField(
                blank=True,
                default=list,
                verbose_name="Ansprechpartner für Fragen zu HUBIplan",
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="help_notes",
            field=models.JSONField(
                blank=True,
                default=dict,
                verbose_name="Hinweise des Vereins zur Hilfe",
            ),
        ),
    ]
