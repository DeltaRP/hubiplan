"""Impressum: Schalter „im Register eingetragen“ (e.V. ja/nein)."""

import re

from django.db import migrations, models


def guess(apps, schema_editor):
    Imprint = apps.get_model("organizations", "Imprint")
    for imprint in Imprint.objects.select_related("organization"):
        name = imprint.name or imprint.organization.name
        if (
            imprint.register_court
            or imprint.register_number
            or "eingetragen" in imprint.legal_form.lower()
            or re.search(r"\be\.\s?V\.", name)
        ):
            imprint.registered = True
            imprint.save(update_fields=["registered"])


class Migration(migrations.Migration):
    dependencies = [("organizations", "0024_webseite")]

    operations = [
        migrations.AddField(
            model_name="imprint",
            name="registered",
            field=models.BooleanField(
                default=False,
                help_text="z. B. eingetragener Verein (e.V.) im Vereinsregister",
                verbose_name="im Register eingetragen",
            ),
        ),
        migrations.RunPython(guess, migrations.RunPython.noop),
    ]
