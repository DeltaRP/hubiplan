from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework import serializers, status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import EXPORT_RUN, MEMBERS_EDIT
from audit.log import record
from core import jobquota
from core.api_base import AuditMixin, OrgScopedMixin
from core.tasks import enqueue

from . import export, importer, tasks
from .models import (
    EXPORT_KEEP_DAYS,
    IMPORT_KEEP_DAYS,
    ExportJob,
    ExportTemplate,
    ImportJob,
    ImportTemplate,
)
from .reading import ReadError, read_stored_table

CLUB = ("club",)
MAX_UPLOAD = 10 * 1024 * 1024


class _OrgCtx:
    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["org"] = getattr(self, "org", None)
        return ctx


# --- Export ---


class ColumnsView(OrgScopedMixin, APIView):
    """Verfügbare Spalten für den Export (inkl. Zusatzfelder)."""

    read_permission = EXPORT_RUN
    allowed_org_types = ("club", "federation")

    def get(self, request, org_id: int):
        if self.org.type == "federation":
            cols = export.federation_columns(self.org)
            return Response(
                {"federation_members": [{"key": c.key, "label": c.label} for c in cols]}
            )
        return Response(
            {
                "members": [
                    {"key": c.key, "label": c.label} for c in export.member_columns(self.org)
                ],
                "jubilees": [{"key": c.key, "label": c.label} for c in export.jubilee_columns()],
            }
        )


class ExportTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExportTemplate
        fields = ["id", "name", "kind", "columns", "filters", "file_format", "orientation"]


class ExportTemplateViewSet(_OrgCtx, OrgScopedMixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = ExportTemplateSerializer
    read_permission = EXPORT_RUN
    write_permission = EXPORT_RUN
    allowed_org_types = ("club", "federation")

    def get_queryset(self):
        return ExportTemplate.objects.filter(organization=self.org)

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}


class ExportJobSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    # Fachfrage 13 (Audit 31.10.): Frist sichtbar machen
    keep_until = serializers.SerializerMethodField()

    class Meta:
        model = ExportJob
        fields = [
            "id",
            "kind",
            "file_format",
            "columns",
            "filters",
            "orientation",
            "title",
            "status",
            "status_label",
            "file_name",
            "row_count",
            "error",
            "created_at",
            "finished_at",
            "purged_at",
            "keep_until",
        ]
        read_only_fields = [
            "status",
            "file_name",
            "row_count",
            "error",
            "created_at",
            "finished_at",
            "purged_at",
        ]

    def get_keep_until(self, obj) -> datetime | None:
        if obj.purged_at:
            return None
        start = obj.finished_at or obj.created_at
        return start + timedelta(days=EXPORT_KEEP_DAYS) if start else None

    def validate_kind(self, value):
        org = self.context["org"]
        if org.type == "federation":
            if value != "federation_members":
                raise serializers.ValidationError(
                    gettext("Dachverbände exportieren die Verbandsliste.")
                )
            if org.federation_member_access == "none":
                raise serializers.ValidationError(
                    gettext("Kein Zugriff auf Mitgliedsdaten freigegeben.")
                )
            return value
        if value not in ("members", "jubilees"):
            raise serializers.ValidationError(gettext("Unbekannte Liste."))
        return value

    def validate_file_format(self, value):
        if value not in ("xlsx", "pdf"):
            raise serializers.ValidationError(gettext("Bitte Excel oder PDF wählen."))
        return value

    def validate_orientation(self, value):
        if value not in ("portrait", "landscape"):
            raise serializers.ValidationError(gettext("Hoch- oder Querformat."))
        return value

    def validate(self, attrs):
        if attrs.get("kind") == "jubilees":
            f = attrs.get("filters", {})
            if not (f.get("von") and f.get("bis")):
                raise serializers.ValidationError(
                    {"filters": gettext("Zeitraum (von, bis) angeben.")}
                )
        kind = attrs.get("kind")
        if kind == "jubilees":
            cols = export.jubilee_columns()
        elif kind == "federation_members":
            cols = export.federation_columns(self.context["org"])
        else:
            cols = export.member_columns(self.context["org"])
        allowed = {c.key for c in cols}
        unknown = [c for c in attrs.get("columns", []) if c not in allowed]
        if unknown:
            raise serializers.ValidationError(
                {"columns": gettext("Unbekannte Spalten: {x}").format(x=", ".join(unknown))}
            )
        return attrs


class ExportJobViewSet(_OrgCtx, OrgScopedMixin, viewsets.ModelViewSet):
    """Export anstoßen (läuft im Hintergrund), Status abfragen, Datei laden."""

    serializer_class = ExportJobSerializer
    read_permission = EXPORT_RUN
    write_permission = EXPORT_RUN
    allowed_org_types = ("club", "federation")
    http_method_names = ["get", "post", "options", "head"]

    def get_queryset(self):
        return (
            ExportJob.objects.filter(organization=self.org)[:50]
            if self.action == "list"
            else (ExportJob.objects.filter(organization=self.org))
        )

    def perform_create(self, serializer):
        jobquota.ensure_capacity(
            ExportJob.objects.filter(organization=self.org),
            active_statuses=[ExportJob.Status.PENDING, ExportJob.Status.RUNNING],
            max_active=3,
            max_per_hour=60,
            what="Listen-Exporte",
        )
        job = serializer.save(organization=self.org, created_by=self.request.user)
        # Jeder Export wird protokolliert: wer, wann, welche Felder
        member_cols = export.member_columns(self.org) if self.org.type == "club" else []
        labels = {
            c.key: c.label
            for c in member_cols + export.jubilee_columns() + export.federation_columns(self.org)
        }
        record(
            self.org,
            self.request.user,
            "create",
            job,
            {
                "Liste": [None, "Jubiläen" if job.kind == "jubilees" else "Mitglieder"],
                "Format": [None, job.file_format.upper()],
                "Spalten": [None, ", ".join(labels.get(c, c) for c in job.columns)],
                "Filter": [None, job.filters],
            },
        )
        enqueue(tasks.run_export, job, failed_status=ExportJob.Status.FAILED)


class ExportDownloadView(OrgScopedMixin, APIView):
    read_permission = EXPORT_RUN
    allowed_org_types = ("club", "federation")

    def get(self, request, org_id: int, pk: int):
        job = get_object_or_404(
            ExportJob, organization=self.org, pk=pk, status=ExportJob.Status.DONE
        )
        if job.purged_at or not job.file:
            raise serializers.ValidationError(
                gettext(
                    "Die Datei wurde nach {EXPORT_KEEP_DAYS} Tagen gelöscht. Bitte neu erstellen."
                ).format(EXPORT_KEEP_DAYS=EXPORT_KEEP_DAYS)
            )
        return FileResponse(job.file.open("rb"), as_attachment=True, filename=job.file_name)


# --- Import ---


class ImportTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportTemplate
        fields = ["id", "name", "mapping", "value_mapping"]


class ImportTemplateViewSet(_OrgCtx, OrgScopedMixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = ImportTemplateSerializer
    read_permission = MEMBERS_EDIT
    write_permission = MEMBERS_EDIT
    allowed_org_types = CLUB

    def get_queryset(self):
        return ImportTemplate.objects.filter(organization=self.org)

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}


class ImportJobSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    has_error_file = serializers.SerializerMethodField()
    undo_blockers = serializers.SerializerMethodField()
    keep_until = serializers.SerializerMethodField()

    class Meta:
        model = ImportJob
        fields = [
            "id",
            "file_name",
            "status",
            "status_label",
            "headers",
            "sample",
            "row_count",
            "mapping",
            "value_mapping",
            "options",
            "preview",
            "counts",
            "error",
            "created_at",
            "imported_at",
            "undone_at",
            "purged_at",
            "has_error_file",
            "undo_blockers",
            "keep_until",
        ]
        read_only_fields = [f for f in fields if f not in ("mapping", "value_mapping", "options")]

    def get_keep_until(self, obj) -> datetime | None:
        """Bis wann Protokoll und Rücknahme bleiben: 30 Tage ab dem letzten Schritt."""
        if obj.purged_at:
            return None
        last = max(t for t in (obj.created_at, obj.imported_at, obj.undone_at) if t)
        return last + timedelta(days=IMPORT_KEEP_DAYS)

    def get_has_error_file(self, obj) -> bool:
        return bool(obj.error_file)

    def get_undo_blockers(self, obj) -> list[str]:
        if obj.purged_at:
            return [f"Die Frist für „Rückgängig“ ({IMPORT_KEEP_DAYS} Tage) ist abgelaufen."]
        return importer.undo_blockers(obj) if obj.status == ImportJob.Status.IMPORTED else []

    def validate_mapping(self, value):
        targets = importer.targets_for(self.context["org"])
        result = {}
        for col, target in value.items():
            if target in ("", None, "ignore"):
                continue
            if target not in targets:
                raise serializers.ValidationError(
                    gettext("Unbekanntes Feld: {target}").format(target=target)
                )
            if target in result.values():
                raise serializers.ValidationError(
                    gettext("„{x}“ ist mehrfach zugeordnet.").format(x=targets[target])
                )
            result[str(col)] = target
        return result


class ImportJobViewSet(_OrgCtx, OrgScopedMixin, viewsets.ModelViewSet):
    serializer_class = ImportJobSerializer
    read_permission = MEMBERS_EDIT
    write_permission = MEMBERS_EDIT
    allowed_org_types = CLUB
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "options", "head"]

    def get_queryset(self):
        return ImportJob.objects.filter(organization=self.org)

    def create(self, request, *args, **kwargs):
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": gettext("Bitte eine Datei wählen.")})
        if upload.size > MAX_UPLOAD:
            raise serializers.ValidationError({"file": gettext("Die Datei ist größer als 10 MB.")})
        jobquota.ensure_capacity(
            ImportJob.objects.filter(organization=self.org),
            active_statuses=[ImportJob.Status.VALIDATING, ImportJob.Status.IMPORTING],
            max_active=3,
            max_per_hour=60,
            what="Listen-Importe",
        )
        name = Path(upload.name).name
        job = ImportJob(organization=self.org, created_by=request.user, file_name=name)
        job.file.save(f"{job.organization_id}-{name}", upload, save=False)
        try:
            headers, rows = read_stored_table(job.file, name)
        except ReadError as exc:
            job.file.delete(save=False)
            raise serializers.ValidationError({"file": str(exc)}) from exc
        job.headers = headers
        job.sample = [[_json(v) for v in r] for r in rows[:5]]
        job.row_count = len(rows)
        job.mapping = importer.suggest_mapping(headers, self.org)
        job.options = {"link_duplicates": True}
        job.save()
        return Response(self.get_serializer(job).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        job = serializer.instance
        if job.purged_at:
            raise serializers.ValidationError(
                gettext(
                    "Dieser Import ist älter als {IMPORT_KEEP_DAYS} Tage und abgelaufen."
                ).format(IMPORT_KEEP_DAYS=IMPORT_KEEP_DAYS)
            )
        if job.status not in (
            ImportJob.Status.UPLOADED,
            ImportJob.Status.VALIDATED,
            ImportJob.Status.FAILED,
        ):
            raise serializers.ValidationError(gettext("Dieser Import ist schon gelaufen."))
        serializer.save(status=ImportJob.Status.UPLOADED, preview=[], counts={})


def _json(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


class ImportTargetsView(OrgScopedMixin, APIView):
    read_permission = MEMBERS_EDIT
    allowed_org_types = CLUB

    def get(self, request, org_id: int):
        targets = importer.targets_for(self.org)
        return Response(
            [
                {"key": k, "label": v, "value_mapped": k in importer.VALUE_MAPPED}
                for k, v in targets.items()
            ]
        )


# Aus diesen Zuständen darf (erneut) geprüft werden
VALIDATE_FROM = (
    ImportJob.Status.UPLOADED,
    ImportJob.Status.VALIDATED,
    ImportJob.Status.FAILED,
)


class _JobAction(OrgScopedMixin, APIView):
    read_permission = MEMBERS_EDIT
    write_permission = MEMBERS_EDIT
    allowed_org_types = CLUB

    def job(self) -> ImportJob:
        job = get_object_or_404(ImportJob, organization=self.org, pk=self.kwargs["pk"])
        if job.purged_at:
            # Datei, Vorschau und Journal sind nach Ablauf der Frist gelöscht
            raise serializers.ValidationError(
                gettext(
                    "Dieser Import ist älter als {IMPORT_KEEP_DAYS} Tage; Datei und "
                    "„Rückgängig“ stehen nicht mehr zur Verfügung."
                ).format(IMPORT_KEEP_DAYS=IMPORT_KEEP_DAYS)
            )
        return job

    def respond(self, job):
        job.refresh_from_db()
        return Response(ImportJobSerializer(job, context={"org": self.org}).data)


class ImportValuesView(_JobAction):
    """Verschiedene Dateiwerte einer Spalte – für die Wertzuordnung."""

    def get(self, request, org_id: int, pk: int):
        target = request.query_params.get("ziel", "member_type")
        return Response(importer.distinct_values(self.job(), target))


class ImportValidateView(_JobAction):
    def post(self, request, org_id: int, pk: int):
        job = self.job()
        if not {"last_name", "first_name", "birth_date"} <= set(job.mapping.values()):
            raise serializers.ValidationError(
                gettext("Name, Vorname und Geburtsdatum müssen zugeordnet sein.")
            )
        # Nur aus erlaubten Vorzuständen und atomar (Audit 31.10. X-01): Ein schon
        # importierter Auftrag bleibt importiert und behält „Rückgängig“
        claimed = ImportJob.objects.filter(
            pk=job.pk, status__in=VALIDATE_FROM, purged_at__isnull=True
        ).update(status=ImportJob.Status.VALIDATING)
        if not claimed:
            raise serializers.ValidationError(
                gettext(
                    "Dieser Import ist schon übernommen oder wird gerade bearbeitet. Für "
                    "eine neue Prüfung bitte die Datei erneut hochladen."
                )
            )
        job.refresh_from_db()
        enqueue(tasks.validate_import, job, failed_status=ImportJob.Status.UPLOADED)
        return self.respond(job)


class ImportRunView(_JobAction):
    def post(self, request, org_id: int, pk: int):
        job = self.job()
        if job.status != ImportJob.Status.VALIDATED:
            raise serializers.ValidationError(gettext("Bitte zuerst prüfen."))
        if not job.counts.get("ok"):
            raise serializers.ValidationError(gettext("Keine fehlerfreien Zeilen zum Importieren."))
        # Atomarer Übergang (Audit 31.10. R-X-02): Ein zweiter, verspäteter Start darf einen
        # fertigen Import nicht wieder auf „wird importiert“ setzen
        claimed = ImportJob.objects.filter(pk=job.pk, status=ImportJob.Status.VALIDATED).update(
            status=ImportJob.Status.IMPORTING
        )
        if not claimed:
            raise serializers.ValidationError(gettext("Der Import läuft schon oder ist fertig."))
        job.refresh_from_db()
        enqueue(tasks.run_import, job, failed_status=ImportJob.Status.VALIDATED)
        return self.respond(job)


class ImportUndoView(_JobAction):
    def post(self, request, org_id: int, pk: int):
        job = self.job()
        try:
            importer.undo(job, request.user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        record(self.org, request.user, "delete", job, {"Import rückgängig": [None, job.file_name]})
        return self.respond(job)


class ImportErrorFileView(_JobAction):
    def get(self, request, org_id: int, pk: int):
        job = self.job()
        if not job.error_file:
            raise serializers.ValidationError(gettext("Keine Fehlerliste vorhanden."))
        return FileResponse(
            job.error_file.open("rb"),
            as_attachment=True,
            filename=f"Fehlerliste {Path(job.file_name).stem}.xlsx",
        )
