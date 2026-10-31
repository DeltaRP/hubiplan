# Bezeichnung „Ehrentitel“ heißt jetzt „Ehrungen“ (nur Anzeige, keine Datenänderung).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0014_foto_aus_app"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="honorarytitle",
            options={
                "ordering": ["sort_order", "name"],
                "verbose_name": "Ehrung",
                "verbose_name_plural": "Ehrungen",
            },
        ),
        migrations.AlterModelOptions(
            name="honorarytitleaward",
            options={
                "ordering": ["valid_from"],
                "verbose_name": "Ehrung (Verleihung)",
                "verbose_name_plural": "Ehrungen (Verleihungen)",
            },
        ),
    ]
