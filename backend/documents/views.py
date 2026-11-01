"""API der Dokumentenablage: Vorstand, Abteilungsbereich, Mitgliederbereich, öffentlich."""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import FileResponse, Http404
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import DEPT_DOCS_MANAGE, DOCS_MANAGE, DOCS_VIEW
from audit.log import record
from core.api_base import OrgScopedMixin
from core.tenancy import rls_bypass, scope_of, set_rls
from members.models import DepartmentMembership, today
from organizations.models import Department, Organization
from portal.views import DepartmentScopedMixin, _portal_access

from . import services
from .models import Document, DocumentVersion, Folder

V = Folder.Visibility


def _user_name(user) -> str:
    return (user.get_full_name() or user.email) if user else ""


def version_data(v: DocumentVersion, base: str) -> dict:
    return {
        "id": v.pk,
        "name": v.name,
        "size": v.size,
        "content_type": v.content_type,
        "uploaded_at": v.uploaded_at,
        "uploaded_by": _user_name(v.uploaded_by),
        "url": f"{base}versions/{v.pk}/",
        "inline": v.content_type in services.INLINE_TYPES,
    }


def document_data(d: Document, base: str, with_versions: bool = True) -> dict:
    versions = list(d.versions.all())
    data = {
        "id": d.pk,
        "folder": d.folder_id,
        "title": d.title,
        "date": d.date,
        "note": d.note,
        "created_at": d.created_at,
        "created_by": _user_name(d.created_by),
        "current": version_data(versions[0], base) if versions else None,
        "version_count": len(versions),
    }
    if with_versions:
        data["versions"] = [version_data(v, base) for v in versions]
    if d.deleted_at:
        data["deleted_at"] = d.deleted_at
        data["deleted_by"] = _user_name(d.deleted_by)
    return data


def public_url(request, folder: Folder) -> str | None:
    if folder.visibility != V.PUBLIC:
        return None
    return request.build_absolute_uri(reverse("public-documents", args=[folder.public_key]))


def folder_data(request, folder: Folder, docs: list[Document], base: str, manage: bool) -> dict:
    data = {
        "id": folder.pk,
        "name": folder.name,
        "visibility": folder.visibility,
        "visibility_label": folder.get_visibility_display(),
        "shared_up": folder.shared_up,
        "documents": [document_data(d, base) for d in docs],
    }
    if manage:
        data["public_url"] = public_url(request, folder)
    return data


def file_response(request, version: DocumentVersion, cache: str = "private") -> FileResponse:
    inline = version.content_type in services.INLINE_TYPES
    response = FileResponse(
        version.file.open("rb"),
        content_type=version.content_type,
        as_attachment=not inline or request.query_params.get("download") == "1",
        filename=version.name,
    )
    response["Cache-Control"] = f"{cache}, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    return response


class FolderSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    visibility = serializers.ChoiceField(choices=V.choices, required=False)
    shared_up = serializers.BooleanField(required=False)


class DocumentSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    date = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)
    folder = serializers.IntegerField(required=False)


# --- Zugänge ---


class _DocsMixin:
    """Gemeinsame Hilfen; ``viewer`` und ``base_url`` setzen die Zugänge."""

    viewer: services.Viewer
    base_url: str
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def audit(self, action: str, instance, changes: dict | None = None) -> None:
        record(self.viewer.org, self.request.user, action, instance, changes)

    def require_manage(self) -> None:
        if not self.viewer.can_manage:
            raise PermissionDenied(gettext("Dafür fehlt dir die Berechtigung."))

    @property
    def department(self) -> Department | None:
        """Eigene Ablage: die der Abteilung bzw. der Organisation selbst (leer).

        Der Vorstand verwaltet nie die Ablagen seiner Abteilungen; er liest nur, was
        eine Abteilung nach oben freigibt."""
        return self.viewer.department if self.viewer.kind == "department" else None

    def own_folder(self, pk: int) -> Folder:
        """Ordner, den diese Sicht verwalten darf."""
        qs = Folder.objects.filter(organization=self.viewer.org, pk=pk, department=self.department)
        folder = qs.select_related("department").first()
        if folder is None:
            raise NotFound()
        return folder

    def own_document(self, pk: int, trash: bool = False) -> Document:
        qs = Document.objects.filter(
            organization=self.viewer.org,
            pk=pk,
            deleted_at__isnull=not trash,
            department=self.department,
        )
        doc = qs.select_related("folder").prefetch_related("versions__uploaded_by").first()
        if doc is None:
            raise NotFound()
        return doc

    def label(self, folder: Folder) -> str:
        return f"{folder.name} ({folder.department.name})" if folder.department else folder.name


class OrgDocsMixin(_DocsMixin, OrgScopedMixin):
    read_permission = DOCS_VIEW
    write_permission = DOCS_MANAGE
    allowed_org_types = (Organization.Type.FEDERATION, Organization.Type.CLUB)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.viewer = services.org_viewer(self.org, self.org_permissions)
        self.base_url = f"/api/orgs/{self.org.pk}/documents/"


class DeptDocsMixin(_DocsMixin, DepartmentScopedMixin):
    read_permission = None
    write_permission = DEPT_DOCS_MANAGE

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.viewer = services.department_viewer(self.ctx)
        self.base_url = f"/api/depts/{self.dept.pk}/documents/"


class PortalDocsMixin(_DocsMixin):
    """Mitgliederbereich: nur lesen, im Kontext des Vereins."""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        access = _portal_access(request.user, kwargs["access_id"])
        club = access.organization
        set_rls(club.pk, request.user.pk, scope_id=scope_of(club.pk))
        on = today()
        depts = list(
            DepartmentMembership.objects.filter(
                membership_id=access.membership_id, valid_from__lte=on
            )
            .exclude(valid_until__lt=on)
            .values_list("department_id", flat=True)
        )
        self.viewer = services.member_viewer(club, depts)
        self.base_url = f"/api/portal/{access.pk}/documents/"


# --- Ansichten (für alle Zugänge gleich) ---


def _readonly(request, folders: list[Folder], base: str, origin) -> list[dict]:
    """Fremde Ordner (vom Dachverband bzw. von unten freigegeben), nur lesen."""
    docs = services.documents_in([f.pk for f in folders])
    return [
        {
            **folder_data(request, f, [d for d in docs if d.folder_id == f.pk], base, False),
            "from": origin(f),
        }
        for f in folders
    ]


class _Overview(APIView):
    """GET: eigene Ordner mit Dokumenten, dazu Freigaben von oben und von unten."""

    def get(self, request, **kwargs):
        viewer = self.viewer
        manage = viewer.can_manage
        folders = list(viewer.folders().select_related("department"))
        docs = services.documents_in([f.pk for f in folders])
        by_folder: dict[int, list[Document]] = {}
        for d in docs:
            by_folder.setdefault(d.folder_id, []).append(d)
        data = {
            "folders": [
                {
                    **folder_data(request, f, by_folder.get(f.pk, []), self.base_url, manage),
                    **(
                        {"department": f.department.display_name if f.department else None}
                        if viewer.kind == "member"
                        else {}
                    ),
                }
                for f in folders
            ],
            "can_manage": manage,
            "org_kind": "department" if viewer.kind == "department" else viewer.org.type,
        }
        if viewer.kind != "member":
            data["visibilities"] = [
                {"value": v, "label": V(v).label}
                for v in services.visibilities_for(viewer.org, self.department)
            ]
            data["share_up_label"] = viewer.share_up_label()
            data["used_bytes"] = services.used_bytes(viewer.org, self.department)
            data["total_bytes"] = services.total_bytes(viewer.org)
            data["budget_bytes"] = services.budget_bytes(viewer.org)
            data["trash_count"] = (
                services.documents_in([f.pk for f in folders], trash=True).count() if manage else 0
            )
        if viewer.kind == "org":
            data["shared"] = _readonly(
                request,
                list(viewer.shared_folders().select_related("organization")),
                self.base_url,
                lambda f: f.organization.name,
            )
            data["from_below"] = _readonly(
                request,
                list(viewer.up_folders().select_related("organization", "department")),
                self.base_url,
                lambda f: f.department.display_name if f.department else f.organization.name,
            )
        return Response(data)


class _Folders(APIView):
    """POST: Ordner anlegen."""

    @transaction.atomic
    def post(self, request, **kwargs):
        self.require_manage()
        department = self.department
        data = FolderSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        visibility = data.validated_data.get("visibility", V.BOARD)
        if visibility not in services.visibilities_for(self.viewer.org, department):
            raise serializers.ValidationError(
                {"visibility": gettext("Diese Sichtbarkeit gibt es hier nicht.")}
            )
        folder = Folder.objects.create(
            organization=self.viewer.org,
            department=department,
            name=data.validated_data["name"].strip(),
            visibility=visibility,
            shared_up=bool(data.validated_data.get("shared_up"))
            and self.viewer.share_up_label() is not None,
            public_key=Folder.new_key(),
            created_by=request.user,
        )
        self.audit("create", folder, {"Ordner": [None, self.label(folder)]})
        return Response(folder_data(request, folder, [], self.base_url, True), status=201)


class _FolderDetail(APIView):
    """PATCH: Ordner umbenennen bzw. Sichtbarkeit ändern · DELETE: leeren Ordner löschen."""

    @transaction.atomic
    def patch(self, request, pk: int, **kwargs):
        self.require_manage()
        folder = self.own_folder(pk)
        data = FolderSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        changes = {}
        name = data.validated_data.get("name")
        if name and name.strip() != folder.name:
            changes["Ordner"] = [folder.name, name.strip()]
            folder.name = name.strip()
        visibility = data.validated_data.get("visibility")
        if visibility and visibility != folder.visibility:
            if visibility not in services.visibilities_for(self.viewer.org, folder.department):
                raise serializers.ValidationError(
                    {"visibility": gettext("Diese Sichtbarkeit gibt es hier nicht.")}
                )
            changes[f"Sichtbar für ({folder.name})"] = [
                folder.get_visibility_display(),
                V(visibility).label,
            ]
            folder.visibility = visibility
        shared_up = data.validated_data.get("shared_up")
        if shared_up is not None and shared_up != folder.shared_up:
            if shared_up and self.viewer.share_up_label() is None:
                raise serializers.ValidationError(
                    {"shared_up": gettext("Hier gibt es keine höhere Ebene zum Freigeben.")}
                )
            changes[f"Nach oben freigegeben ({folder.name})"] = [folder.shared_up, shared_up]
            folder.shared_up = shared_up
        if changes:
            folder.save(update_fields=["name", "visibility", "shared_up"])
            self.audit("update", folder, changes)
        docs = services.documents_in([folder.pk])
        return Response(folder_data(request, folder, list(docs), self.base_url, True))

    @transaction.atomic
    def delete(self, request, pk: int, **kwargs):
        self.require_manage()
        folder = self.own_folder(pk)
        if Document.objects.filter(folder=folder, deleted_at__isnull=True).exists():
            raise serializers.ValidationError(
                {
                    "detail": gettext(
                        "Der Ordner ist nicht leer. Bitte zuerst die Dokumente verschieben."
                    )
                }
            )
        self.audit("delete", folder, {"Ordner": [self.label(folder), None]})
        folder.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _save_version(viewer, document: Document, upload, user) -> DocumentVersion:
    try:
        ctype = services.check_upload(upload)
        services.check_budget(viewer.org, upload.size)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(exc.message_dict) from exc
    version = DocumentVersion(
        organization=viewer.org,
        department=document.department,
        document=document,
        name=services.clean_name(upload.name),
        size=upload.size,
        content_type=ctype,
        uploaded_by=user,
        uploaded_at=timezone.now(),
    )
    version.file.save(services.storage_name(upload.name), upload, save=False)
    version.save()
    return version


class _FolderDocuments(APIView):
    """POST: Dokument mit erster Fassung in einen Ordner hochladen."""

    @transaction.atomic
    def post(self, request, pk: int, **kwargs):
        self.require_manage()
        folder = self.own_folder(pk)
        data = DocumentSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        upload = request.FILES.get("file")
        try:
            services.check_upload(upload)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        doc = Document.objects.create(
            organization=self.viewer.org,
            department=folder.department,
            folder=folder,
            title=data.validated_data["title"].strip(),
            date=data.validated_data.get("date"),
            note=data.validated_data.get("note", ""),
            created_by=request.user,
        )
        _save_version(self.viewer, doc, upload, request.user)
        self.audit("create", doc, {"Dokument": [None, f"{doc.title} ({self.label(folder)})"]})
        doc = self.own_document(doc.pk)
        return Response(document_data(doc, self.base_url), status=201)


class _DocumentDetail(APIView):
    """PATCH: Angaben ändern oder verschieben · DELETE: in den Papierkorb
    (``?final=1``: aus dem Papierkorb endgültig löschen)."""

    @transaction.atomic
    def patch(self, request, pk: int, **kwargs):
        self.require_manage()
        doc = self.own_document(pk)
        data = DocumentSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        changes = {}
        if "folder" in values and values["folder"] != doc.folder_id:
            target = self.own_folder(values["folder"])
            if target.department_id != doc.department_id:
                raise serializers.ValidationError(
                    {
                        "folder": gettext(
                            "Dokumente lassen sich nur innerhalb einer Ablage verschieben."
                        )
                    }
                )
            changes["Ordner"] = [doc.folder.name, target.name]
            doc.folder = target
        for key, label in (("title", "Titel"), ("date", "Datum"), ("note", "Bemerkung")):
            if key in values:
                new = values[key].strip() if isinstance(values[key], str) else values[key]
                if new != getattr(doc, key):
                    changes[label] = [str(getattr(doc, key) or ""), str(new or "")]
                    setattr(doc, key, new)
        if changes:
            doc.save(update_fields=["folder", "title", "date", "note"])
            self.audit("update", doc, changes)
        return Response(document_data(self.own_document(pk), self.base_url))

    @transaction.atomic
    def delete(self, request, pk: int, **kwargs):
        self.require_manage()
        if request.query_params.get("final") == "1":
            doc = self.own_document(pk, trash=True)
            self.audit("delete", doc, {"Dokument endgültig gelöscht": [doc.title, None]})
            doc.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        doc = self.own_document(pk)
        doc.deleted_at = timezone.now()
        doc.deleted_by = request.user
        doc.save(update_fields=["deleted_at", "deleted_by"])
        self.audit("delete", doc, {"Dokument (Papierkorb)": [doc.title, None]})
        return Response(status=status.HTTP_204_NO_CONTENT)


class _DocumentRestore(APIView):
    """POST: Dokument aus dem Papierkorb zurückholen."""

    @transaction.atomic
    def post(self, request, pk: int, **kwargs):
        self.require_manage()
        doc = self.own_document(pk, trash=True)
        doc.deleted_at = None
        doc.deleted_by = None
        doc.save(update_fields=["deleted_at", "deleted_by"])
        self.audit("update", doc, {"Dokument wiederhergestellt": [None, doc.title]})
        return Response(document_data(self.own_document(pk), self.base_url))


class _Trash(APIView):
    """GET: Papierkorb einer Ablage (``department``)."""

    def get(self, request, **kwargs):
        self.require_manage()
        folders = {f.pk: f for f in self.viewer.folders()}
        docs = services.documents_in(list(folders), trash=True).order_by("-deleted_at")
        return Response(
            [
                {**document_data(d, self.base_url, False), "folder_name": folders[d.folder_id].name}
                for d in docs
            ]
        )


class _DocumentVersions(APIView):
    """POST: neue Fassung eines Dokuments hochladen."""

    @transaction.atomic
    def post(self, request, pk: int, **kwargs):
        self.require_manage()
        doc = self.own_document(pk)
        version = _save_version(self.viewer, doc, request.FILES.get("file"), request.user)
        self.audit("update", doc, {"Neue Fassung": [None, f"{doc.title}: {version.name}"]})
        return Response(document_data(self.own_document(pk), self.base_url), status=201)


class _Version(APIView):
    """GET: Datei einer Fassung · DELETE: Fassung löschen (nicht die einzige)."""

    def get(self, request, pk: int, **kwargs):
        version = self.viewer.visible_versions().filter(pk=pk).select_related("document").first()
        if version is None:
            raise NotFound()
        record(
            self.viewer.org,
            request.user,
            "view",
            version.document,
            {"Datei abgerufen": [None, version.name]},
        )
        return file_response(request, version)

    @transaction.atomic
    def delete(self, request, pk: int, **kwargs):
        self.require_manage()
        qs = DocumentVersion.objects.filter(
            organization=self.viewer.org, pk=pk, department=self.department
        )
        version = qs.select_related("document").first()
        if version is None:
            raise NotFound()
        # Dokument sperren, dann frisch zählen: Zwei gleichzeitige Löschungen verschiedener
        # Fassungen dürfen nicht beide die letzte übrig lassen wollen (B-F03).
        Document.objects.select_for_update().filter(pk=version.document_id).values_list(
            "pk"
        ).first()
        version.document.refresh_from_db()
        if version.document.deleted_at or not qs.exists():
            raise NotFound()
        if version.document.versions.count() <= 1:
            raise serializers.ValidationError(
                {
                    "detail": gettext(
                        "Die einzige Fassung lässt sich nicht löschen. Lösche das Dokument."
                    )
                }
            )
        self.audit("update", version.document, {"Fassung gelöscht": [version.name, None]})
        version.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# Vorstand einer Organisation
class OrgOverviewView(OrgDocsMixin, _Overview):
    pass


class OrgFoldersView(OrgDocsMixin, _Folders):
    pass


class OrgFolderDetailView(OrgDocsMixin, _FolderDetail):
    pass


class OrgFolderDocumentsView(OrgDocsMixin, _FolderDocuments):
    pass


class OrgDocumentDetailView(OrgDocsMixin, _DocumentDetail):
    pass


class OrgDocumentRestoreView(OrgDocsMixin, _DocumentRestore):
    pass


class OrgTrashView(OrgDocsMixin, _Trash):
    read_permission = DOCS_MANAGE


class OrgDocumentVersionsView(OrgDocsMixin, _DocumentVersions):
    pass


class OrgVersionView(OrgDocsMixin, _Version):
    pass


# Abteilungsbereich
class DeptOverviewView(DeptDocsMixin, _Overview):
    pass


class DeptFoldersView(DeptDocsMixin, _Folders):
    pass


class DeptFolderDetailView(DeptDocsMixin, _FolderDetail):
    pass


class DeptFolderDocumentsView(DeptDocsMixin, _FolderDocuments):
    pass


class DeptDocumentDetailView(DeptDocsMixin, _DocumentDetail):
    pass


class DeptDocumentRestoreView(DeptDocsMixin, _DocumentRestore):
    pass


class DeptTrashView(DeptDocsMixin, _Trash):
    read_permission = DEPT_DOCS_MANAGE


class DeptDocumentVersionsView(DeptDocsMixin, _DocumentVersions):
    pass


class DeptVersionView(DeptDocsMixin, _Version):
    pass


# Mitgliederbereich (nur lesen)
class PortalOverviewView(PortalDocsMixin, _Overview):
    pass


class PortalVersionView(PortalDocsMixin, _Version):
    http_method_names = ["get", "head", "options"]


# --- öffentlicher Abruf ohne Anmeldung ---


class PublicFolderView(APIView):
    """Dokumente eines öffentlichen Ordners (aktuelle Fassungen), z. B. für Webseiten."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, key: str):
        folder, docs = services.public_folder(key)
        if folder is None:
            raise Http404
        owner = folder.department or folder.organization
        data = {
            "name": folder.name,
            "owner": owner.name,
            "documents": [
                {
                    "title": d.title,
                    "date": d.date,
                    "note": d.note,
                    "name": d.versions.all()[0].name,
                    "size": d.versions.all()[0].size,
                    "url": request.build_absolute_uri(reverse("public-document", args=[key, d.pk])),
                }
                for d in docs
            ],
        }
        response = Response(data)
        response["Access-Control-Allow-Origin"] = "*"
        response["Cache-Control"] = "public, max-age=300"
        return response


class PublicDocumentView(APIView):
    """Aktuelle Fassung eines Dokuments aus einem öffentlichen Ordner."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, key: str, pk: int):
        folder, docs = services.public_folder(key)
        doc = next((d for d in docs if d.pk == pk), None)
        if folder is None or doc is None:
            raise Http404
        with rls_bypass():
            response = file_response(request, doc.versions.all()[0], cache="public")
        response["Access-Control-Allow-Origin"] = "*"
        return response
