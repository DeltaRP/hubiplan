"""Hilfe (konzepte/hilfe-funktion.md, docs/hilfe.md): Angaben aus der Einheit.

- Ansprechpartner für Fragen zu HUBIplan (3.6): nur Personen, die die Einheit ausdrücklich
  einträgt; sonst nennt die Hilfe nur Rollennamen.
- Hinweise des Vereins zu einzelnen Anleitungen (3.7), vererbt an die Untereinheiten.
- „Warum sehe ich das nicht?“ (3.5): Beschriftungen der Rechte und welche Rollen der
  Einheit Rechte vergeben dürfen.

Lesen darf jede Person mit einer Rolle in der Einheit, ändern nur mit „Organisationsdaten
bearbeiten“. Die Texte der Anleitungen selbst liegen im Frontend (src/help/).
"""

from __future__ import annotations

import re

from django.db import transaction
from django.utils.translation import gettext
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import ORG_EDIT, ROLES_MANAGE, catalog_for
from access.models import Role
from audit.log import record
from core.api_base import OrgScopedMixin

from .models import Organization

GUIDE_KEY = re.compile(r"^guide\.[a-z0-9_]{1,60}$")
MAX_CONTACTS = 10
MAX_NOTE = 500


def clean_contacts(raw) -> list[dict]:
    """Nur bekannte Felder in vernünftiger Länge (auch nach einem Import)."""
    out = []
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict) or not str(c.get("name", "")).strip():
            continue
        out.append(
            {
                "name": str(c.get("name", "")).strip()[:100],
                "hint": str(c.get("hint", "")).strip()[:200],
                "email": str(c.get("email", "")).strip()[:254],
            }
        )
    return out[:MAX_CONTACTS]


def clean_notes(raw) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {
        k: str(v).strip()[:MAX_NOTE]
        for k, v in raw.items()
        if isinstance(k, str) and GUIDE_KEY.match(k) and str(v).strip()
    }


def chain(org: Organization) -> list[Organization]:
    """Die Einheit und alle darüber, die oberste zuerst (ohne Plattform)."""
    out = []
    node = org
    while node is not None and node.type != Organization.Type.PLATFORM:
        out.append(node)
        node = node.parent
    return list(reversed(out))


class ContactSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    hint = serializers.CharField(max_length=200, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)


class HelpUpdateSerializer(serializers.Serializer):
    contacts = ContactSerializer(many=True, required=False)

    def validate_contacts(self, value):
        if len(value) > MAX_CONTACTS:
            raise serializers.ValidationError(
                gettext("Höchstens {n} Ansprechpartner.").format(n=MAX_CONTACTS)
            )
        return value


class NoteSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=MAX_NOTE, allow_blank=True)


def help_state(org: Organization, perms: set[str]) -> dict:
    units = chain(org)
    # Ansprechpartner: die eigenen, sonst die der nächsten Einheit darüber
    contacts, contacts_from = [], None
    for unit in reversed(units):
        found = clean_contacts(unit.help_contacts)
        if found:
            contacts, contacts_from = found, unit
            break
    # Hinweise: von oben nach unten; die Einheit selbst zuletzt
    notes: dict[str, list[dict]] = {}
    for unit in units:
        for key, text in clean_notes(unit.help_notes).items():
            notes.setdefault(key, []).append(
                {"text": text, "from": unit.display_name, "own": unit.pk == org.pk}
            )
    admin_roles = sorted(
        {
            r.name
            for r in Role.objects.filter(organization=org)
            if ROLES_MANAGE in (r.permissions or [])
        }
    )
    rights = {p["code"]: p["label"] for m in catalog_for(org.type, org) for p in m["permissions"]}
    return {
        "contacts": contacts,
        "contacts_from": (
            {"name": contacts_from.display_name, "own": contacts_from.pk == org.pk}
            if contacts_from
            else None
        ),
        "own_contacts": clean_contacts(org.help_contacts),
        "notes": notes,
        "admin_roles": admin_roles,
        "rights": rights,
        "can_edit": ORG_EDIT in perms,
    }


@extend_schema(responses=dict)
class OrgHelpView(OrgScopedMixin, APIView):
    """GET: Angaben der Einheit für die Hilfe · PATCH: Ansprechpartner festlegen."""

    write_permission = ORG_EDIT

    def get(self, request, org_id: int):
        return Response(help_state(self.org, self.org_permissions))

    @extend_schema(request=HelpUpdateSerializer, responses=dict)
    def patch(self, request, org_id: int):
        data = HelpUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        org = self.org
        if "contacts" in data.validated_data:
            before = clean_contacts(org.help_contacts)
            after = clean_contacts(data.validated_data["contacts"])
            if before != after:
                with transaction.atomic():
                    org.help_contacts = after
                    org.save(update_fields=["help_contacts"])
                    record(
                        org,
                        request.user,
                        "update",
                        org,
                        {"Ansprechpartner für Fragen zu HUBIplan": [before, after]},
                    )
        return Response(help_state(org, self.org_permissions))


@extend_schema(request=NoteSerializer, responses=dict)
class OrgHelpNoteView(OrgScopedMixin, APIView):
    """PUT: Hinweis des Vereins zu einer Anleitung setzen; leerer Text entfernt ihn."""

    write_permission = ORG_EDIT

    def put(self, request, org_id: int, key: str):
        if not GUIDE_KEY.match(key):
            raise PermissionDenied(gettext("Unbekannte Anleitung."))
        data = NoteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        org = self.org
        notes = clean_notes(org.help_notes)
        before = notes.get(key, "")
        text = data.validated_data["text"].strip()
        if text:
            notes[key] = text
        else:
            notes.pop(key, None)
        if before != text:
            with transaction.atomic():
                org.help_notes = notes
                org.save(update_fields=["help_notes"])
                record(
                    org,
                    request.user,
                    "update",
                    org,
                    {f"Hinweis zur Hilfe ({key})": [before, text]},
                )
        return Response(help_state(org, self.org_permissions))
