"""2FA-Geheimnisse mit dem ersten Schlüssel aus MFA_ENCRYPTION_KEYS neu verschlüsseln."""

from allauth.mfa.models import Authenticator
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.mfa import rotate, transform_data
from core.tenancy import rls_bypass


class Command(BaseCommand):
    help = (
        "Verschlüsselt alle 2FA-Geheimnisse mit dem neuen Schlüssel (MFA_ENCRYPTION_KEYS=neu,alt)."
    )

    def handle(self, *args, **options):
        changed = 0
        with transaction.atomic(), rls_bypass():
            for item in Authenticator.objects.select_for_update():
                data = transform_data(item.type, item.data, rotate)
                if data != item.data:
                    item.data = data
                    item.save(update_fields=["data"])
                    changed += 1
        self.stdout.write(f"{changed} Einträge neu verschlüsselt.")
