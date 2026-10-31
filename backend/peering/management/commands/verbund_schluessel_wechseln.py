"""Schlüssel der Instanz im Verbund wechseln (auch ohne Anmeldung im Browser, z. B. im Notfall)."""

from django.core.management.base import BaseCommand

from core.tenancy import rls_bypass
from peering import keys


class Command(BaseCommand):
    help = (
        "Wechselt die Verbund-Schlüssel dieser Instanz und teilt sie allen Partnern mit. "
        "--notfall: alter Schlüssel gilt sofort nicht mehr, Partner müssen bestätigen."
    )

    def add_arguments(self, parser):
        parser.add_argument("--notfall", action="store_true", help="Notfallwechsel")

    def handle(self, *args, **options):
        with rls_bypass():
            ident = keys.rotate(None, emergency=options["notfall"])
            results = keys.announce_all()
        self.stdout.write(f"Neuer Fingerabdruck: {ident.fingerprint}")
        for base_url, result in sorted(results.items()):
            text = {"applied": "übernommen", "pending": "wartet auf Bestätigung dort"}.get(
                result, f"nicht erreicht ({result}), wird täglich wiederholt"
            )
            self.stdout.write(f"  {base_url}: {text}")
        if options["notfall"]:
            self.stdout.write(
                "Den neuen Fingerabdruck jedem Partner auf anderem Weg (Telefon) mitteilen."
            )
