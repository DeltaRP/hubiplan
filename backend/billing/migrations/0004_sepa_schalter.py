"""SEPA-Lastschrift ein- und ausschaltbar.

Bestehende Organisationen, die Lastschrift schon eingerichtet oder genutzt haben
(Gläubiger-ID, Mandate oder Lastschriftläufe), behalten sie eingeschaltet.
"""

from django.db import migrations, models


def forwards(apps, schema_editor):
    BillingSettings = apps.get_model("billing", "BillingSettings")
    Mandate = apps.get_model("billing", "Mandate")
    DebitRun = apps.get_model("billing", "DebitRun")
    used = set(Mandate.objects.values_list("organization_id", flat=True))
    used |= set(DebitRun.objects.values_list("organization_id", flat=True))
    for cfg in BillingSettings.objects.all():
        if cfg.creditor_id or cfg.organization_id in used:
            cfg.sepa_enabled = True
            cfg.save(update_fields=["sepa_enabled"])


class Migration(migrations.Migration):
    dependencies = [("billing", "0003_sepa_lastschrift")]

    operations = [
        migrations.AddField(
            model_name="billingsettings",
            name="sepa_enabled",
            field=models.BooleanField(default=False, verbose_name="SEPA-Lastschrift nutzen"),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
