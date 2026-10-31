"""Gesamtaudit I-S02: vorhandene 2FA-Geheimnisse verschlüsseln."""

from django.db import migrations


def encrypt_all(apps, schema_editor):
    from accounts.mfa import encrypt, transform_data
    from core.tenancy import rls_bypass

    Authenticator = apps.get_model("mfa", "Authenticator")
    with rls_bypass():
        for item in Authenticator.objects.all():
            data = transform_data(item.type, item.data, encrypt)
            if data != item.data:
                item.data = data
                item.save(update_fields=["data"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_email_change"),
        ("mfa", "0003_authenticator_type_uniq"),
    ]

    operations = [migrations.RunPython(encrypt_all, migrations.RunPython.noop)]
