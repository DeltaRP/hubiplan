"""Hintergrund-Jobs für Import und Export (Celery)."""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core import alarm
from core.files import delete_on_commit
from core.tenancy import rls_bypass, tenant_context

from . import export, importer
from .models import EXPORT_KEEP_DAYS, IMPORT_KEEP_DAYS, ExportJob, ImportJob, private_storage

logger = logging.getLogger(__name__)


def _load(model, pk):
    # Auftrag zuerst systemweit laden, dann im Kontext seiner Organisation arbeiten
    with rls_bypass():
        return model.objects.select_related("organization", "created_by").get(pk=pk)


@shared_task
def run_export(job_id: int) -> None:
    job = _load(ExportJob, job_id)
    with tenant_context(job.organization_id, job.created_by_id):
        try:
            job.status = ExportJob.Status.RUNNING
            job.save(update_fields=["status"])
            content, name, count = export.build(job)
            job.file.save(name, ContentFile(content), save=False)
            job.file_name = name
            job.row_count = count
            job.status = ExportJob.Status.DONE
            alarm.export_finished(job.organization, job.created_by, f"Liste ({job.kind})", count)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Export %s fehlgeschlagen", job_id)
            job.status = ExportJob.Status.FAILED
            job.error = str(exc)[:500]
        job.finished_at = timezone.now()
        job.save()


@shared_task
def validate_import(job_id: int) -> None:
    job = _load(ImportJob, job_id)
    with tenant_context(job.organization_id, job.created_by_id):
        if job.status != ImportJob.Status.VALIDATING:
            logger.warning("Import %s ist nicht (mehr) zu prüfen", job_id)
            return
        try:
            groups = importer.validate(job)
            preview, counts = importer.preview_of(groups)
            fields = {"preview": preview, "counts": counts, "status": "validated", "error": ""}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Importprüfung %s fehlgeschlagen", job_id)
            fields = {"status": ImportJob.Status.FAILED, "error": str(exc)[:500]}
        # Nur schreiben, wenn der Auftrag noch geprüft wird (Audit 31.10. X-01)
        with transaction.atomic():
            locked = ImportJob.objects.select_for_update().get(pk=job_id)
            if locked.status != ImportJob.Status.VALIDATING:
                logger.warning("Import %s wurde während der Prüfung weitergeführt", job_id)
                return
            for key, value in fields.items():
                setattr(locked, key, value)
            locked.save(update_fields=list(fields))


@shared_task
def run_import(job_id: int) -> None:
    job = _load(ImportJob, job_id)
    with tenant_context(job.organization_id, job.created_by_id):
        try:
            with transaction.atomic():
                # Doppelt zugestellter Auftrag: nur einmal importieren, sonst würde das
                # Importjournal (für „Rückgängig“) überschrieben
                locked = (
                    ImportJob.objects.select_for_update(of=("self",))
                    .select_related("organization", "created_by")
                    .get(pk=job_id)
                )
                if locked.status != ImportJob.Status.IMPORTING:
                    logger.warning("Import %s ist nicht (mehr) zu importieren", job_id)
                    return
                importer.run(locked, locked.created_by)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Import %s fehlgeschlagen", job_id)
            job.refresh_from_db()
            job.status = ImportJob.Status.FAILED
            job.error = str(exc)[:500]
            job.save()


# Verwaiste Dateien erst ab diesem Alter löschen: ein Auftrag, der gerade schreibt, hat
# seine Datei womöglich noch nicht in der Datenbank vermerkt
ORPHAN_MIN_AGE = timedelta(days=1)


@shared_task
def purge_expired() -> dict[str, int]:
    """Listen-Exporte nach 7 Tagen, Importe 30 Tage nach Abschluss löschen (täglich).

    Gelöscht werden die Dateien, Vorschau und Beispielzeilen sowie das Journal für
    „Rückgängig“. Der Auftrag selbst und der Protokolleintrag bleiben stehen.
    """
    now = timezone.now()
    counts = {"exports": 0, "imports": 0, "orphans": 0}
    with rls_bypass():
        export_cut = now - timedelta(days=EXPORT_KEEP_DAYS)
        for job in ExportJob.objects.filter(purged_at__isnull=True).filter(
            Q(finished_at__lte=export_cut) | Q(finished_at__isnull=True, created_at__lte=export_cut)
        ):
            if job.file:
                job.file.delete(save=False)
            job.file = ""
            job.purged_at = now
            job.save(update_fields=["file", "purged_at"])
            counts["exports"] += 1

        import_cut = now - timedelta(days=IMPORT_KEEP_DAYS)
        busy = (ImportJob.Status.VALIDATING, ImportJob.Status.IMPORTING)
        candidates = ImportJob.objects.filter(
            purged_at__isnull=True, created_at__lte=import_cut
        ).exclude(status__in=busy)
        for pk in candidates.values_list("pk", flat=True):
            if _purge_import(pk, import_cut, busy, now):
                counts["imports"] += 1

        counts["orphans"] = _purge_orphans(now)
    if any(counts.values()):
        logger.info("Listen-Import/-Export aufgeräumt: %s", counts)
    return counts


@transaction.atomic
def _purge_import(pk: int, import_cut, busy, now) -> bool:
    """Einen Import aufräumen, unter Zeilensperre und mit frischem Stand (Audit 31.10.
    R-X-01): Ein gerade fertig gewordener Import behält Journal und Frist."""
    job = ImportJob.objects.select_for_update().filter(pk=pk).first()
    if job is None or job.purged_at or job.status in busy:
        return False
    # Frist ab dem letzten Schritt (Import oder Rückgängig), sonst ab dem Hochladen
    last = max(t for t in (job.created_at, job.imported_at, job.undone_at) if t)
    if last > import_cut:
        return False
    # Dateien erst nach dem Speichern löschen
    delete_on_commit(job.file, job.error_file)
    job.file = ""
    job.error_file = ""
    job.headers = []
    job.sample = []
    job.preview = []
    job.value_mapping = {}
    job.created = {}
    job.purged_at = now
    job.save(
        update_fields=[
            "file",
            "error_file",
            "headers",
            "sample",
            "preview",
            "value_mapping",
            "created",
            "purged_at",
        ]
    )
    return True


def _purge_orphans(now) -> int:
    """Dateien unter exports/ und imports/ löschen, auf die kein Auftrag mehr zeigt."""
    storage = private_storage()
    used = set()
    for name in ExportJob.objects.exclude(file="").values_list("file", flat=True):
        used.add(name)
    for file, error_file in ImportJob.objects.values_list("file", "error_file"):
        used.update(n for n in (file, error_file) if n)
    count = 0
    for top in ("exports", "imports"):
        for name in _walk(storage, top):
            if name in used:
                continue
            try:
                modified = storage.get_modified_time(name)
            except OSError:
                continue
            if now - modified < ORPHAN_MIN_AGE:
                continue
            storage.delete(name)
            count += 1
    return count


def _walk(storage, path: str):
    try:
        dirs, files = storage.listdir(path)
    except FileNotFoundError:
        return
    for f in files:
        yield f"{path}/{f}"
    for d in dirs:
        yield from _walk(storage, f"{path}/{d}")
