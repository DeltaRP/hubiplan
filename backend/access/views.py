from __future__ import annotations

from contextlib import contextmanager

from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from accounts.models import User
from audit.log import diff, record, snapshot, type_label
from audit.models import AuditEntry
from core.api_base import AuditMixin, OrgScopedMixin
from core.listing import ListPagination, search
from core.reorder import reorder_response
from core.tenancy import tenant_context
from organizations import theme
from organizations.models import Organization
from organizations.terms import department_terms, rename_word

from . import preview
from .catalog import AUDIT_VIEW, ROLES_MANAGE, ROLES_PREVIEW, catalog_for
from .models import Role, RoleAssignment
from .permissions import (
    inherited_permissions,
    organizations_for,
    own_permissions_in,
    permissions_in,
)
from .serializers import AssignmentSerializer, RoleSerializer


class _OrgContextMixin:
    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["org"] = getattr(self, "org", None)
        return ctx

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}


class RoleViewSet(_OrgContextMixin, OrgScopedMixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = RoleSerializer
    read_permission = ROLES_MANAGE
    write_permission = ROLES_MANAGE

    def get_queryset(self):
        # Eine Reihenfolge für HUBIplan und Webseite, per Ziehen festgelegt (Ralf 31.10.)
        return Role.objects.filter(organization=self.org).order_by("position", "name")

    @action(detail=False, methods=["post"])
    def reorder(self, request, *args, **kwargs):
        return reorder_response(
            request,
            self.org,
            Role.objects.filter(organization=self.org),
            "position",
            also=("website_position",),
        )

    @transaction.atomic
    def perform_update(self, serializer):
        with _keeps_roles_manage(self.request.user, self.org):
            super().perform_update(serializer)

    @transaction.atomic
    def perform_destroy(self, instance):
        # Noch vergeben? Dann verlieren die Inhaber die Rolle (nach Rückfrage in der App).
        if _locks_out(self.request.user, self.org, instance):
            raise serializers.ValidationError(LOCKOUT)
        for assignment in instance.assignments.select_related("user", "person"):
            record(
                self.org,
                self.request.user,
                "delete",
                assignment,
                diff(snapshot(assignment), {}),
                person=assignment.person,
            )
        super().perform_destroy(instance)


LOCKOUT = "Du kannst dir die Rollenverwaltung nicht selbst entziehen."


@contextmanager
def _keeps_roles_manage(user, org: Organization):
    """Änderung ausführen; endet dadurch die eigene Rollenverwaltung, wird sie abgelehnt.

    Muss in einer Transaktion laufen: Die Prüfung nach der Änderung rollt sie zurück.
    """
    _serialize(user)
    had = ROLES_MANAGE in permissions_in(user, org)
    yield
    if had and ROLES_MANAGE not in permissions_in(user, org):
        raise serializers.ValidationError(LOCKOUT)


def _serialize(user) -> None:
    """Gleichzeitige Rollenänderungen desselben Benutzers nacheinander prüfen.

    Sonst sehen zwei parallele Anfragen, die je eine von zwei eigenen Verwaltungsrollen
    entfernen, jeweils noch die andere (Gesamtaudit 31.10.b, AT-V05)."""
    User.objects.select_for_update().filter(pk=user.pk).values_list("pk").first()


def _locks_out(user, org: Organization, role: Role) -> bool:
    """Verliert der Benutzer mit dieser Rolle das Recht, Rollen zu verwalten?"""
    _serialize(user)
    if ROLES_MANAGE not in role.permissions:
        return False
    if not role.assignments.active().filter(user=user).exists():
        return False
    others = (
        RoleAssignment.objects.active()
        .filter(user=user, organization=org)
        .exclude(role=role)
        .select_related("role")
    )
    perms: set[str] = set()
    for assignment in others:
        perms.update(assignment.role.permissions)
    if org.type == Organization.Type.UNIT:
        perms |= inherited_permissions(user, org)
    return ROLES_MANAGE not in perms


def _has_rights_elsewhere(target, org) -> bool:
    """Hat das Konto Rechte außerhalb von ``org`` und ihren Untereinheiten?

    Plattform-, Staff- und Superuser-Konten zählen immer dazu. Gelesen wird in der Sicht des
    Zielkontos, sonst blendet RLS dessen Rollen in fremden Organisationen aus.
    """
    from access.permissions import is_platform_admin
    from core.tenancy import rls_bypass, user_view

    if target.is_staff or target.is_superuser or is_platform_admin(target):
        return True
    with user_view(target.pk):
        org_ids = set(
            RoleAssignment.objects.active()
            .filter(user=target)
            .values_list("organization_id", flat=True)
        )
    org_ids.discard(org.pk)
    if not org_ids:
        return False
    # Nur Baumstruktur lesen (ohne Inhalte); fehlt eine Zeile, lieber ablehnen
    with rls_bypass():
        parents = dict(Organization.objects.values_list("pk", "parent_id"))
    for org_id in org_ids:
        node = org_id
        while node is not None and node != org.pk:
            node = parents.get(node)
        if node is None:
            return True
    return False


class AssignmentViewSet(_OrgContextMixin, OrgScopedMixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = AssignmentSerializer
    read_permission = ROLES_MANAGE
    write_permission = ROLES_MANAGE

    def get_queryset(self):
        # Freie Einträge früherer Inhaber (Mitglieder › Ämter) haben kein Konto
        qs = RoleAssignment.objects.filter(organization=self.org, name="").select_related(
            "user", "role", "person"
        )
        if self.request.query_params.get("aktiv") == "1":
            qs = qs.active()
        return qs.order_by("user__email", "-valid_from")

    def get_create_kwargs(self) -> dict:
        return {}

    @transaction.atomic
    def perform_update(self, serializer):
        # Auch Zeitraum oder Rolle der eigenen Zuordnung ändern darf die eigene
        # Rollenverwaltung nicht beenden (wie beim Löschen).
        with _keeps_roles_manage(self.request.user, self.org):
            super().perform_update(serializer)

    @transaction.atomic
    def perform_destroy(self, instance):
        with _keeps_roles_manage(self.request.user, self.org):
            super().perform_destroy(instance)

    @extend_schema(request=None)
    @action(detail=True, methods=["post"], url_path="reset-mfa")
    @transaction.atomic
    def reset_mfa(self, request, *args, **kwargs):
        """Zwei-Faktor-Anmeldung eines Rolleninhabers zurücksetzen (Handy und Codes weg).

        Nur durch eine zweite Person mit Rollenverwaltung, die selbst einen zweiten Faktor
        hat (Gesamtaudit 31.10.b, Frage 1); nie für sich selbst. Das Konto muss den zweiten
        Faktor sofort neu einrichten, bis dahin ruhen heikle Rechte.
        """
        from allauth.mfa.models import Authenticator
        from django.utils import timezone

        from accounts.mfa_policy import has_mfa
        from accounts.security import secure_account
        from core.alarm import send_alert
        from outbox import mail

        assignment = self.get_object()
        target = assignment.user
        if target.pk == request.user.pk:
            raise serializers.ValidationError(
                {"detail": "Die eigene Zwei-Faktor-Anmeldung setzt eine zweite Person zurück."}
            )
        if not has_mfa(request.user):
            raise serializers.ValidationError(
                {"detail": "Zurücksetzen darf nur, wer selbst die Zwei-Faktor-Anmeldung nutzt."}
            )
        if not RoleAssignment.objects.active().filter(pk=assignment.pk).exists():
            raise serializers.ValidationError({"detail": "Die Rolle ist nicht mehr aktiv."})
        if _has_rights_elsewhere(target, self.org):
            # Die Zwei-Faktor-Anmeldung gilt für das ganze Konto. Ein Verein darf sie nur
            # für Konten zurücksetzen, die allein hier Rechte haben (Gesamtaudit 01.11., GA-S01).
            raise serializers.ValidationError(
                {
                    "detail": "Dieses Konto hat auch außerhalb dieses Vereins Rechte. "
                    "Die Zwei-Faktor-Anmeldung setzt dann nur die Plattform-Verwaltung zurück."
                }
            )
        removed, _ = Authenticator.objects.filter(user=target).delete()
        if not removed:
            raise serializers.ValidationError(
                {"detail": "Für dieses Konto ist keine Zwei-Faktor-Anmeldung eingerichtet."}
            )
        User.objects.filter(pk=target.pk).update(mfa_required_by=timezone.now())
        secure_account(target, devices=True)
        record(
            self.org,
            request.user,
            "update",
            assignment,
            {"Zwei-Faktor-Anmeldung": ["eingerichtet", f"zurückgesetzt von {request.user.email}"]},
        )
        org = self.org
        transaction.on_commit(
            lambda: mail.send(
                target.email,
                f"Ihre Zwei-Faktor-Anmeldung bei HUBIplan – {org.name} wurde zurückgesetzt",
                (
                    f"Guten Tag,\n\n{request.user.email} hat Ihre Zwei-Faktor-Anmeldung "
                    f"zurückgesetzt ({org.name}). Bitte richten Sie sie nach der nächsten "
                    "Anmeldung unter „Mein Konto › Anmeldung & Sicherheit“ neu ein; bis dahin "
                    "ruhen Rollenverwaltung, Exporte und Kasse. App-Geräte wurden abgemeldet.\n\n"
                    f"Wenn Sie das nicht veranlasst haben, wenden Sie sich bitte an {org.name}.\n"
                ),
                organization=org,
                kind="zugang",
            )
        )
        transaction.on_commit(
            lambda: send_alert(
                "Zwei-Faktor-Anmeldung zurückgesetzt",
                [f"Konto: {target.email}", f"durch: {request.user.email}", f"in: {org.name}"],
            )
        )
        return Response({"reset": True})


class AuditEntrySerializer(serializers.ModelSerializer):
    action_label = serializers.CharField(source="get_action_display")
    object_type = serializers.SerializerMethodField()
    changes = serializers.SerializerMethodField()
    undo = serializers.SerializerMethodField()

    def _org(self):
        return self.context.get("org")

    def get_object_type(self, obj) -> str:
        return rename_word(type_label(obj.object_type), self._org())

    def get_undo(self, obj) -> dict | None:
        """Rückgängig aus dem Protokoll: möglich, schon erledigt oder gesperrt (mit Grund)."""
        change_set = self.context.get("change_sets", {}).get(obj.change_set)
        if change_set is None:
            return None
        if change_set.blocked_reason:
            state = "blocked"
        elif change_set.reverted_by:
            state = "done"
        else:
            state = "possible"
        return {
            "change_set": str(change_set.pk),
            "state": state,
            "reason": change_set.blocked_reason,
            "is_undo": change_set.reverts is not None,
        }

    def get_changes(self, obj) -> dict:
        # Feldnamen wie „Abteilung“ in der eigenen Bezeichnung zeigen
        org = self._org()
        return {rename_word(k, org): v for k, v in (obj.changes or {}).items()}

    class Meta:
        model = AuditEntry
        fields = [
            "id",
            "timestamp",
            "user_email",
            "via",
            "action",
            "action_label",
            "object_type",
            "object_repr",
            "changes",
            "undo",
        ]


def change_set_map(entries) -> dict:
    from changes.models import ChangeSet

    ids = {e.change_set for e in entries if e.change_set}
    return {cs.pk: cs for cs in ChangeSet.objects.filter(pk__in=ids)}


class AuditListView(_OrgContextMixin, OrgScopedMixin, generics.ListAPIView):
    """Änderungsprotokoll mit Suche (Objekt, Person, Art), Zeitraum und Seiten."""

    serializer_class = AuditEntrySerializer
    read_permission = AUDIT_VIEW
    pagination_class = ListPagination

    def get_queryset(self):
        qs = AuditEntry.objects.filter(organization=self.org)
        params = self.request.query_params
        if params.get("aktion") in {"create", "update", "delete"}:
            qs = qs.filter(action=params["aktion"])
        return search(qs, params, ("object_repr", "object_type", "user_email"), "timestamp")

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        context = {**self.get_serializer_context(), "change_sets": change_set_map(page)}
        return self.get_paginated_response(
            AuditEntrySerializer(page, many=True, context=context).data
        )


def _catalog_org(request: Request) -> Organization | None:
    """Organisation, deren Abteilungsbezeichnung der Katalog verwenden soll."""
    raw = request.query_params.get("org")
    if not raw or not raw.isdigit() or not request.user.is_authenticated:
        return None
    org_id = int(raw)
    for org, _perms in organizations_for(request.user):
        if org.pk == org_id:
            return org
    from portal.services import department_contexts

    for ctx in department_contexts(request.user).values():
        if ctx.club.pk == org_id:
            return ctx.club
    return None


@extend_schema(
    parameters=[
        OpenApiParameter("org_type", str, required=False),
        OpenApiParameter("org", int, required=False),
    ]
)
@api_view(["GET"])
def permission_catalog(request: Request) -> Response:
    """Berechtigungskatalog, nach Modulen gegliedert (Texte mit eigener Bezeichnung)."""
    return Response(catalog_for(request.query_params.get("org_type"), _catalog_org(request)))


def ensure_imprint(org: Organization):
    from organizations.imprint import ensure

    return ensure(org)


def organization_summary(org: Organization, perms: set[str]) -> dict:
    imprint = ensure_imprint(org)
    return {
        "id": org.pk,
        "name": org.name,
        "short_name": org.short_name,
        "display_name": org.display_name,
        "type": org.type,
        "type_label": org.kind_label,
        "label": org.label,
        "label_plural": org.label_plural,
        "parent_name": org.parent.name if org.parent and org.parent.type != "platform" else None,
        "parent_display_name": (
            org.parent.display_name if org.parent and org.parent.type != "platform" else None
        ),
        "permissions": sorted(perms),
        "modules": list(org.enabled_modules) if org.type != Organization.Type.PLATFORM else [],
        "department_label": org.department_label,
        "department_label_plural": org.department_label_plural,
        "department_terms": department_terms(org),
        "date_precision": org.date_precision,
        "federation_member_access": (
            org.federation_member_access if org.type == Organization.Type.FEDERATION else None
        ),
        "theme": theme.effective_theme(org.ancestors()),
        "sepa_enabled": _sepa_enabled(org),
        # Kasse: Zählprotokoll und Kassenbericht für Feste (Schalter unter Konten)
        "cash_counts_enabled": bool(org.cash_counts_enabled) and org.type != "platform",
        # Kasse: Rücklagen nach § 62 AO (Schalter unter Konten)
        "reserves_enabled": bool(org.reserves_enabled) and org.type != "platform",
        "direct_members": org.type == Organization.Type.FEDERATION and org.direct_members,
        "imprint_key": imprint.public_key,
        # Schalter „Eingetragener Verein“ (Impressum, Briefbogen)
        "registered": bool(imprint.registered) and org.type != Organization.Type.PLATFORM,
        # Schalter „steuerbegünstigt mit eigenem Bescheid“ (Zuwendungsbestätigungen)
        "donations_enabled": _donations_enabled(org),
    }


def _donations_enabled(org: Organization) -> bool:
    from core.tenancy import tenant_context
    from finance.donations import is_enabled

    with tenant_context(org.pk):
        return is_enabled(org)


def _sepa_enabled(org: Organization) -> bool:
    """SEPA-Lastschrift eingeschaltet (Einstellung unter Finanzen)."""
    if org.type == Organization.Type.PLATFORM or "billing" not in (org.enabled_modules or []):
        return False
    from billing.models import BillingSettings
    from core.tenancy import tenant_context

    with tenant_context(org.pk):
        return BillingSettings.objects.filter(organization=org, sepa_enabled=True).exists()


@api_view(["GET"])
def my_organizations(request: Request) -> Response:
    """Organisationen, in denen der angemeldete Benutzer eine Rolle hat.

    ``role_preview``: Darf hier die Ansicht als Rolle gewählt werden, und welche Rolle
    ist gerade gewählt? ``permissions`` sind während der Ansicht die der Ansicht.
    """
    current = preview.current()
    if current:
        org = Organization.objects.filter(pk=current.org_id).first()
        own = own_permissions_in(request.user, org) if org else set()
        if ROLES_PREVIEW not in own or preview.role_permissions(org, current.role_id) is None:
            # Recht entzogen oder Rolle gelöscht: Ansicht endet
            preview.stop(request)
            current = None
    entries = organizations_for(request.user)
    if current and all(org.pk != current.org_id for org, _ in entries):
        # Rolle ohne Rechte in einer Untereinheit: Einheit bleibt wählbar, um zu beenden
        org = Organization.objects.get(pk=current.org_id)
        entries.append((org, permissions_in(request.user, org)))
    result = []
    for org, perms in entries:
        summary = organization_summary(org, perms)
        own = perms
        active = None
        if current and current.org_id == org.pk:
            own = own_permissions_in(request.user, org)
            with tenant_context(org.pk):
                active = Role.objects.filter(pk=current.role_id).values("id", "name").first()
        summary["role_preview"] = {"available": ROLES_PREVIEW in own, "active": active}
        result.append(summary)
    return Response(result)


class AuditChainView(OrgScopedMixin, generics.GenericAPIView):
    """Prüfung der Protokollkette (Finanzamt-Prüfung C3): letztes Ergebnis bzw. jetzt prüfen."""

    read_permission = AUDIT_VIEW
    write_permission = AUDIT_VIEW

    @staticmethod
    def _data(check) -> dict | None:
        if check is None:
            return None
        return {
            "checked_at": check["checked_at"],
            "ok": check["ok"],
            "entries": check["entries"],
            "cleared": check["cleared"],
            "head_seq": check["head_seq"],
            "head_hash": check["head_hash"],
            "problems": check["problems"],
        }

    def get(self, request, org_id):
        from audit.models import AuditCheck

        check = AuditCheck.objects.filter(organization=self.org).values().first()
        return Response({"check": self._data(check)})

    def post(self, request, org_id):
        from audit.chain import seal, verify

        seal(self.org.pk)
        return Response({"check": self._data(verify(self.org.pk))})


class RolePreviewView(generics.GenericAPIView):
    """Ansicht als Rolle (access/preview.py): Rollen zur Wahl, beginnen, beenden.

    Geprüft wird mit den eigenen Rechten, nicht mit denen der gerade gewählten Rolle,
    sonst ließe sich die Ansicht in einer Rolle ohne dieses Recht nicht mehr wechseln.
    """

    serializer_class = None

    def _org(self, org_id: int) -> tuple[Organization, set[str]]:
        org = Organization.objects.filter(pk=org_id).first()
        perms = own_permissions_in(self.request.user, org) if org else set()
        if not perms:
            raise NotFound()
        return org, perms

    @staticmethod
    def _roles(org: Organization):
        with tenant_context(org.pk):
            return list(
                Role.objects.filter(organization=org)
                .order_by("position", "name")
                .values("id", "name")
            )

    def _state(self, org: Organization, perms: set[str]) -> dict:
        current = preview.current()
        active = None
        if current and current.org_id == org.pk:
            active = next((r for r in self._roles(org) if r["id"] == current.role_id), None)
        return {
            "available": ROLES_PREVIEW in perms,
            "roles": self._roles(org) if ROLES_PREVIEW in perms else [],
            "active": active,
        }

    def _log(self, org_id: int, role_id: int, before: str, after: str) -> None:
        org = Organization.objects.filter(pk=org_id).first()
        if org is None:
            return
        with tenant_context(org.pk):
            role = Role.objects.filter(pk=role_id, organization=org).first()
        if role is not None:
            record(org, self.request.user, "view", role, {"Ansicht als Rolle": [before, after]})

    def get(self, request, org_id: int):
        org, perms = self._org(org_id)
        return Response(self._state(org, perms))

    @transaction.atomic
    def post(self, request, org_id: int):
        org, perms = self._org(org_id)
        if ROLES_PREVIEW not in perms:
            raise PermissionDenied("Dafür fehlt dir die Berechtigung.")
        role_id = request.data.get("role") if isinstance(request.data, dict) else None
        if not isinstance(role_id, int) or isinstance(role_id, bool):
            raise serializers.ValidationError({"role": "Bitte eine Rolle wählen."})
        with tenant_context(org.pk):
            role = Role.objects.filter(pk=role_id, organization=org).first()
        if role is None:
            raise serializers.ValidationError({"role": "Diese Rolle gibt es hier nicht."})
        previous = preview.current()
        if previous:
            self._log(previous.org_id, previous.role_id, "begonnen", "beendet")
        preview.start(request, org, role)
        record(org, request.user, "view", role, {"Ansicht als Rolle": ["", "begonnen"]})
        return Response(self._state(org, perms))

    @transaction.atomic
    def delete(self, request, org_id: int):
        previous = preview.current()
        if previous:
            self._log(previous.org_id, previous.role_id, "begonnen", "beendet")
        preview.stop(request)
        org = Organization.objects.filter(pk=org_id).first()
        perms = own_permissions_in(request.user, org) if org else set()
        if not perms:
            return Response({"available": False, "roles": [], "active": None})
        return Response(self._state(org, perms))
