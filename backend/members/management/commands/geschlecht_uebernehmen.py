"""Geschlecht aus einem Zusatzfeld „Geschlecht“ in das feste Feld übernehmen.

Die Migration macht das einmal beim Ausrollen. Wurde danach noch in das
Zusatzfeld importiert, holt dieser Befehl die neuen Werte nach. Das Zusatzfeld
bleibt bestehen und kann danach in der Einrichtung archiviert werden.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from core.tenancy import rls_bypass
from customfields.models import FieldDefinition, FieldValue
from members.gender import take_over_field
from members.models import Person


class Command(BaseCommand):
    help = "Übernimmt Werte eines Zusatzfelds „Geschlecht“ in das feste Feld Geschlecht."

    def handle(self, *args, **options):
        with transaction.atomic(), rls_bypass():
            count = take_over_field(Person, FieldDefinition, FieldValue)
        self.stdout.write(f"Geschlecht bei {count} Personen übernommen.")
