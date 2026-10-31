"""Impressum und Datenschutzhinweise, wie sie nach außen gelten.

Jede Einheit hat ein Impressum (``Imprint``), das sie entweder selbst pflegt,
auf eine eigene Seite verlinkt oder von der übergeordneten Einheit übernimmt.
Untereinheiten übernehmen standardmäßig. Am Ende der Kette steht die Plattform.
Leere Felder werden aus den Stammdaten der Einheit ergänzt; Vertretungsberechtigte
kommen aus den Rollen mit dem Kennzeichen „vertritt die Einheit“.

Hinweis: HUBIplan bildet Pflichtangaben nur technisch ab. Ob sie im Einzelfall
vollständig sind, prüft die Einheit selbst.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.db import IntegrityError, transaction

from core.tenancy import rls_bypass

from .models import Imprint, Organization


def ensure(org: Organization) -> Imprint:
    """Impressum der Einheit; legt es beim ersten Zugriff mit Standardwerten an."""
    imprint = Imprint.objects.filter(organization=org).first()
    if imprint is not None:
        return imprint
    try:
        with transaction.atomic():
            return Imprint.objects.create(
                organization=org,
                mode=Imprint.default_mode(org),
                # „e.V.“ im Namen: als eingetragen vorbelegen
                registered=bool(re.search(r"\be\.\s?V\.", org.name)),
            )
    except IntegrityError:
        return Imprint.objects.get(organization=org)


def owner_of(org: Organization) -> tuple[Organization, Imprint]:
    """Einheit, deren Impressum für ``org`` gilt (sie selbst oder eine darüber)."""
    for node in org.ancestors():
        imprint = ensure(node)
        if imprint.mode != Imprint.Mode.INHERIT or node.type == Organization.Type.PLATFORM:
            return node, imprint
    platform = Organization.platform()
    return platform, ensure(platform)


def representatives(org: Organization) -> list[dict]:
    """Heutige Inhaber der Rollen mit „vertritt die Einheit“ (Name und Funktion)."""
    from access.models import RoleAssignment

    with rls_bypass():
        rows = (
            RoleAssignment.objects.active()
            .filter(organization=org, role__represents=True)
            .select_related("role", "user", "person")
            .order_by("role__name", "valid_from")
        )
        result, seen = [], set()
        for row in rows:
            if row.person_id:
                name = f"{row.person.first_name} {row.person.last_name}".strip()
            elif row.user_id:
                name = row.user.get_full_name() or ""
            else:
                name = ""
            if not name or (name, row.role.name) in seen:
                continue
            seen.add((name, row.role.name))
            result.append({"name": name, "role": row.role.name})
    return result


def page_urls(org: Organization) -> dict:
    """Öffentliche Adressen von Impressum und Datenschutz für ``org``."""
    base = settings.FRONTEND_URL.rstrip("/")
    if org.type == Organization.Type.PLATFORM:
        return {"imprint": f"{base}/impressum", "privacy": f"{base}/datenschutz"}
    key = ensure(org).public_key
    return {"imprint": f"{base}/impressum/{key}", "privacy": f"{base}/datenschutz/{key}"}


def _contact(owner: Organization) -> tuple[str, str]:
    if owner.type == Organization.Type.PLATFORM:
        return owner.contact_email, owner.contact_phone
    from .serializers import effective_contact

    with rls_bypass():
        contact = effective_contact(owner)
    return contact["email"], contact["phone"]


def missing(owner: Organization, imprint: Imprint, data: dict | None = None) -> list[str]:
    """Fehlende Angaben, die üblicherweise ins Impressum gehören."""
    if imprint.mode == Imprint.Mode.LINK:
        result = []
    else:
        data = data or details(owner, imprint)
        result = []
        address = data["address"]
        if not (address["street"] and address["postal_code"] and address["city"]):
            result.append("Anschrift")
        if owner.type != Organization.Type.PLATFORM and not (
            data["representatives"] or data["representatives_text"]
        ):
            result.append("Vertretungsberechtigte")
        if not data["email"]:
            result.append("E-Mail")
        if not data["phone"]:
            result.append("Telefon (zweiter Kontaktweg)")
        if imprint.registered:
            if not data["register_court"]:
                result.append("Registergericht")
            if not data["register_number"]:
                result.append("Registernummer")
    if imprint.privacy_mode == Imprint.PrivacyMode.LINK:
        if not imprint.privacy_url:
            result.append("Datenschutzhinweise")
    elif not imprint.privacy_published_text.strip():
        result.append("Datenschutzhinweise")
    return result


def guess_legal_form(owner: Organization, imprint: Imprint) -> str:
    """Rechtsform, wenn keine eingetragen ist: bei eingetragenen Einheiten
    „eingetragener Verein“ (die Plattform rät nichts)."""
    if imprint.legal_form:
        return imprint.legal_form
    if imprint.registered and owner.type != Organization.Type.PLATFORM:
        return "eingetragener Verein"
    return ""


def details(owner: Organization, imprint: Imprint) -> dict:
    """Die Angaben des Impressums mit ergänzten Stammdaten."""
    email, phone = _contact(owner)
    reps = [] if imprint.representatives.strip() else representatives(owner)
    return {
        "name": imprint.name or owner.name,
        "legal_form": guess_legal_form(owner, imprint),
        "address": {
            "street": imprint.street or owner.street,
            "postal_code": imprint.postal_code or owner.postal_code,
            "city": imprint.city or owner.city,
            "country": owner.country,
        },
        "representatives": reps,
        "representatives_text": imprint.representatives.strip(),
        "email": imprint.email or email,
        "phone": imprint.phone or phone,
        "website": owner.website,
        # Registerangaben nur bei eingetragenen Einheiten
        "registered": imprint.registered,
        "register_court": imprint.register_court if imprint.registered else "",
        "register_number": imprint.register_number if imprint.registered else "",
        "vat_id": imprint.vat_id,
        "responsible": imprint.responsible.strip(),
        "data_protection_officer": imprint.data_protection_officer.strip(),
        "extra_text": imprint.extra_text.strip(),
    }


def public_data(org: Organization) -> dict:
    """Was die öffentliche Seite für ``org`` zeigt."""
    owner, imprint = owner_of(org)
    data = details(owner, imprint) if imprint.mode == Imprint.Mode.OWN else None
    privacy = {
        "mode": imprint.privacy_mode,
        "text": imprint.privacy_published_text
        if imprint.privacy_mode == Imprint.PrivacyMode.TEXT
        else "",
        "url": imprint.privacy_url if imprint.privacy_mode == Imprint.PrivacyMode.LINK else "",
    }
    return {
        "unit": org.name,
        "owner": owner.name,
        "owner_label": "" if owner.type == Organization.Type.PLATFORM else owner.kind_label,
        "is_platform": owner.type == Organization.Type.PLATFORM,
        "inherited": owner.pk != org.pk,
        "mode": imprint.mode,
        "external_url": imprint.external_url if imprint.mode == Imprint.Mode.LINK else "",
        "details": data,
        "privacy": privacy,
        "updated_at": imprint.updated_at,
    }
