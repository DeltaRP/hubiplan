"""Änderungspakete löschen: nach Ablauf der Frist und bei Löschung einer Person."""

from __future__ import annotations

import datetime

from django.utils import timezone

from core.tenancy import rls_bypass

from .models import RETENTION_DAYS, ChangeRecord, ChangeSet


def purge_old(now: datetime.datetime | None = None) -> int:
    cutoff = (now or timezone.now()) - datetime.timedelta(days=RETENTION_DAYS)
    with rls_bypass():
        ChangeRecord.objects.filter(created_at__lt=cutoff).delete()
        count, _ = ChangeSet.objects.filter(created_at__lt=cutoff).delete()
    return count


def forget_person(organization_id: int, person_id: int) -> None:
    """Alle Pakete eines Vereins löschen, die Daten dieser Person enthalten."""
    sets = set(
        ChangeRecord.objects.filter(
            organization_id=organization_id, person_id=person_id
        ).values_list("change_set_id", flat=True)
    )
    if sets:
        ChangeRecord.objects.filter(change_set_id__in=sets).delete()
        ChangeSet.objects.filter(pk__in=sets).delete()
