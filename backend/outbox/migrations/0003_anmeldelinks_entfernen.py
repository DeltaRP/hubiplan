"""Anmelde-, Passwort- und Bestätigungslinks aus gespeicherten Mails entfernen.

Sie stehen nur in der verschickten Mail; der Postausgang einer Einheit soll sie
nicht zeigen (Gesamtaudit A-S01).
"""

from django.db import migrations


def redact_existing(apps, schema_editor):
    from django.db.models import Q

    from outbox.backend import redact

    OutgoingMail = apps.get_model("outbox", "OutgoingMail")
    paths = ("/anmelden/link/", "/passwort-zuruecksetzen/", "/konto/email/")
    found = Q()
    for path in paths:
        found |= Q(body__contains=path)
    for mail in OutgoingMail.objects.filter(found).iterator():
        mail.body = redact(mail.body)
        mail.save(update_fields=["body"])


class Migration(migrations.Migration):
    dependencies = [("outbox", "0002_plattformname_hubiplan")]

    operations = [migrations.RunPython(redact_existing, migrations.RunPython.noop)]
