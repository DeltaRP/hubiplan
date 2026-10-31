# Gründungsurkunde als dritte Dokumentart (Ralf 2026-10-31).
# Ändert nur die Auswahlliste von ``kind``; in der Datenbank passiert nichts.

from django.db import migrations, models

KINDS = [
    ("statute", "Satzung"),
    ("fee_rules", "Beitragsordnung"),
    ("founding_deed", "Gründungsurkunde"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("statutes", "0003_beitragsordnung"),
    ]

    operations = [
        migrations.AlterField(
            model_name="statutepublication",
            name="kind",
            field=models.CharField(
                choices=KINDS, default="statute", max_length=20, verbose_name="Art"
            ),
        ),
        migrations.AlterField(
            model_name="statuteversion",
            name="kind",
            field=models.CharField(
                choices=KINDS, default="statute", max_length=20, verbose_name="Art"
            ),
        ),
    ]
