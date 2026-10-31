"""Notfall: alle Geräte der App abmelden und alle Vorstandszugänge in der App sperren."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.tenancy import rls_bypass
from devices import webpush
from devices.models import Device


class Command(BaseCommand):
    help = (
        "Meldet alle Geräte ab (Mitglieder verbinden die App neu). --push-schluessel: auch den "
        "VAPID-Schlüssel neu erzeugen (beim nächsten Gebrauch)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--push-schluessel", action="store_true")

    def handle(self, *args, **options):
        with rls_bypass():
            count = Device.objects.filter(revoked_at__isnull=True).update(
                revoked_at=timezone.now(), admin_token_hash="", admin_until=None
            )
        self.stdout.write(f"{count} Geräte abgemeldet.")
        if options["push_schluessel"]:
            path = webpush.key_path()
            if path.exists():
                path.unlink()
                self.stdout.write(
                    f"{path} gelöscht. Neuer Schlüssel beim nächsten Gebrauch; "
                    "Backend und Worker danach neu starten."
                )
