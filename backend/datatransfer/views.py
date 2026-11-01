"""API für den vollständigen Export und den Import aus einer Exportdatei.

- ``/api/orgs/<id>/datatransfer/…``     Dachverband und Verein
- ``/api/depts/<id>/datatransfer/…``    Abteilung (nur Export)
- ``/api/platform/datatransfer/…``      Plattform-Administration
"""

from __future__ import annotations

from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import CLUBS_MANAGE, DATA_EXPORT, DEPT_EXPORT, ORG_EDIT
from audit.log import diff, record, snapshot
from core import jobquota
from core.api_base import OrgScopedMixin
from core.tasks import enqueue
from organizations.models import Department, Organization
from organizations.views import IsPlatformAdmin
from portal.views import DepartmentScopedMixin

from . import services, tasks
from .models import TransferJob

MAX_UPLOAD_BYTES = 500 * 1024 * 1024


def job_data(job: TransferJob) -> dict:
    return {
        "id": job.pk,
        "direction": job.direction,
        "kind": job.kind,
        "status": job.status,
        "status_label": job.get_status_display(),
        "with_files": job.with_files,
        "file_name": job.file_name,
        "size": job.size,
        "has_file": bool(job.file),
        "summary": job.summary,
        "preview": job.preview,
        "decisions": job.decisions,
        "options": {k: v for k, v in (job.options or {}).items() if k != "by_platform"},
        "error": job.error,
        "subject": (
            {"id": job.subject_id, "name": job.subject.display_name} if job.subject_id else None
        ),
        "department": (
            {"id": job.department_id, "name": job.department.display_name}
            if job.department_id
            else None
        ),
        "result_organization": (
            {"id": job.result_organization_id, "name": job.result_organization.display_name}
            if job.result_organization_id
            else None
        ),
        "created_by": job.created_by.email if job.created_by_id else None,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "expires_at": job.expires_at,
    }


def jobs_of(org: Organization, direction: str, **filters):
    return (
        TransferJob.objects.filter(organization=org, direction=direction, **filters)
        .select_related("subject", "department", "result_organization", "created_by")
        .order_by("-created_at")[:30]
    )


class ExportRequest(serializers.Serializer):
    kind = serializers.ChoiceField(choices=TransferJob.Kind.choices, default="organization")
    department = serializers.IntegerField(required=False, allow_null=True)
    organization = serializers.IntegerField(required=False, allow_null=True)
    with_files = serializers.BooleanField(default=False)


class ImportOptions(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    invite = serializers.BooleanField(required=False, default=False)
    board_email = serializers.EmailField(required=False, allow_blank=True)
    # Anschrift, wenn eine Untereinheit eigene Einheit wird (Plattform-Import, Schritt 8b)
    street = serializers.CharField(max_length=200, required=False, allow_blank=True)
    postal_code = serializers.CharField(max_length=10, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    persons = serializers.DictField(child=serializers.CharField(), required=False)


def _capacity(org) -> None:
    jobquota.ensure_capacity(
        TransferJob.objects.filter(organization=org),
        active_statuses=[TransferJob.Status.PENDING, TransferJob.Status.RUNNING],
        max_active=2,
        max_per_hour=10,
        what="vollständige Exporte oder Importe",
    )


def start_export(
    org, user, *, kind, with_files, department=None, subject=None, extra=None
) -> TransferJob:
    _capacity(org)
    job = TransferJob.objects.create(
        organization=org,
        direction=TransferJob.Direction.EXPORT,
        kind=kind,
        department=department,
        subject=subject,
        with_files=with_files,
        options={"by_platform": org.type == Organization.Type.PLATFORM, **(extra or {})},
        created_by=user,
    )
    what = (department or subject or org).name
    # Jeder vollständige Export wird protokolliert
    for log_org in {org, subject or org, department.organization if department else org}:
        record(
            log_org,
            user,
            "create",
            job,
            {
                "Vollständiger Export": [None, what],
                "mit Dateien": [None, "ja" if with_files else "nein"],
                "durch": [None, org.name],
            },
        )
    transaction.on_commit(
        lambda: enqueue(tasks.run_export, job, failed_status=TransferJob.Status.FAILED)
    )
    return job


def start_import(org, user, upload, options: dict) -> TransferJob:
    if upload is None:
        raise serializers.ValidationError({"file": gettext("Bitte eine Exportdatei auswählen.")})
    if upload.size > MAX_UPLOAD_BYTES:
        raise serializers.ValidationError({"file": gettext("Die Datei ist größer als 500 MB.")})
    _capacity(org)
    kind = "department" if org.type == Organization.Type.CLUB else "organization"
    job = TransferJob(
        organization=org,
        direction=TransferJob.Direction.IMPORT,
        kind=kind,
        file_name=upload.name[:200],
        size=upload.size,
        options={k: v for k, v in options.items() if k != "persons"},
        decisions={"persons": options.get("persons") or {}},
        created_by=user,
    )
    job.file.save(upload.name[-100:], upload, save=False)
    job.save()
    transaction.on_commit(
        lambda: enqueue(tasks.check_import, job, failed_status=TransferJob.Status.FAILED)
    )
    return job


def _lock(job: TransferJob) -> None:
    """Auftrag sperren und frisch lesen (zwei gleichzeitige Starts, B-F02)."""
    TransferJob.objects.select_for_update().filter(pk=job.pk).values_list("pk").first()
    job.refresh_from_db()


@transaction.atomic
def update_import(job: TransferJob, options: dict) -> TransferJob:
    _lock(job)
    if job.status in (TransferJob.Status.DONE, TransferJob.Status.RUNNING):
        raise serializers.ValidationError(
            gettext("Dieser Import ist schon abgeschlossen oder läuft.")
        )
    if not job.file:
        raise serializers.ValidationError(gettext("Die Datei ist nicht mehr vorhanden."))
    persons = options.pop("persons", None)
    job.options = {**(job.options or {}), **options}
    if persons is not None:
        job.decisions = {"persons": persons}
    job.status = TransferJob.Status.PENDING
    job.error = ""
    job.save()
    transaction.on_commit(
        lambda: enqueue(tasks.check_import, job, failed_status=TransferJob.Status.FAILED)
    )
    return job


@transaction.atomic
def run_import(job: TransferJob) -> TransferJob:
    _lock(job)
    if job.status != TransferJob.Status.CHECKED:
        raise serializers.ValidationError(gettext("Bitte zuerst die Prüfung abwarten."))
    if (job.preview or {}).get("error_count"):
        raise serializers.ValidationError(
            gettext("Die Datei hat noch Fehler. Bitte zuerst beheben.")
        )
    job.status = TransferJob.Status.RUNNING
    job.save(update_fields=["status"])
    transaction.on_commit(
        lambda: enqueue(tasks.run_import, job, failed_status=TransferJob.Status.CHECKED)
    )
    return job


def download(job: TransferJob):
    if not job.file or job.status != TransferJob.Status.DONE:
        raise NotFound(gettext("Die Datei ist nicht mehr vorhanden."))
    return FileResponse(job.file.open("rb"), as_attachment=True, filename=job.file_name)


# --- Dachverband und Verein ---


class OrgExportView(OrgScopedMixin, APIView):
    read_permission = DATA_EXPORT
    write_permission = DATA_EXPORT
    allowed_org_types = ("federation", "club")

    def get(self, request, org_id: int):
        return Response([job_data(j) for j in jobs_of(self.org, "export")])

    @transaction.atomic
    def post(self, request, org_id: int):
        data = ExportRequest(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        department = None
        if values["kind"] == "department":
            if self.org.type != Organization.Type.CLUB:
                raise NotFound()
            department = get_object_or_404(
                Department, organization=self.org, pk=values.get("department")
            )
        job = start_export(
            self.org,
            request.user,
            kind=values["kind"],
            with_files=values["with_files"],
            department=department,
        )
        return Response(job_data(job), status=status.HTTP_201_CREATED)


class OrgJobMixin(OrgScopedMixin):
    allowed_org_types = ("federation", "club")
    direction = "export"

    def job(self) -> TransferJob:
        return get_object_or_404(
            TransferJob, organization=self.org, direction=self.direction, pk=self.kwargs["pk"]
        )


class OrgExportDetailView(OrgJobMixin, APIView):
    read_permission = DATA_EXPORT

    def get(self, request, org_id: int, pk: int):
        return Response(job_data(self.job()))


class OrgExportDownloadView(OrgJobMixin, APIView):
    read_permission = DATA_EXPORT

    def get(self, request, org_id: int, pk: int):
        return download(self.job())


class _ImportPermission:
    """Dachverband: Vereine anlegen. Verein: Organisationsdaten bearbeiten."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        needed = CLUBS_MANAGE if self.org.type == Organization.Type.FEDERATION else ORG_EDIT
        if needed not in self.org_permissions:
            raise PermissionDenied(gettext("Dafür fehlt dir die Berechtigung."))


class OrgImportView(_ImportPermission, OrgScopedMixin, APIView):
    allowed_org_types = ("federation", "club")
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, org_id: int):
        return Response([job_data(j) for j in jobs_of(self.org, "import")])

    @transaction.atomic
    def post(self, request, org_id: int):
        options = ImportOptions(data=request.data)
        options.is_valid(raise_exception=True)
        job = start_import(
            self.org, request.user, request.FILES.get("file"), options.validated_data
        )
        return Response(job_data(job), status=status.HTTP_201_CREATED)


class OrgImportDetailView(_ImportPermission, OrgJobMixin, APIView):
    direction = "import"

    def get(self, request, org_id: int, pk: int):
        return Response(job_data(self.job()))

    @transaction.atomic
    def patch(self, request, org_id: int, pk: int):
        options = ImportOptions(data=request.data, partial=True)
        options.is_valid(raise_exception=True)
        return Response(job_data(update_import(self.job(), dict(options.validated_data))))


class OrgImportRunView(_ImportPermission, OrgJobMixin, APIView):
    direction = "import"

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        return Response(job_data(run_import(self.job())))


class ClubCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    founding_year = serializers.IntegerField(min_value=800, max_value=2100)
    street = serializers.CharField(max_length=200)
    postal_code = serializers.CharField(max_length=10)
    city = serializers.CharField(max_length=100)
    country = serializers.CharField(max_length=100, required=False, default="Deutschland")
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    contact_phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    website = serializers.URLField(required=False, allow_blank=True)
    board_email = serializers.EmailField(required=False, allow_blank=True)


class FederationClubCreateView(OrgScopedMixin, APIView):
    """Dachverband legt einen Verein von Hand an."""

    allowed_org_types = ("federation",)
    read_permission = CLUBS_MANAGE
    write_permission = CLUBS_MANAGE

    @transaction.atomic
    def post(self, request, org_id: int):
        data = ClubCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        board_email = values.pop("board_email", "")
        from django.core.exceptions import ValidationError as DjangoValidationError

        try:
            club = services.create_club(self.org, values)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        record(self.org, request.user, "create", club, diff({}, snapshot(club)))
        record(club, request.user, "create", club, diff({}, snapshot(club)))
        invitations: list = []
        if board_email:
            services.add_board(club, board_email, invitations)

        def send():
            from accounts.invitations import send_invitation

            for user, org, role in invitations:
                send_invitation(user, org, role)

        transaction.on_commit(send)
        return Response(
            {"id": club.pk, "name": club.name, "invited": len(invitations)},
            status=status.HTTP_201_CREATED,
        )


# --- Abteilung ---


class DeptExportView(DepartmentScopedMixin, APIView):
    read_permission = DEPT_EXPORT
    write_permission = DEPT_EXPORT

    def get(self, request, dept_id: int):
        return Response(
            [
                job_data(j)
                for j in jobs_of(self.org, "export", department=self.dept, created_by=request.user)
            ]
        )

    @transaction.atomic
    def post(self, request, dept_id: int):
        data = ExportRequest(data=request.data)
        data.is_valid(raise_exception=True)
        job = start_export(
            self.org,
            request.user,
            kind="department",
            with_files=data.validated_data["with_files"],
            department=self.dept,
        )
        return Response(job_data(job), status=status.HTTP_201_CREATED)


class DeptExportDetailView(DepartmentScopedMixin, APIView):
    read_permission = DEPT_EXPORT

    def job(self):
        return get_object_or_404(
            TransferJob,
            organization=self.org,
            department=self.dept,
            direction="export",
            created_by=self.request.user,
            pk=self.kwargs["pk"],
        )

    def get(self, request, dept_id: int, pk: int):
        return Response(job_data(self.job()))


class DeptExportDownloadView(DeptExportDetailView):
    def get(self, request, dept_id: int, pk: int):
        return download(self.job())


# --- Plattform ---


class PlatformExportView(APIView):
    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        return Response([job_data(j) for j in jobs_of(Organization.platform(), "export")])

    @transaction.atomic
    def post(self, request):
        data = ExportRequest(data=request.data)
        data.is_valid(raise_exception=True)
        subject = get_object_or_404(
            Organization.objects.exclude(type=Organization.Type.PLATFORM),
            pk=data.validated_data.get("organization"),
        )
        job = start_export(
            Organization.platform(),
            request.user,
            kind="organization",
            with_files=data.validated_data["with_files"],
            subject=subject,
        )
        return Response(job_data(job), status=status.HTTP_201_CREATED)


class PlatformJobMixin:
    permission_classes = [IsPlatformAdmin]
    direction = "export"

    def job(self) -> TransferJob:
        return get_object_or_404(
            TransferJob,
            organization=Organization.platform(),
            direction=self.direction,
            pk=self.kwargs["pk"],
        )


class PlatformExportDetailView(PlatformJobMixin, APIView):
    def get(self, request, pk: int):
        return Response(job_data(self.job()))


class PlatformExportDownloadView(PlatformJobMixin, APIView):
    def get(self, request, pk: int):
        return download(self.job())


class PlatformImportView(APIView):
    permission_classes = [IsPlatformAdmin]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        return Response([job_data(j) for j in jobs_of(Organization.platform(), "import")])

    @transaction.atomic
    def post(self, request):
        options = ImportOptions(data=request.data)
        options.is_valid(raise_exception=True)
        job = start_import(
            Organization.platform(), request.user, request.FILES.get("file"), options.validated_data
        )
        return Response(job_data(job), status=status.HTTP_201_CREATED)


class PlatformImportDetailView(PlatformJobMixin, APIView):
    direction = "import"

    def get(self, request, pk: int):
        return Response(job_data(self.job()))

    @transaction.atomic
    def patch(self, request, pk: int):
        options = ImportOptions(data=request.data, partial=True)
        options.is_valid(raise_exception=True)
        return Response(job_data(update_import(self.job(), dict(options.validated_data))))


class PlatformImportRunView(PlatformJobMixin, APIView):
    direction = "import"

    @transaction.atomic
    def post(self, request, pk: int):
        return Response(job_data(run_import(self.job())))
