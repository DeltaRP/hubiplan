"""Hintergrund-Jobs für den vollständigen Export und den Import (Celery)."""

from __future__ import annotations

import logging

from celery import shared_task
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from core import alarm
from core.tenancy import rls_bypass, tenant_context

from . import dump, load
from .models import TransferJob

logger = logging.getLogger(__name__)


def _load(pk: int) -> TransferJob:
    with rls_bypass():
        return TransferJob.objects.select_related(
            "organization", "subject", "created_by", "department__organization"
        ).get(pk=pk)


def _save(job: TransferJob) -> None:
    with tenant_context(job.organization_id):
        job.save()


@shared_task
def run_export(job_id: int) -> None:
    job = _load(job_id)
    job.status = TransferJob.Status.RUNNING
    _save(job)
    try:
        if job.kind == TransferJob.Kind.DEPARTMENT:
            content, name, counts = dump.export_department(
                job.department,
                with_files=job.with_files,
                spin_off=(job.options or {}).get("spin_off"),
            )
        else:
            content, name, counts = dump.export_organization(
                job.subject or job.organization,
                with_files=job.with_files,
                by_platform=bool(job.options.get("by_platform")),
            )
        job.file.save(name, ContentFile(content), save=False)
        job.file_name = name
        job.size = len(content)
        job.summary = counts
        job.status = TransferJob.Status.DONE
        alarm.export_finished(
            job.subject or job.organization, job.created_by, "vollständiger Datenexport", None
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Datenexport %s fehlgeschlagen", job_id)
        job.status = TransferJob.Status.FAILED
        job.error = str(exc)[:500]
    if (job.options or {}).get("spin_off"):
        # Ausgliederung: der Kopplungscode steht nur in der Datei, nicht mehr in der Datenbank
        job.options = {
            **job.options,
            "spin_off": {k: v for k, v in job.options["spin_off"].items() if k != "code"},
        }
    job.finished_at = timezone.now()
    _save(job)


@shared_task
def check_import(job_id: int) -> None:
    job = _load(job_id)
    try:
        job.preview = load.check(job)
        job.status = TransferJob.Status.CHECKED
        job.error = ""
    except load.FileProblem as exc:
        job.preview = {}
        job.status = TransferJob.Status.FAILED
        job.error = str(exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Importprüfung %s fehlgeschlagen", job_id)
        job.status = TransferJob.Status.FAILED
        job.error = f"Die Datei ließ sich nicht prüfen: {str(exc)[:300]}"
    _save(job)


@shared_task
def run_import(job_id: int) -> None:
    """Import einmalig ausführen (Gesamtaudit 30.10., B-F02).

    Der Auftrag wird gesperrt und nur im Zustand „läuft“ ausgeführt. Daten, Ergebnis und
    Zustand „fertig“ werden gemeinsam festgeschrieben: Eine doppelt zugestellte Aufgabe
    wartet auf die erste und tut dann nichts; ein Abbruch hinterlässt nichts halb.
    """
    try:
        with transaction.atomic():
            with rls_bypass():
                job = (
                    TransferJob.objects.select_for_update(of=("self",))
                    .select_related(
                        "organization", "subject", "created_by", "department__organization"
                    )
                    .get(pk=job_id)
                )
            if job.status != TransferJob.Status.RUNNING:
                logger.info("Import %s ist nicht (mehr) gestartet, nichts zu tun", job_id)
                return
            result = load.run(job, job.created_by)
            job.summary = result
            if "organization" in result:
                job.result_organization_id = result["organization"]["id"]
            if "department" in result:
                job.department_id = result["department"]["id"]
            job.status = TransferJob.Status.DONE
            job.error = ""
            job.finished_at = timezone.now()
            _save(job)
            _audit(job)
    except (ValidationError, load.FileProblem) as exc:
        _failed(job_id, "; ".join(getattr(exc, "messages", [str(exc)]))[:2000])
    except Exception as exc:  # noqa: BLE001
        logger.exception("Import %s fehlgeschlagen", job_id)
        _failed(
            job_id, f"Der Import ist fehlgeschlagen, es wurde nichts angelegt: {str(exc)[:300]}"
        )


def _failed(job_id: int, error: str) -> None:
    with transaction.atomic():
        with rls_bypass():
            job = TransferJob.objects.select_for_update().get(pk=job_id)
        if job.status != TransferJob.Status.RUNNING:
            return  # eine andere Ausführung war schon erfolgreich
        job.status = TransferJob.Status.CHECKED
        job.error = error
        job.finished_at = timezone.now()
        _save(job)


def _audit(job: TransferJob) -> None:
    from audit.log import record

    result = job.summary or {}
    created = result.get("organization") or result.get("department") or {}
    record(
        job.organization,
        job.created_by,
        "create",
        job,
        {
            "Import aus Datei": [None, job.file_name],
            "angelegt": [None, created.get("name")],
            "Einladungen": [None, result.get("invited", 0)],
        },
    )


@shared_task
def purge_expired() -> int:
    """Export- und Importdateien nach Ablauf löschen (täglich)."""
    count = 0
    with rls_bypass():
        for job in TransferJob.objects.filter(expires_at__lte=timezone.now()).exclude(file=""):
            job.file.delete(save=False)
            job.file = ""
            job.save(update_fields=["file"])
            count += 1
    return count
