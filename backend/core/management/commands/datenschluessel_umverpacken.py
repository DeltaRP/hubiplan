"""Alle Datenschlüssel mit der ersten Schlüsselquelle bzw. dem ersten Hauptschlüssel neu
verpacken (Wechsel des Hauptschlüssels oder der Quelle, z. B. zu einem externen
Schlüsseldienst). Die verschlüsselten Daten selbst bleiben unverändert."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core import crypto
from core.models import DataKey


class Command(BaseCommand):
    help = "Datenschlüssel mit dem neuen Hauptschlüssel verpacken (Daten bleiben unverändert)."

    def handle(self, *args, **options):
        count = 0
        with transaction.atomic():
            for row in DataKey.objects.select_for_update().order_by("pk"):
                context = crypto._context(row.organization_id)
                key = crypto.unwrap_key(row.wrapped, context)
                row.wrapped = crypto.wrap_key(key, context)
                row.rewrapped_at = timezone.now()
                row.save(update_fields=["wrapped", "rewrapped_at"])
                count += 1
        crypto.reset()
        self.stdout.write(f"{count} Datenschlüssel neu verpackt.")
