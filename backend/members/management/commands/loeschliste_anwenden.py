from django.core.management.base import BaseCommand

from members import loeschliste


class Command(BaseCommand):
    help = "Erledigte Löschungen erneut anwenden (z. B. nach dem Einspielen eines Backups)."

    def handle(self, *args, **options):
        count = loeschliste.apply()
        self.stdout.write(f"Löschliste: {count} Mitgliedschaften erneut gelöscht.")
