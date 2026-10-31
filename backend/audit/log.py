"""Einträge ins Änderungsprotokoll schreiben."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from decimal import Decimal
from typing import Any

from django.db import models
from django.db.models.fields.files import FieldFile

from changes.tracking import current_set_id
from core.tenancy import tenant_context

from .models import AuditEntry

# Herkunft der Änderungen dieser Anfrage (Verwaltung in der App setzt „App (Gerät)“)
current_via: ContextVar[str] = ContextVar("hubiplan_audit_via", default="")

IGNORED_FIELDS = {"created_at", "updated_at", "id", "organization", "uuid"}

# Lesbare Namen der protokollierten Objekte
OBJECT_TYPES = {
    "organization": "Organisation",
    "department": "Abteilung",
    "departmentrole": "Abteilungsrolle",
    "role": "Rolle",
    "roleassignment": "Rollenzuordnung",
    "platformsettings": "Plattform-Einstellungen",
    "membertype": "Mitgliedsart",
    "membership": "Mitgliedschaft",
    "membershipperiod": "Mitgliedszeitraum",
    "membertypeassignment": "Mitgliedsart-Zuordnung",
    "departmentmembership": "Abteilungszugehörigkeit",
    "departmentroleholder": "Abteilungsrolle",
    "honorarytitle": "Ehrung",
    "honorarytitleaward": "Ehrung (Verleihung)",
    "federationmember": "Verbandsmitgliedschaft",
    "contactdetails": "Kontaktdaten",
    "person": "Person",
    "fielddefinition": "Zusatzfeld",
    "fieldvalue": "Zusatzfeld-Wert",
    "exportjob": "Export",
    "exporttemplate": "Exportvorlage",
    "importjob": "Import",
    "importtemplate": "Importvorlage",
    "memberphoto": "Mitgliederfoto",
    "photouploadlink": "Foto-Upload-Link",
    "account": "Konto",
    "category": "Kategorie",
    "booking": "Buchung",
    "receipt": "Beleg",
    "reserve": "Rücklage",
    "reservemovement": "Rücklagenbewegung",
    "changerequest": "Änderungsmeldung",
    "transferjob": "Datenübernahme",
    "event": "Termin",
    "eventcategory": "Terminkategorie",
    "eventexception": "Serientermin",
    "eventattachment": "Terminanhang",
    "calendarpublication": "Öffentlicher Kalender",
    "circular": "Rundschreiben",
    "circulartemplate": "Vorlage für Rundschreiben",
    "circularattachment": "Anhang eines Rundschreibens",
    "website": "Webseite",
    "websitedomain": "Domain der Webseite",
    "previewlink": "Vorschau-Link",
    "websitetext": "Text der Webseite",
    "websiteimage": "Bild der Webseite",
    "heldmessage": "Nachricht von der Webseite",
    "dignity": "Würde",
    "reign": "Regentschaft",
    "companion": "Begleitperson",
    "reignphoto": "Foto einer Regentschaft",
}


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, FieldFile):
        return value.name or ""
    if isinstance(value, models.Model):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def snapshot(instance: models.Model) -> dict[str, Any]:
    data = {}
    # Modelle können die protokollierten Felder eingrenzen (z. B. Untereinheiten,
    # die viele Felder der Organisationstabelle nicht nutzen)
    only = getattr(instance, "audit_fields", None)
    for field in instance._meta.concrete_fields:
        if field.name in IGNORED_FIELDS or (only is not None and field.name not in only):
            continue
        # Lesbarer deutscher Feldname fürs Protokoll
        data[str(field.verbose_name)] = _plain(getattr(instance, field.attname))
    return data


def type_label(object_type: str) -> str:
    """Lesbarer Name einer protokollierten Objektart; ohne Eintrag in OBJECT_TYPES
    steht der technische Modellname (z. B. „imprint“), dann gilt dessen verbose_name."""
    if object_type in OBJECT_TYPES:
        return OBJECT_TYPES[object_type]
    if object_type.isascii() and object_type.islower():
        from django.apps import apps

        for model in apps.get_models():
            if model._meta.model_name == object_type:
                return str(model._meta.verbose_name)
    return object_type


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[Any]]:
    return {
        key: [before.get(key), after.get(key)]
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    }


def record(
    organization,
    user,
    action: str,
    instance: models.Model,
    changes: dict | None = None,
    person=None,
) -> AuditEntry:
    model = instance._meta.model_name
    # Rollen und Inhaber von Untereinheiten (auch ohne die Sicht DepartmentRole)
    if model == "role" and getattr(instance, "department_id", None):
        model = "departmentrole"
    elif model == "roleassignment" and getattr(instance, "membership_id", None):
        model = "departmentroleholder"
    from .chain import seal_later

    seal_later(organization.pk)
    with tenant_context(organization.pk):
        return AuditEntry.objects.create(
            organization=organization,
            user=user if user and user.is_authenticated else None,
            user_email=getattr(user, "email", "") or "",
            action=action,
            object_type=OBJECT_TYPES.get(model, model),
            object_id=str(instance.pk),
            object_repr=str(instance)[:200],
            changes=changes or {},
            person_id=getattr(person, "pk", None),
            change_set=current_set_id(),
            via=current_via.get()[:100],
        )
