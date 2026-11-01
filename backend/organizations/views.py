from __future__ import annotations

from django.db import transaction
from django.db.models import Count, ProtectedError, RestrictedError
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework import generics, mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import (
    CLUBS_MANAGE,
    DEFAULT_MODULES,
    ORG_EDIT,
    ROLES_MANAGE,
    THEME_EDIT,
    WEBSITE_CONTENT,
    WEBSITE_MANAGE,
    codes_for,
)
from access.models import Role, RoleAssignment
from access.permissions import is_platform_admin
from accounts.models import User
from audit.log import diff, record, snapshot
from core.api_base import AuditMixin, OrgScopedMixin
from core.reorder import reorder_response
from core.tenancy import rls_bypass, set_rls, tenant_context
from members import services as member_services

from . import homepage_preview
from .models import Department, DepartmentRole, Organization, PlatformSettings
from .serializers import (
    DepartmentRoleSerializer,
    DepartmentSerializer,
    FederationClubSerializer,
    HomepageImageSerializer,
    LogoSerializer,
    OrganizationSerializer,
    PlatformOrganizationSerializer,
    PlatformSettingsSerializer,
    ThemeSerializer,
    current_members_q,
)
from .terms import fill
from .tree import UnitTree

DEFAULT_BOARD_ROLE = "Vorstand"


class OrganizationDetailView(OrgScopedMixin, AuditMixin, generics.RetrieveUpdateAPIView):
    """Stammdaten der Organisation (lesen: alle mit Rolle; ändern: org.edit)."""

    serializer_class = OrganizationSerializer
    write_permission = ORG_EDIT
    http_method_names = ["get", "patch", "options", "head"]

    def get_object(self):
        return self.org


class ThemeView(OrgScopedMixin, AuditMixin, generics.RetrieveUpdateAPIView):
    """Farben der Organisation; leere Werte erben von der übergeordneten Ebene."""

    serializer_class = ThemeSerializer
    write_permission = THEME_EDIT
    http_method_names = ["get", "patch", "options", "head"]

    def get_object(self):
        return self.org


class _LogoMixin:
    parser_classes = [MultiPartParser, FormParser]

    def get_logo_owner(self):
        raise NotImplementedError

    def post(self, request, *args, **kwargs):
        owner = self.get_logo_owner()
        serializer = LogoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before = snapshot(owner)
        if owner.logo:
            owner.logo.delete(save=False)
        owner.logo = serializer.validated_data["logo"]
        owner.save()
        record(self.org, request.user, "update", owner, diff(before, snapshot(owner)))
        return Response({"logo_url": owner.logo.url})

    def delete(self, request, *args, **kwargs):
        owner = self.get_logo_owner()
        if owner.logo:
            before = snapshot(owner)
            owner.logo.delete(save=True)
            record(self.org, request.user, "update", owner, diff(before, snapshot(owner)))
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrganizationLogoView(OrgScopedMixin, _LogoMixin, APIView):
    write_permission = THEME_EDIT

    def get_logo_owner(self):
        return self.org


class DepartmentViewSet(OrgScopedMixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = DepartmentSerializer
    write_permission = ORG_EDIT
    allowed_org_types = (Organization.Type.CLUB,)

    def get_queryset(self):
        return (
            Department.objects.filter(organization=self.org)
            .select_related("organization__parent__parent")
            .prefetch_related("unit_roles__assignments__membership__person")
            .annotate(
                current_member_count=Count(
                    "unit_memberships__membership",
                    filter=current_members_q("unit_memberships__"),
                    distinct=True,
                )
            )
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["org"] = getattr(self, "org", None)
        return ctx

    def list(self, request, *args, **kwargs):
        # Baumreihenfolge: jede Einheit vor ihren Untereinheiten
        units = list(self.filter_queryset(self.get_queryset()))
        tree = UnitTree.of(self.org.pk)
        order = {pk: i for i, pk in enumerate(tree.ordered())}
        units.sort(key=lambda u: order.get(u.pk, len(order)))
        context = {**self.get_serializer_context(), "tree": tree}
        return Response(self.get_serializer_class()(units, many=True, context=context).data)

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}

    def perform_create(self, serializer):
        super().perform_create(serializer)
        ensure_workspace_role(serializer.instance)
        homepage_preview.schedule(serializer.instance)

    @action(detail=False, methods=["post"])
    def reorder(self, request, *args, **kwargs):
        """Reihenfolge der Untereinheiten unter einer Einheit (``parent``; leer: oberste Ebene)."""
        parent = request.data.get("parent") or self.org.pk
        if not isinstance(parent, int):
            raise serializers.ValidationError({"parent": gettext("Unbekannte Einheit.")})
        return reorder_response(
            request,
            self.org,
            Department.objects.filter(organization=self.org, parent_id=parent),
            "sort_order",
        )

    @action(detail=True, methods=["post"])
    def manager(self, request, *args, **kwargs):
        """Ersten Verwalter einrichten: Rolle „Leitung“ mit allen Rechten + Zugang."""
        from members.models import Membership
        from portal.unit_manager import setup_unit_manager

        unit = self.get_object()
        _not_remote(unit)
        member_id = request.data.get("member")
        membership = (
            Membership.objects.filter(organization=self.org, pk=member_id).first()
            if str(member_id).isdigit()
            else None
        )
        if membership is None:
            raise serializers.ValidationError({"member": gettext("Unbekanntes Mitglied.")})
        result = setup_unit_manager(self.org, unit, membership, request.user)
        return Response(
            {
                "email": result.email,
                "role": result.role,
                "workspace_role": result.workspace_role,
                "mail": result.mail,
            }
        )

    def perform_update(self, serializer):
        _not_remote(serializer.instance)
        old_parent = serializer.instance.parent_id
        super().perform_update(serializer)
        unit = serializer.instance
        if unit.parent_id != old_parent:
            # Umgehängt: Bezeichnung nach der Vorgabe der neuen übergeordneten Einheit
            above = Organization.objects.get(pk=unit.parent_id)
            unit.label = above.department_label
            unit.label_plural = above.department_label_plural
            unit.label_gender = above.department_label_gender
            unit.label_genitive = above.department_label_genitive
            unit.label_en = above.department_label_en
            unit.label_plural_en = above.department_label_plural_en
            unit.save(
                update_fields=[
                    "label",
                    "label_plural",
                    "label_gender",
                    "label_genitive",
                    "label_en",
                    "label_plural_en",
                ]
            )
        ensure_workspace_role(unit)
        # Neue Homepage: Vorschaubild einmal im Hintergrund holen
        homepage_preview.schedule(unit)

    @transaction.atomic
    def perform_destroy(self, instance):
        if instance.is_remote:
            raise serializers.ValidationError(
                gettext(
                    "Diese Einheit liegt auf einer anderen Instanz. Zum Entfernen die "
                    "Kopplung unter Verbund lösen."
                )
            )
        if Department.objects.filter(parent=instance).exists():
            raise serializers.ValidationError(
                fill(
                    "{e_Diese} hat noch {pl} und kann deshalb nicht gelöscht werden.",
                    instance,
                )
            )
        from finance.services import finance_records_of

        if what := finance_records_of(instance):
            raise serializers.ValidationError(
                fill(
                    "{e_Diese} hat " + what + " und kann deshalb nicht gelöscht werden "
                    "(Aufbewahrungspflicht). Setze {e_akk} stattdessen auf inaktiv.",
                    instance,
                )
            )
        try:
            # Ohne RLS-Sicht, damit auch Rollen, Konten und Einstellungen im eigenen
            # Arbeitsbereich der Einheit mitgelöscht werden (sonst Fremdschlüsselfehler).
            # Mitglieder, Untereinheiten und Finanzdaten sind oben bzw. per PROTECT geprüft.
            with transaction.atomic(), rls_bypass():
                super().perform_destroy(instance)
        except (ProtectedError, RestrictedError) as exc:
            raise serializers.ValidationError(
                fill(
                    "{e_Diese} hat noch (auch frühere) Mitglieder oder Rolleninhaber und kann "
                    "deshalb nicht gelöscht werden. Setze {e_akk} stattdessen auf inaktiv.",
                    instance,
                )
            ) from exc


def _not_remote(unit) -> None:
    if unit.is_remote:
        raise serializers.ValidationError(
            {
                "detail": gettext(
                    "Diese Einheit liegt auf einer anderen Instanz und pflegt sich dort."
                )
            }
        )


def ensure_workspace_role(unit: Department) -> None:
    """Neuer Arbeitsbereich: eine Vorstandsrolle mit allen Rechten der Untereinheit."""
    if not unit.own_workspace:
        return
    with tenant_context(unit.pk):
        if not Role.objects.filter(organization=unit).exists():
            # Webseite nur, wenn sie für die Untereinheit eingeschaltet ist (siehe unten)
            perms = [c for c in codes_for(unit.type) if c not in (WEBSITE_MANAGE, WEBSITE_CONTENT)]
            Role.objects.create(organization=unit, name=DEFAULT_BOARD_ROLE, permissions=perms)
        if "website" in (unit.enabled_modules or []):
            # Eigene Webseite: wer Rollen verwaltet, darf auch die Webseite pflegen
            for role in Role.objects.filter(organization=unit):
                perms = set(role.permissions or [])
                if ROLES_MANAGE in perms and WEBSITE_MANAGE not in perms:
                    role.permissions = sorted(perms | {WEBSITE_MANAGE, WEBSITE_CONTENT})
                    role.save(update_fields=["permissions"])


class DepartmentLogoView(OrgScopedMixin, _LogoMixin, APIView):
    write_permission = ORG_EDIT
    allowed_org_types = (Organization.Type.CLUB,)

    def get_logo_owner(self):
        unit = get_object_or_404(Department, organization=self.org, pk=self.kwargs["pk"])
        _not_remote(unit)
        return unit


class DepartmentHomepageImageView(OrgScopedMixin, APIView):
    """Eigenes Vorschaubild der Homepage (Ersatz, wenn die Homepage keins liefert).

    POST lädt ein eigenes Bild hoch, das nie automatisch ersetzt wird. DELETE
    entfernt das Bild und holt es neu von der Homepage.
    """

    parser_classes = [MultiPartParser, FormParser]
    write_permission = ORG_EDIT
    allowed_org_types = (Organization.Type.CLUB,)

    def unit(self) -> Department:
        unit = get_object_or_404(Department, organization=self.org, pk=self.kwargs["pk"])
        _not_remote(unit)
        return unit

    def post(self, request, *args, **kwargs):
        unit = self.unit()
        serializer = HomepageImageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before = snapshot(unit)
        if unit.website_image:
            unit.website_image.delete(save=False)
        unit.website_image = serializer.validated_data["image"]
        unit.website_image_custom = True
        unit.save()
        record(self.org, request.user, "update", unit, diff(before, snapshot(unit)))
        return Response({"website_image_url": unit.website_image.url})

    def delete(self, request, *args, **kwargs):
        """Eigenes Bild weg und sofort neu von der Homepage holen (dauert wenige
        Sekunden); die Antwort sagt, warum kein Bild kam."""
        unit = self.unit()
        before = snapshot(unit)
        if unit.website_image:
            unit.website_image.delete(save=False)
        unit.website_image = ""
        unit.website_image_custom = False
        unit.website_image_for = ""
        unit.save()
        reason = homepage_preview.refresh(unit)
        record(self.org, request.user, "update", unit, diff(before, snapshot(unit)))
        return Response(
            {
                "website_image_url": unit.website_image.url if unit.website_image else None,
                "message": reason,
            }
        )


class DepartmentRoleViewSet(OrgScopedMixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = DepartmentRoleSerializer
    write_permission = ORG_EDIT
    allowed_org_types = (Organization.Type.CLUB,)

    def get_queryset(self):
        return (
            DepartmentRole.objects.filter(organization=self.org)
            .select_related("department")
            .prefetch_related("assignments__membership__person")
        )

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["org"] = getattr(self, "org", None)
        return ctx

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}

    @action(detail=False, methods=["post"])
    def reorder(self, request, *args, **kwargs):
        """Reihenfolge der Rollen einer Untereinheit (``department``)."""
        department = request.data.get("department")
        if not isinstance(department, int):
            raise serializers.ValidationError({"department": gettext("Unbekannte Einheit.")})
        return reorder_response(
            request,
            self.org,
            DepartmentRole.objects.filter(organization=self.org, department_id=department),
            "position",
            also=("website_position",),
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        # Die Rolle verschwindet auch bei ihren (früheren) Inhabern
        member_services.remove_role_holders(self.org, self.request.user, instance)
        super().perform_destroy(instance)


class FederationClubViewSet(
    OrgScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Dachverband: seine Vereine auflisten, Stammdaten ändern, (de)aktivieren.

    Gelöscht wird ein Verein nie, nur deaktiviert – seine Daten bleiben erhalten.
    """

    serializer_class = FederationClubSerializer
    read_permission = CLUBS_MANAGE
    write_permission = CLUBS_MANAGE
    allowed_org_types = (Organization.Type.FEDERATION,)
    http_method_names = ["get", "patch", "options", "head"]

    def get_queryset(self):
        return Organization.objects.filter(parent=self.org, type=Organization.Type.CLUB).order_by(
            "name"
        )

    def perform_update(self, serializer):
        if serializer.instance.is_remote:
            raise serializers.ValidationError(
                {
                    "detail": gettext(
                        "Diese Einheit liegt auf einer anderen Instanz und pflegt sich dort."
                    )
                }
            )
        before = snapshot(serializer.instance)
        club = serializer.save()
        changes = diff(before, snapshot(club))
        if changes:
            changes["geändert durch Dachverband"] = [None, self.org.name]
            record(self.org, self.request.user, "update", club, changes)
            record(club, self.request.user, "update", club, changes)


# --- Plattformbereich ---


class IsPlatformAdmin(BasePermission):
    message = "Nur für die Plattform-Administration."

    def has_permission(self, request, view) -> bool:
        if not request.user.is_authenticated or not is_platform_admin(request.user):
            return False
        set_rls(Organization.platform().pk, request.user.pk)
        return True


class PlatformOrganizationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Dachverbände und Vereine anlegen, ändern und deaktivieren (kein Löschen)."""

    serializer_class = PlatformOrganizationSerializer
    permission_classes = [IsPlatformAdmin]
    http_method_names = ["get", "post", "patch", "options", "head"]

    def get_queryset(self):
        return (
            Organization.objects.exclude(type=Organization.Type.PLATFORM)
            .select_related("parent")
            .order_by("type", "name")
        )

    @transaction.atomic
    def perform_create(self, serializer):
        org = serializer.save(
            enabled_modules=serializer.validated_data.get("enabled_modules", list(DEFAULT_MODULES))
        )
        # Jede neue Organisation bekommt eine Vorstandsrolle mit allen Rechten.
        with tenant_context(org.pk):
            Role.objects.create(
                organization=org,
                name=DEFAULT_BOARD_ROLE,
                description="Vollzugriff auf die Organisation",
                permissions=codes_for(org.type),
            )
        record(org, self.request.user, "create", org, diff({}, snapshot(org)))

    def perform_update(self, serializer):
        if serializer.instance.is_remote:
            raise serializers.ValidationError(
                {"detail": gettext("Diese Einheit liegt auf einer anderen Instanz (Verbund).")}
            )
        before = snapshot(serializer.instance)
        org = serializer.save()
        changes = diff(before, snapshot(org))
        if changes:
            record(org, self.request.user, "update", org, changes)


class BoardMemberSerializer(serializers.Serializer):
    email = serializers.EmailField()


def _tell_board(org, user, role_name: str, actor) -> None:
    """Fachfrage 16 (31.10.b): vergibt die Plattform eine Rolle in einer Einheit, erfährt es
    deren Vorstand sofort (alle mit Rollenverwaltung dort, außer der neuen Person)."""
    from access.catalog import ROLES_MANAGE
    from core.alarm import send_alert
    from outbox import mail

    with tenant_context(org.pk):
        holders = (
            RoleAssignment.objects.active()
            .filter(organization=org)
            .exclude(user=user)
            .select_related("role", "user")
        )
        to = sorted(
            {a.user.email for a in holders if a.user and ROLES_MANAGE in a.role.permissions}
        )
    text = (
        f"Guten Tag,\n\ndie Plattformverwaltung ({actor.email}) hat bei {org.name} die Rolle "
        f"„{role_name}“ an {user.email} vergeben.\n\nWenn das nicht abgesprochen war, entzieht "
        "die Rolle bitte unter „Rollen“ und meldet euch beim Betreiber. Der Eintrag steht im "
        "Protokoll.\n"
    )
    subject = f"Rolle bei {org.name} durch die Plattform vergeben"
    if to:
        transaction.on_commit(lambda: mail.send(to, subject, text, organization=org, kind="zugang"))
    transaction.on_commit(
        lambda: send_alert(
            "Rolle durch die Plattform vergeben",
            [f"Einheit: {org.name}", f"Rolle: {role_name} an {user.email}", f"Von: {actor.email}"],
        )
    )


class PlatformBoardView(APIView):
    """Ersten Vorstand einer Organisation festlegen: Benutzer bekommt die Rolle „Vorstand“."""

    permission_classes = [IsPlatformAdmin]

    @transaction.atomic
    def post(self, request, pk: int):
        org = get_object_or_404(
            Organization.objects.exclude(type=Organization.Type.PLATFORM), pk=pk
        )
        data = BoardMemberSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data["email"].lower()
        user, created = User.objects.get_or_create(email=email)
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        with tenant_context(org.pk):
            role, _ = Role.objects.get_or_create(
                organization=org,
                name=DEFAULT_BOARD_ROLE,
                defaults={"permissions": codes_for(org.type)},
            )
            assignment = RoleAssignment.objects.create(organization=org, role=role, user=user)
        record(
            org,
            request.user,
            "create",
            assignment,
            {**diff({}, snapshot(assignment)), "vergeben durch": [None, "Plattformverwaltung"]},
        )
        _tell_board(org, user, role.name, request.user)
        invited = False
        if created:
            from accounts.invitations import send_invitation

            invited = send_invitation(user, org, role.name)
        return Response(
            {
                "email": user.email,
                "role": role.name,
                "invited": invited,
                "new_account": created,
            },
            status=status.HTTP_201_CREATED,
        )


class PlatformSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = PlatformSettingsSerializer
    permission_classes = [IsPlatformAdmin]
    http_method_names = ["get", "patch", "options", "head"]

    def get_object(self):
        return PlatformSettings.load()

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        obj = serializer.save()
        changes = diff(before, snapshot(obj))
        if changes:
            record(Organization.platform(), self.request.user, "update", obj, changes)
