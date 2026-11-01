"""Wer sieht welche Dokumente, Dateien prüfen und aufräumen.

Jede Sicht (Vorstand einer Organisation, Abteilungsrolle, Mitgliederbereich,
öffentlicher Link) beschreibt sich als ``Viewer``. Die Datenbank (RLS) lässt
zusätzlich nur Zeilen der eigenen Organisation und die für Vereine freigegebenen
Ordner des eigenen Dachverbands heraus.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.utils import timezone

from changes.models import RETENTION_DAYS
from core.tenancy import rls_bypass
from organizations.models import Department, Organization
from organizations.terms import fill
from organizations.tree import with_ancestors

from .models import MAX_DOCUMENT_BYTES, Document, DocumentVersion, Folder

V = Folder.Visibility

# Erlaubte Dateien: Endung → (Dateiart, Erkennung am Dateianfang oder None)
ALLOWED_TYPES: dict[str, tuple[str, tuple[bytes, ...] | None]] = {
    "pdf": ("application/pdf", (b"%PDF-",)),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        (b"PK\x03\x04",),
    ),
    "dotx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
        (b"PK\x03\x04",),
    ),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", (b"PK\x03\x04",)),
    "pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        (b"PK\x03\x04",),
    ),
    "odt": ("application/vnd.oasis.opendocument.text", (b"PK\x03\x04",)),
    "ods": ("application/vnd.oasis.opendocument.spreadsheet", (b"PK\x03\x04",)),
    "doc": ("application/msword", (b"\xd0\xcf\x11\xe0",)),
    "xls": ("application/vnd.ms-excel", (b"\xd0\xcf\x11\xe0",)),
    "txt": ("text/plain", None),
    "csv": ("text/csv", None),
}
# Im Browser anzeigen statt herunterladen (alles andere kommt als Download)
INLINE_TYPES = {"application/pdf", "image/jpeg", "image/png"}
ALLOWED_HINT = "PDF, Word, Excel, PowerPoint, OpenDocument, JPEG, PNG, Text oder CSV"


def check_upload(upload) -> str:
    """Prüft Größe und Dateiart, gibt die Dateiart zurück."""
    if upload is None:
        raise ValidationError({"file": "Bitte eine Datei wählen."})
    if upload.size > MAX_DOCUMENT_BYTES:
        raise ValidationError({"file": "Die Datei ist größer als 20 MB."})
    ext = clean_name(upload.name).rsplit(".", 1)[-1].lower() if "." in upload.name else ""
    if ext not in ALLOWED_TYPES:
        raise ValidationError({"file": f"Erlaubt sind {ALLOWED_HINT}."})
    ctype, magic = ALLOWED_TYPES[ext]
    head = upload.read(8)
    upload.seek(0)
    if magic is None:
        if b"\x00" in upload.read(4096):
            upload.seek(0)
            raise ValidationError({"file": "Das ist keine Textdatei."})
        upload.seek(0)
    elif not head.startswith(magic):
        raise ValidationError({"file": "Inhalt und Dateiendung passen nicht zusammen."})
    return ctype


def clean_name(name: str) -> str:
    return (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:200] or "dokument"


def storage_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in ".-_" else "_" for c in clean_name(name))
    return keep[-80:] or "dokument"


def visibilities_for(org: Organization, department: Department | None) -> list[str]:
    """Welche Sichtbarkeiten es für eine Ablage gibt."""
    if org.type == Organization.Type.FEDERATION:
        return [V.BOARD, V.CLUBS, V.PUBLIC]
    return [V.BOARD, V.MEMBERS, V.PUBLIC]


def federation_of(org: Organization) -> Organization | None:
    parent = org.parent if org.type == Organization.Type.CLUB else None
    if parent is not None and parent.type == Organization.Type.FEDERATION:
        return parent
    return None


@dataclass
class Viewer:
    """Sicht auf eine Ablage. ``org`` = Organisation, in deren RLS-Kontext gelesen wird."""

    org: Organization
    kind: str = "org"  # org | department | member
    department: Department | None = None
    can_manage: bool = False
    # Mitgliederbereich: Abteilungen des Mitglieds
    member_departments: list[int] = field(default_factory=list)

    def folders(self):
        """Eigene Ordner dieser Sicht (Vorstand: nur die der Organisation selbst)."""
        qs = Folder.objects.filter(organization=self.org)
        if self.kind == "member":
            return qs.filter(
                Q(department__isnull=True) | Q(department_id__in=self.member_departments),
                visibility__in=[V.MEMBERS, V.PUBLIC],
            )
        if self.kind == "department":
            return qs.filter(department=self.department)
        return qs.filter(department__isnull=True)

    def shared_folders(self):
        """Für Vereine freigegebene Ordner des Dachverbands (nur lesen)."""
        fed = federation_of(self.org)
        if fed is None or self.kind == "member":
            return Folder.objects.none()
        return Folder.objects.filter(
            organization=fed, department__isnull=True, visibility__in=[V.CLUBS, V.PUBLIC]
        )

    def up_folders(self):
        """Von unten freigegebene Ordner (nur lesen): Abteilungen für den Verein,
        Vereine für den Dachverband. Ohne Freigabe sieht die höhere Ebene nichts."""
        if self.kind != "org":
            return Folder.objects.none()
        if self.org.type == Organization.Type.FEDERATION:
            return Folder.objects.filter(
                organization__parent=self.org,
                organization__type=Organization.Type.CLUB,
                organization__is_active=True,
                department__isnull=True,
                shared_up=True,
            )
        return Folder.objects.filter(
            organization=self.org, department__isnull=False, shared_up=True
        )

    def visible_versions(self):
        folder_ids = list(self.all_folders().values_list("pk", flat=True))
        return DocumentVersion.objects.filter(
            document__folder_id__in=folder_ids, document__deleted_at__isnull=True
        )

    def all_folders(self):
        return self.folders() | self.shared_folders() | self.up_folders()

    def share_up_label(self) -> str | None:
        """Beschriftung der Freigabe nach oben, falls es eine höhere Ebene gibt."""
        if self.kind == "department":
            return fill("Für den Vorstand {e_gen} freigeben (nur lesen)", self.org)
        if self.kind == "org" and federation_of(self.org) is not None:
            return fill("Für {dv_akk} freigeben (nur lesen)", self.org)
        return None


def org_viewer(org: Organization, perms: set[str]) -> Viewer:
    from access.catalog import DOCS_MANAGE

    return Viewer(org=org, kind="org", can_manage=DOCS_MANAGE in perms)


def department_viewer(ctx) -> Viewer:
    from access.catalog import DEPT_DOCS_MANAGE

    return Viewer(
        org=ctx.club,
        kind="department",
        department=ctx.department,
        can_manage=DEPT_DOCS_MANAGE in ctx.permissions,
    )


def member_viewer(club: Organization, departments: list[int]) -> Viewer:
    # Wer einer Untereinheit angehört, sieht auch die Ordner der Einheiten darüber
    ids = sorted(with_ancestors(club.pk, departments) or departments)
    return Viewer(org=club, kind="member", member_departments=ids)


def used_bytes(org: Organization, department: Department | None = None) -> int:
    """Belegter Platz einer Ablage (alle Fassungen, auch im Papierkorb)."""
    qs = DocumentVersion.objects.filter(organization=org, department=department)
    return qs.aggregate(s=Sum("size"))["s"] or 0


def budget_bytes(org: Organization) -> int:
    """Speicherbudget der Ablage eines Vereins samt Untereinheiten (GA-S04)."""
    from django.conf import settings

    gb = org.document_budget_gb or settings.DOCUMENT_BUDGET_GB
    return gb * 1024**3


def total_bytes(org: Organization) -> int:
    """Belegter Platz des ganzen Vereins (alle Ablagen, Fassungen und Papierkorb)."""
    return DocumentVersion.objects.filter(organization=org).aggregate(s=Sum("size"))["s"] or 0


def check_budget(org: Organization, size: int) -> None:
    """Passt eine weitere Datei noch ins Budget? Sperrt den Verein bis zum Commit,
    damit gleichzeitige Uploads das Budget nicht gemeinsam überschreiten."""
    Organization.objects.select_for_update().filter(pk=org.pk).values_list("pk").first()
    limit = budget_bytes(org)
    if total_bytes(org) + (size or 0) > limit:
        raise ValidationError(
            {
                "file": f"Der Speicherplatz der Ablage ({limit // 1024**3} GB) ist voll. Bitte "
                "alte Fassungen oder den Papierkorb leeren oder die Plattform um mehr Platz "
                "bitten."
            }
        )


def documents_in(folder_ids, *, trash: bool = False):
    qs = Document.objects.filter(folder_id__in=folder_ids, deleted_at__isnull=not trash)
    return qs.prefetch_related("versions__uploaded_by").select_related("created_by", "deleted_by")


def public_folder(key: str) -> tuple[Folder, list[Document]]:
    with rls_bypass():
        folder = (
            Folder.objects.select_related("organization", "department")
            .filter(public_key=key, visibility=V.PUBLIC, organization__is_active=True)
            .first()
        )
        # Deaktivierte Untereinheit: Link gesperrt wie bei der Organisation (Audit B-V05)
        if folder is None or (folder.department is not None and not folder.department.is_active):
            return None, []
        docs = [d for d in documents_in([folder.pk]) if d.versions.all()]
    return folder, docs


# --- Aufräumen ---


def files_in_changes(since: datetime.datetime) -> set[str]:
    """Dateien aus Änderungspaketen, die noch nicht abgelaufen sind."""
    from changes.models import ChangeRecord

    names = set()
    rows = ChangeRecord.objects.filter(
        model="documents.documentversion", created_at__gte=since
    ).values_list("before", "after")
    for before, after in rows:
        for values in (before, after):
            if isinstance(values, dict) and values.get("file"):
                names.add(values["file"])
    return names


def purge(now: datetime.datetime | None = None) -> int:
    """Papierkorb nach 30 Tagen leeren und nicht mehr verwendete Dateien entfernen.

    Dateien bleiben so lange liegen wie Änderungspakete (Rückgängig kann eine
    gelöschte Fassung samt Datei zurückholen).
    """
    now = now or timezone.now()
    cutoff = now - datetime.timedelta(days=RETENTION_DAYS)
    removed = 0
    with rls_bypass():
        removed += Document.objects.filter(deleted_at__lt=cutoff).delete()[0]
        storage = DocumentVersion._meta.get_field("file").storage
        used = set(DocumentVersion.objects.values_list("file", flat=True))
        # Dateien, die ein noch nicht abgelaufenes Änderungspaket kennt: Rückgängig holt
        # sie zurück. Das Alter der Datei allein sagt darüber nichts (alte Datei, eben
        # gelöscht).
        used |= files_in_changes(since=cutoff)
        try:
            orgs, _ = storage.listdir("documents")
        except (FileNotFoundError, NotADirectoryError):
            return removed
        for org_dir in orgs:
            try:
                _, files = storage.listdir(f"documents/{org_dir}")
            except (FileNotFoundError, NotADirectoryError):
                continue
            for name in files:
                path = f"documents/{org_dir}/{name}"
                if path in used:
                    continue
                try:
                    modified = storage.get_modified_time(path)
                except (FileNotFoundError, NotImplementedError):
                    continue
                if modified < cutoff:
                    storage.delete(path)
                    removed += 1
    return removed
