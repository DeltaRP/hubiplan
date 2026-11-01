"""Alte Startpasswörter zählen und auf Einladungslinks umstellen (FQ-16, Ralf 01.11.2026).

Ohne Schalter nur die Anzahl (keine Namen oder Adressen). Mit ``--umstellen`` wird jedes
noch ausgegebene Startpasswort unbrauchbar und die Person bekommt einen Link, mit dem sie
ihr Passwort selbst festlegt."""

from django.core.management.base import BaseCommand

from accounts.models import User
from accounts.tasks import convert_initial_passwords
from core.tenancy import rls_bypass


class Command(BaseCommand):
    help = "Zählt alte Startpasswörter; mit --umstellen werden sie durch Einladungslinks ersetzt."

    def add_arguments(self, parser):
        parser.add_argument("--umstellen", action="store_true", help="jetzt umstellen")

    def handle(self, *args, **options):
        with rls_bypass():
            count = User.objects.filter(initial_password_expires__isnull=False).count()
        self.stdout.write(f"{count} Konten haben noch ein Startpasswort.")
        if options["umstellen"] and count:
            converted, sent = convert_initial_passwords()
            self.stdout.write(f"{converted} umgestellt, {sent} Links verschickt.")
