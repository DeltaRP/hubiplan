"""Fassungen von Satzung, Beitragsordnung und Gründungsurkunde speichern, prüfen und auflisten."""

from __future__ import annotations

from django.core.exceptions import ValidationError

from .models import MAX_STATUTE_BYTES, Kind, StatutePublication, StatuteVersion


def check_pdf(upload) -> None:
    if upload is None:
        raise ValidationError({"file": "Bitte eine PDF-Datei wählen."})
    if upload.size > MAX_STATUTE_BYTES:
        raise ValidationError({"file": "Die Datei ist größer als 20 MB."})
    head = upload.read(5)
    upload.seek(0)
    if head != b"%PDF-":
        raise ValidationError({"file": "Bitte eine PDF-Datei hochladen."})


def safe_name(name: str, kind: str = Kind.STATUTE) -> str:
    name = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    keep = "".join(c if c.isalnum() or c in ".-_" else "_" for c in name)
    fallback = {Kind.FEE_RULES: "beitragsordnung.pdf", Kind.FOUNDING_DEED: "gruendungsurkunde.pdf"}
    keep = keep[-80:] or fallback.get(kind, "satzung.pdf")
    return keep if keep.lower().endswith(".pdf") else f"{keep}.pdf"


def versions(org, department=None, kind: str = Kind.STATUTE):
    return StatuteVersion.objects.filter(organization=org, department=department, kind=kind)


def publication(
    org, department=None, create: bool = False, kind: str = Kind.STATUTE
) -> StatutePublication | None:
    pub = StatutePublication.objects.filter(
        organization=org, department=department, kind=kind
    ).first()
    if pub is None and create:
        pub = StatutePublication.objects.create(
            organization=org,
            department=department,
            kind=kind,
            public_key=StatutePublication.new_key(),
        )
    return pub


def owner_label(org, department=None) -> str:
    return department.name if department else org.name
