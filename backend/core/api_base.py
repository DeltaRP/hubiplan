"""Gemeinsame Bausteine für die organisationsbezogene API."""

from __future__ import annotations

import copy

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied

from access.permissions import permissions_in
from audit.log import diff, record, snapshot
from organizations.models import Organization

from .tenancy import scope_of, set_rls


class OrgScopedMixin:
    """API-Ansicht innerhalb einer Organisation (URL-Parameter ``org_id``).

    1. Organisation laden und prüfen, dass der Benutzer dort eine aktive Rolle hat.
       Sonst 404 – fremde Organisationen sollen nicht einmal sichtbar sein.
    2. Lesen: ``read_permission`` (None = jede Rolle der Organisation genügt).
       Schreiben: ``write_permission``.
    3. Erst dann die RLS-Variable ``app.org_id`` setzen.
    """

    read_permission: str | None = None
    write_permission: str | None = None
    allowed_org_types: tuple[str, ...] | None = None

    org: Organization
    org_permissions: set[str]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        org = get_object_or_404(Organization, pk=kwargs["org_id"])
        perms = permissions_in(request.user, org)
        if not perms:
            raise NotFound()
        if self.allowed_org_types and org.type not in self.allowed_org_types:
            raise NotFound("Für diese Art von Organisation nicht verfügbar.")
        needed = (
            self.read_permission
            if request.method in ("GET", "HEAD", "OPTIONS")
            else self.write_permission
        )
        if needed and needed not in perms:
            raise PermissionDenied("Dafür fehlt dir die Berechtigung.")
        self.org = org
        self.org_permissions = perms
        # Dachverband: Zugriff auf Mitgliedsdaten seiner Vereine nur gemäß Plattform-Freigabe
        fed_access = ""
        if org.type == Organization.Type.FEDERATION and org.federation_member_access != "none":
            fed_access = org.federation_member_access
        set_rls(org.pk, request.user.pk, scope_id=scope_of(org.pk), fed_access=fed_access)


class AuditMixin:
    """Schreibt Anlegen, Ändern und Löschen ins Änderungsprotokoll."""

    def audit_org(self, instance):
        return self.org

    @transaction.atomic
    def perform_create(self, serializer):
        # Speichern und Protokoll gemeinsam: scheitert das Protokoll, bleibt nichts halb
        instance = serializer.save(**self.get_create_kwargs())
        record(
            self.audit_org(instance),
            self.request.user,
            "create",
            instance,
            diff({}, snapshot(instance)),
        )

    def get_create_kwargs(self) -> dict:
        return {}

    def perform_update(self, serializer):
        with transaction.atomic():
            if self._lock_and_refresh(serializer.instance):
                serializer = self._revalidate(serializer)
            self._update(serializer)

    @staticmethod
    def _lock_and_refresh(instance) -> bool:
        """Zeile sperren und frisch lesen: Eine gleichzeitige Änderung anderer Felder
        bleibt erhalten, statt vom veralteten Stand dieser Anfrage überschrieben zu werden.
        Gibt zurück, ob sich die Zeile seit dem Lesen geändert hat."""
        model = type(instance)
        fields = [f.attname for f in model._meta.concrete_fields]
        seen = {name: getattr(instance, name, None) for name in fields}
        list(model._base_manager.select_for_update().filter(pk=instance.pk).values_list("pk"))
        instance.refresh_from_db()
        return any(getattr(instance, name, None) != seen[name] for name in fields)

    @staticmethod
    def _revalidate(serializer):
        """Auf dem frischen Stand erneut prüfen: Zwei einzeln gültige Änderungen (z. B.
        Tag 30 und Monat Februar) dürfen zusammen keinen ungültigen Stand ergeben."""
        fresh = type(serializer)(
            serializer.instance,
            data=serializer.initial_data,
            partial=serializer.partial,
            context=serializer.context,
        )
        fresh.is_valid(raise_exception=True)
        return fresh

    def _update(self, serializer):
        before = snapshot(serializer.instance)
        instance = serializer.save()
        changes = diff(before, snapshot(instance))
        if changes:
            record(self.audit_org(instance), self.request.user, "update", instance, changes)

    @transaction.atomic
    def perform_destroy(self, instance):
        record(
            self.audit_org(instance),
            self.request.user,
            "delete",
            instance,
            diff(snapshot(instance), {}),
        )
        instance.delete()


class ModelCleanMixin:
    """Führt ``Model.clean()`` bei der Validierung aus (DRF tut das nicht)."""

    def extra_clean_attrs(self) -> dict:
        return {}

    def validate(self, attrs):
        attrs = super().validate(attrs)
        model = self.Meta.model
        instance = copy.copy(self.instance) if self.instance is not None else model()
        for key, value in {**self.extra_clean_attrs(), **attrs}.items():
            setattr(instance, key, value)
        try:
            instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "error_dict") else exc.messages
            ) from exc
        return attrs
