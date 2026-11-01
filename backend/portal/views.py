"""API für Zugänge: Mitgliederbereich, Abteilungsbereich, Anmeldelinks.

Drei Bereiche:

- ``/api/orgs/<id>/…``: der Vereinsvorstand richtet Zugänge ein und bearbeitet
  Änderungsmeldungen.
- ``/api/depts/<id>/…``: Abteilungsrollen arbeiten mit den Mitgliedern ihrer
  Abteilung. Die Datenbank arbeitet dabei im Kontext des Vereins (RLS); die
  Anwendung begrenzt zusätzlich auf die Abteilung.
- ``/api/portal/…``: das Mitglied sieht seine eigenen Daten.
"""

from __future__ import annotations

from django.contrib.auth import login
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext, gettext_noop
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import (
    DEPT_ACCESS_MANAGE,
    DEPT_MEMBERS_EDIT,
    DEPT_MEMBERS_VIEW,
    DEPT_ROLES_MANAGE,
    catalog_for,
)
from accounts.models import User
from audit.log import diff, record, snapshot
from core.ratelimit import client_ip, too_many
from core.tenancy import scope_of, set_rls, tenant_context
from members import services as member_services
from members.models import (
    DepartmentMembership,
    DepartmentRoleHolder,
    Gender,
    Membership,
    today,
)
from members.serializers import MemberUpdateSerializer
from members.views import (
    MemberPagination,
    _ClubMixin,
    filter_members,
    member_queryset,
    member_rows,
    update_member,
)
from organizations.imprint import ensure as ensure_imprint
from organizations.models import DepartmentRole
from organizations.serializers import clean_department_permissions
from organizations.terms import department_terms, fill
from organizations.theme import effective_theme
from organizations.tree import UnitTree, subtree_ids

from . import services
from .models import ChangeRequest, LoginLink, PortalAccess, hash_token

# --- Vereinsseite: Zugänge und Änderungsmeldungen ---


class MemberAccessView(_ClubMixin, APIView):
    """Zugang eines Mitglieds: ansehen, einrichten/Link senden, entfernen."""

    def get_membership(self) -> Membership:
        return get_object_or_404(
            Membership.objects.select_related("person"), organization=self.org, pk=self.kwargs["pk"]
        )

    def get(self, request, org_id: int, pk: int):
        membership = self.get_membership()
        access = PortalAccess.objects.filter(membership=membership).select_related("user").first()
        return Response(
            {
                "access": services.access_info(access),
                "portal_enabled": self.org.member_portal_enabled,
                "department_access_enabled": self.org.department_access_enabled,
            }
        )

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        membership = self.get_membership()
        if not (self.org.member_portal_enabled or self.org.department_access_enabled):
            raise serializers.ValidationError(
                fill(
                    "Bitte zuerst unter Einstellungen → Organisation den Mitgliederbereich "
                    "oder den Zugang für {pl} freischalten.",
                    self.org,
                )
            )
        before = PortalAccess.objects.filter(membership=membership).select_related("user").first()
        old_email = before.user.email if before else None
        transfer = bool(request.data.get("transfer"))
        access = services.ensure_access(self.org, membership, request.user, transfer=transfer)
        kind = services.send_access_mail(self.org, access, request.user)
        if old_email and old_email != access.user.email:
            record(
                self.org,
                request.user,
                "update",
                membership,
                {"Zugang übertragen": [old_email, access.user.email]},
                person=membership.person,
            )
        record(
            self.org,
            request.user,
            "update",
            membership,
            {
                "Zugang": [
                    None,
                    f"{'Anmeldelink' if kind == 'link' else 'Passwort-Link'} an "
                    f"{access.user.email} gesendet",
                ]
            },
            person=membership.person,
        )
        return Response({"access": services.access_info(access), "sent": kind})

    def delete(self, request, org_id: int, pk: int):
        membership = self.get_membership()
        access = PortalAccess.objects.filter(membership=membership).select_related("user").first()
        if access is not None:
            email = access.user.email
            access.delete()
            record(
                self.org,
                request.user,
                "update",
                membership,
                {"Zugang": [email, None]},
                person=membership.person,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


def change_request_data(cr: ChangeRequest) -> dict:
    person = cr.membership.person
    return {
        "id": cr.pk,
        "member_id": cr.membership_id,
        "member_name": f"{person.first_name} {person.last_name}",
        "data": cr.data,
        "previous": cr.previous,
        "message": cr.message,
        "status": cr.status,
        "status_label": cr.get_status_display(),
        "response": cr.response,
        "created_at": cr.created_at,
        "decided_at": cr.decided_at,
    }


class ChangeRequestListView(_ClubMixin, APIView):
    def get(self, request, org_id: int):
        qs = ChangeRequest.objects.filter(organization=self.org).select_related(
            "membership__person"
        )
        wanted = request.query_params.get("status", "pending")
        if wanted != "alle":
            qs = qs.filter(status=wanted)
        return Response([change_request_data(cr) for cr in qs[:200]])


class DecisionSerializer(serializers.Serializer):
    accept = serializers.BooleanField()
    response = serializers.CharField(max_length=500, required=False, allow_blank=True)
    # Felder, die seit der Meldung im Verein geändert wurden, trotzdem überschreiben
    overwrite = serializers.BooleanField(required=False, default=False)


def current_values(club, membership) -> dict:
    """Heutige Werte der Felder, die ein Mitglied selbst melden kann."""
    current = dept_member_detail(club, membership, with_access=False)
    return {
        "last_name": current["last_name"],
        "first_name": current["first_name"],
        "birth_date": current["birth_date"].isoformat(),
        "gender": current["gender"],
        **(current["contact"] or {}),
    }


FIELD_LABELS = {
    "last_name": "Nachname",
    "first_name": "Vorname",
    "birth_date": "Geburtsdatum",
    "gender": "Geschlecht",
    "email": "E-Mail",
    "phone": "Telefon",
    "mobile": "Mobil",
    "street": "Straße",
    "postal_code": "PLZ",
    "city": "Ort",
    "country": "Land",
}


def conflicts(club, cr: ChangeRequest) -> list[str]:
    """Felder der Meldung, die der Verein inzwischen anders geändert hat."""
    now = current_values(club, cr.membership)
    return [
        key
        for key, wanted in (cr.data or {}).items()
        if key in (cr.previous or {})
        and (now.get(key) or "") != (cr.previous.get(key) or "")
        and (now.get(key) or "") != (wanted or "")
    ]


def _sync_login_email(cr: ChangeRequest) -> None:
    """Neue E-Mail aus einer angenommenen Meldung auch als Anmelde-E-Mail anbieten.

    Die Freigabe des Vereins ändert das Konto nicht selbst: Das Mitglied bekommt
    einen Bestätigungslink an die neue Adresse, wie beim Ändern im eigenen Konto;
    erst danach gilt sie, und alte Anmeldelinks werden ungültig (Audit ID-N01)."""
    from accounts.models import User
    from accounts.self_service import request_email_change

    new = (cr.data or {}).get("email")
    if not new:
        return
    access = PortalAccess.objects.filter(membership=cr.membership).select_related("user").first()
    # Nur für das Konto, das die Meldung geschickt hat (Zugang inzwischen neu vergeben?)
    if access is None or access.user_id != cr.user_id:
        return
    if access.user.email.lower() == new.lower():
        return
    if User.objects.filter(email__iexact=new).exclude(pk=access.user_id).exists():
        return
    request_email_change(
        access.user,
        User.objects.normalize_email(new).lower(),
        org_name=cr.membership.organization.name,
    )


class ChangeRequestDecisionView(_ClubMixin, APIView):
    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        cr = get_object_or_404(
            ChangeRequest.objects.select_related("membership__person").select_for_update(
                of=("self",)
            ),
            organization=self.org,
            pk=pk,
        )
        if cr.status != ChangeRequest.Status.PENDING:
            raise serializers.ValidationError(gettext("Diese Meldung ist schon bearbeitet."))
        data = DecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        if data.validated_data["accept"]:
            changed = conflicts(self.org, cr)
            if changed and not data.validated_data["overwrite"]:
                # Nicht still überschreiben, was der Verein seit der Meldung geändert hat
                names = ", ".join(FIELD_LABELS.get(k, k) for k in changed)
                return Response(
                    {
                        "detail": gettext(
                            "Seit der Meldung wurde im Verein geändert: {names}. Annehmen "
                            "überschreibt diese Angaben mit der Meldung."
                        ).format(names=names),
                        "conflicts": changed,
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            values = MemberUpdateSerializer(data=cr.data, partial=True)
            values.is_valid(raise_exception=True)
            update_member(self.org, cr.membership, values.validated_data, request.user)
            _sync_login_email(cr)
            cr.status = ChangeRequest.Status.ACCEPTED
        else:
            cr.status = ChangeRequest.Status.REJECTED
        cr.response = data.validated_data.get("response", "")
        cr.decided_by = request.user
        cr.decided_at = timezone.now()
        cr.save()
        from devices.push import notify_membership

        accepted = cr.status == ChangeRequest.Status.ACCEPTED
        notify_membership(
            cr.membership_id,
            gettext_noop("Deine Änderung wurde übernommen")
            if accepted
            else gettext_noop("Deine Änderung wurde abgelehnt"),
            cr.response or self.org.name,
        )
        return Response(change_request_data(cr))


# --- Abteilungsbereich ---


class DepartmentScopedMixin:
    """API-Ansicht in einer Abteilung (URL-Parameter ``dept_id``)."""

    read_permission: str | None = DEPT_MEMBERS_VIEW
    write_permission: str | None = DEPT_MEMBERS_EDIT

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        ctx = services.department_contexts(request.user).get(int(kwargs["dept_id"]))
        if ctx is None:
            raise NotFound()
        needed = (
            self.read_permission
            if request.method in ("GET", "HEAD", "OPTIONS")
            else self.write_permission
        )
        if needed and needed not in ctx.permissions:
            raise PermissionDenied(gettext("Dafür fehlt dir die Berechtigung."))
        self.ctx = ctx
        self.dept = ctx.department
        self.org = ctx.club
        self.dept_permissions = ctx.permissions
        set_rls(self.org.pk, request.user.pk, scope_id=scope_of(self.org.pk))

    def dept_members(self):
        on = today()
        in_dept = DepartmentMembership.objects.filter(
            membership=OuterRef("pk"), department_id__in=subtree_ids(self.dept), valid_from__lte=on
        ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
        return member_queryset(self.org).filter(Exists(in_dept), is_current=True)

    def get_member(self, pk: int) -> Membership:
        membership = self.dept_members().filter(pk=pk).select_related("person").first()
        if membership is None:
            raise NotFound()
        return membership


def department_summary(ctx: services.DepartmentContext) -> dict:
    club = ctx.club
    return {
        "id": ctx.department.pk,
        "name": ctx.department.name,
        "display_name": ctx.department.display_name,
        "club_id": club.pk,
        "club_name": club.name,
        "club_display_name": club.display_name,
        # Bezeichnung dieser Einheit: Vorgabe der direkt übergeordneten Einheit
        "label": ctx.department.parent.department_label,
        "terms": department_terms(ctx.department.parent),
        "path": UnitTree.of(club.pk).path(ctx.department.pk),
        "date_precision": ctx.department.effective_date_precision,
        "permissions": sorted(ctx.permissions),
        "theme": effective_theme(ctx.department.ancestors()),
        "events_enabled": "events" in (club.enabled_modules or []),
        "imprint_key": ensure_imprint(ctx.department).public_key,
    }


class DepartmentInfoView(DepartmentScopedMixin, APIView):
    read_permission = None

    def get(self, request, dept_id: int):
        return Response(department_summary(self.ctx))


class DepartmentMemberListView(DepartmentScopedMixin, APIView):
    def get(self, request, dept_id: int):
        params = request.query_params.copy()
        params["status"] = "alle"  # schon auf aktuelle Mitglieder begrenzt
        qs = filter_members(self.dept_members(), params, self.org)
        paginator = MemberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(member_rows(page, self.org))


def dept_member_detail(org, membership: Membership, with_access: bool) -> dict:
    person = membership.person
    contact = member_services.contact_for(person, org)
    current_type = membership.current_type()
    on = today()
    departments = (
        DepartmentMembership.objects.filter(membership=membership, valid_from__lte=on)
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
        .select_related("department")
    )
    first = membership.periods.order_by("entry_date").first()
    data = {
        "id": membership.pk,
        "last_name": person.last_name,
        "first_name": person.first_name,
        "birth_date": person.birth_date,
        "gender": person.gender,
        "club_number": membership.club_number,
        "member_type": current_type.member_type.name if current_type else None,
        "entry_date": first.entry_date if first else None,
        "departments": [d.department.display_name for d in departments],
        "contact": (
            {f: getattr(contact, f) for f in member_services.CONTACT_FIELDS} if contact else None
        ),
    }
    if with_access:
        access = PortalAccess.objects.filter(membership=membership).select_related("user").first()
        data["access"] = services.access_info(access)
    return data


class DepartmentMemberDetailView(DepartmentScopedMixin, APIView):
    def get(self, request, dept_id: int, pk: int):
        membership = self.get_member(pk)
        return Response(
            dept_member_detail(self.org, membership, DEPT_ACCESS_MANAGE in self.dept_permissions)
        )

    @transaction.atomic
    def patch(self, request, dept_id: int, pk: int):
        membership = self.get_member(pk)
        data = MemberUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("club_number", None)  # Vereinsnummer vergibt der Verein
        update_member(self.org, membership, values, request.user)
        return Response(
            dept_member_detail(self.org, membership, DEPT_ACCESS_MANAGE in self.dept_permissions)
        )


class DepartmentMemberAccessView(DepartmentScopedMixin, APIView):
    read_permission = DEPT_ACCESS_MANAGE
    write_permission = DEPT_ACCESS_MANAGE

    @transaction.atomic
    def post(self, request, dept_id: int, pk: int):
        membership = self.get_member(pk)
        before = PortalAccess.objects.filter(membership=membership).select_related("user").first()
        old_email = before.user.email if before else None
        transfer = bool(request.data.get("transfer"))
        access = services.ensure_access(self.org, membership, request.user, transfer=transfer)
        kind = services.send_access_mail(self.org, access, request.user)
        changes = {"Zugang": [None, f"Link an {access.user.email} gesendet ({self.dept.name})"]}
        if old_email and old_email != access.user.email:
            changes["Zugang übertragen"] = [old_email, access.user.email]
        record(self.org, request.user, "update", membership, changes, person=membership.person)
        return Response({"access": services.access_info(access), "sent": kind})

    def delete(self, request, dept_id: int, pk: int):
        membership = self.get_member(pk)
        PortalAccess.objects.filter(membership=membership).delete()
        record(
            self.org,
            request.user,
            "update",
            membership,
            {"Zugang": ["vorhanden", None]},
            person=membership.person,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeptRoleSerializer(serializers.ModelSerializer):
    permissions = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True
    )
    holder_count = serializers.SerializerMethodField()

    class Meta:
        model = DepartmentRole
        fields = ["id", "name", "permissions", "holder_count"]

    def get_holder_count(self, obj) -> int:
        on = today()
        return (
            obj.holders.filter(valid_from__lte=on)
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
            .count()
        )

    def validate_permissions(self, value):
        return clean_department_permissions(value)

    def validate_name(self, value):
        dept = self.context["dept"]
        qs = DepartmentRole.objects.filter(department=dept, name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(gettext("Diese Rolle gibt es schon."))
        return value


class DepartmentRolesView(DepartmentScopedMixin, APIView):
    read_permission = DEPT_ROLES_MANAGE
    write_permission = DEPT_ROLES_MANAGE

    def get(self, request, dept_id: int):
        roles = DepartmentRole.objects.filter(department=self.dept)
        return Response(
            {
                "roles": DeptRoleSerializer(roles, many=True).data,
                "catalog": catalog_for("department"),
            }
        )

    def post(self, request, dept_id: int):
        data = DeptRoleSerializer(data=request.data, context={"dept": self.dept})
        data.is_valid(raise_exception=True)
        role = data.save(department=self.dept, organization=self.org)
        record(self.org, request.user, "create", role, diff({}, snapshot(role)))
        return Response(DeptRoleSerializer(role).data, status=status.HTTP_201_CREATED)


class DepartmentRoleOrderView(DepartmentScopedMixin, APIView):
    """POST: Reihenfolge der Rollen der Untereinheit (per Ziehen)."""

    read_permission = DEPT_ROLES_MANAGE
    write_permission = DEPT_ROLES_MANAGE

    def post(self, request, dept_id: int):
        from core.reorder import reorder_response

        return reorder_response(
            request,
            self.org,
            DepartmentRole.objects.filter(department=self.dept),
            "position",
            also=("website_position",),
        )


class DepartmentRoleDetailView(DepartmentScopedMixin, APIView):
    read_permission = DEPT_ROLES_MANAGE
    write_permission = DEPT_ROLES_MANAGE

    def get_role(self, pk: int) -> DepartmentRole:
        return get_object_or_404(DepartmentRole, department=self.dept, pk=pk)

    def _keeps_own_admin(self, role: DepartmentRole, new_perms: list[str] | None) -> bool:
        """Verhindert, dass man sich die Rollenverwaltung selbst entzieht.

        Läuft in der Transaktion der Änderung; gleichzeitige Änderungen desselben
        Benutzers warten aufeinander (Gesamtaudit 31.10.b, AT-V05)."""
        User.objects.select_for_update().filter(pk=self.request.user.pk).values_list("pk").first()
        # Nur heute wirksame Rollen: eine erst künftig beginnende ersetzt die heutige
        # nicht (Audit 29.10. ID-F01)
        own_roles = DepartmentRoleHolder.objects.filter(
            membership_id=self.ctx.membership_id,
            role__department=self.dept,
            valid_from__lte=today(),
        ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today()))
        others = [
            h.role
            for h in own_roles.select_related("role")
            if h.role_id != role.pk and DEPT_ROLES_MANAGE in (h.role.permissions or [])
        ]
        holds = own_roles.filter(role=role).exists()
        if not holds or others:
            return True
        return new_perms is not None and DEPT_ROLES_MANAGE in new_perms

    @transaction.atomic
    def patch(self, request, dept_id: int, pk: int):
        role = self.get_role(pk)
        data = DeptRoleSerializer(
            role, data=request.data, partial=True, context={"dept": self.dept}
        )
        data.is_valid(raise_exception=True)
        new_perms = data.validated_data.get("permissions", role.permissions)
        if not self._keeps_own_admin(role, new_perms):
            raise serializers.ValidationError(
                gettext("Du kannst dir die Rollenverwaltung nicht selbst entziehen.")
            )
        before = snapshot(role)
        role = data.save()
        changes = diff(before, snapshot(role))
        if changes:
            record(self.org, request.user, "update", role, changes)
        return Response(DeptRoleSerializer(role).data)

    @transaction.atomic
    def delete(self, request, dept_id: int, pk: int):
        role = self.get_role(pk)
        if not self._keeps_own_admin(role, None):
            raise serializers.ValidationError(
                gettext("Du kannst dir die Rollenverwaltung nicht selbst entziehen.")
            )
        with transaction.atomic():
            member_services.remove_role_holders(self.org, request.user, role)
            record(self.org, request.user, "delete", role, diff(snapshot(role), {}))
            role.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class HolderSerializer(serializers.Serializer):
    member = serializers.IntegerField()
    role = serializers.IntegerField()
    valid_from = serializers.DateField(required=False)


def holder_data(h: DepartmentRoleHolder) -> dict:
    person = h.membership.person
    return {
        "id": h.pk,
        "member_id": h.membership_id,
        "member_name": f"{person.first_name} {person.last_name}",
        "role": h.role_id,
        "role_name": h.role.name,
        "valid_from": h.valid_from,
        "valid_until": h.valid_until,
    }


class DepartmentHoldersView(DepartmentScopedMixin, APIView):
    read_permission = DEPT_ROLES_MANAGE
    write_permission = DEPT_ROLES_MANAGE

    def get(self, request, dept_id: int):
        on = today()
        holders = (
            DepartmentRoleHolder.objects.filter(role__department=self.dept)
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
            .select_related("membership__person", "role")
            .order_by("role__position", "role__name", "membership__person__last_name")
        )
        return Response([holder_data(h) for h in holders])

    @transaction.atomic
    def post(self, request, dept_id: int):
        data = HolderSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        membership = self.get_member(data.validated_data["member"])
        role = get_object_or_404(
            DepartmentRole, department=self.dept, pk=data.validated_data["role"]
        )
        holder = DepartmentRoleHolder.objects.create(
            organization=self.org,
            membership=membership,
            role=role,
            valid_from=data.validated_data.get("valid_from") or today(),
        )
        record(
            self.org,
            request.user,
            "create",
            holder,
            {"Abteilungsrolle": [None, role.name]},
            person=membership.person,
        )
        return Response(holder_data(holder), status=status.HTTP_201_CREATED)


class DepartmentHolderEndView(DepartmentScopedMixin, APIView):
    read_permission = DEPT_ROLES_MANAGE
    write_permission = DEPT_ROLES_MANAGE

    def post(self, request, dept_id: int, pk: int):
        holder = get_object_or_404(
            DepartmentRoleHolder.objects.select_related("membership__person", "role"),
            role__department=self.dept,
            pk=pk,
        )
        if holder.membership_id == self.ctx.membership_id and DEPT_ROLES_MANAGE in (
            holder.role.permissions or []
        ):
            raise serializers.ValidationError(
                gettext("Du kannst dir die Rollenverwaltung nicht selbst entziehen.")
            )
        end = today()
        holder.valid_until = max(end, holder.valid_from)
        holder.save(update_fields=["valid_until"])
        record(
            self.org,
            request.user,
            "update",
            holder,
            {"bis": [None, holder.valid_until.isoformat()]},
            person=holder.membership.person,
        )
        return Response(holder_data(holder))


# --- Mitgliederbereich ---


def _portal_access(user, access_id: int) -> PortalAccess:
    access = next((a for a in services.portal_accesses(user) if a.pk == int(access_id)), None)
    if access is None:
        raise NotFound()
    return access


def portal_summary(access: PortalAccess) -> dict:
    club = access.organization
    with tenant_context(club.pk, access.user_id):
        person = access.membership.person
        return {
            "id": access.pk,
            "club_id": club.pk,
            "club_name": club.name,
            "club_display_name": club.display_name,
            "first_name": person.first_name,
            "last_name": person.last_name,
            "date_precision": club.date_precision,
            "theme": effective_theme(club.ancestors()),
            "events_enabled": "events" in (club.enabled_modules or []),
            "entries_enabled": "entries" in (club.enabled_modules or []),
            "terms": department_terms(club),
            "imprint_key": ensure_imprint(club).public_key,
        }


@extend_schema(responses=dict)
class MyContextsView(APIView):
    """Abteilungen mit Rechten und Mitgliedschaften im Mitgliederbereich."""

    def get(self, request):
        return Response(
            {
                "departments": [
                    department_summary(ctx)
                    for ctx in sorted(
                        services.department_contexts(request.user).values(),
                        key=lambda c: (c.club.display_name, c.department.display_name),
                    )
                ],
                "portal": [portal_summary(a) for a in services.portal_accesses(request.user)],
            }
        )


class PortalDetailView(APIView):
    def get(self, request, access_id: int):
        access = _portal_access(request.user, access_id)
        club = access.organization
        with tenant_context(club.pk, request.user.pk):
            membership = (
                Membership.objects.select_related("person").filter(pk=access.membership_id).first()
            )
            if membership is None:
                raise NotFound()
            data = dept_member_detail(club, membership, with_access=False)
            current = membership.current_period()
            data["status"] = "active" if current else "former"
            data["contact_changes_need_approval"] = club.contact_changes_need_approval
            data["club"] = {
                "name": club.name,
                "street": club.street,
                "postal_code": club.postal_code,
                "city": club.city,
                "email": club.contact_email,
                "phone": club.contact_phone,
                "website": club.website,
            }
            data["change_requests"] = [
                change_request_data(cr)
                for cr in ChangeRequest.objects.filter(membership=membership).select_related(
                    "membership__person"
                )[:20]
            ]
        return Response(data)


class PortalChangeSerializer(serializers.Serializer):
    last_name = serializers.CharField(max_length=100, required=False)
    first_name = serializers.CharField(max_length=100, required=False)
    birth_date = serializers.DateField(required=False)
    gender = serializers.ChoiceField(choices=Gender.choices, required=False, allow_blank=True)
    email = serializers.EmailField(required=False)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=50)
    street = serializers.CharField(max_length=200, required=False)
    postal_code = serializers.CharField(max_length=10, required=False)
    city = serializers.CharField(max_length=100, required=False)
    country = serializers.CharField(max_length=100, required=False)
    message = serializers.CharField(max_length=500, required=False, allow_blank=True)


class PortalChangeRequestView(APIView):
    @transaction.atomic
    def post(self, request, access_id: int):
        access = _portal_access(request.user, access_id)
        club = access.organization
        data = PortalChangeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        message = values.pop("message", "")
        with tenant_context(club.pk, request.user.pk):
            membership = Membership.objects.select_related("person").get(pk=access.membership_id)
            previous_values = current_values(club, membership)
            changed = {
                k: (v.isoformat() if hasattr(v, "isoformat") else v)
                for k, v in values.items()
                if (v.isoformat() if hasattr(v, "isoformat") else v) != previous_values.get(k)
            }
            if not changed:
                raise serializers.ValidationError(gettext("Es wurde nichts geändert."))
            direct = (
                {}
                if club.contact_changes_need_approval
                else {k: v for k, v in changed.items() if k in services.DIRECT_FIELDS}
            )
            pending = {k: v for k, v in changed.items() if k not in direct}
            if direct:
                # Kontaktdaten gelten sofort; update_member schreibt das Protokoll.
                update_member(
                    club,
                    membership,
                    {k: values[k] for k in direct},
                    request.user,
                )
            cr = None
            if pending:
                if ChangeRequest.objects.filter(
                    membership=membership, status=ChangeRequest.Status.PENDING
                ).exists():
                    raise serializers.ValidationError(
                        fill(
                            "Es gibt schon eine offene Meldung. Bitte warten, bis {e_nom} sie ",
                            club,
                        )
                        + "bearbeitet hat."
                    )
                cr = ChangeRequest.objects.create(
                    organization=club,
                    membership=membership,
                    user=request.user,
                    data=pending,
                    previous={k: previous_values.get(k) for k in pending},
                    message=message,
                )
                record(
                    club,
                    request.user,
                    "create",
                    cr,
                    {k: [previous_values.get(k), v] for k, v in pending.items()},
                    person=membership.person,
                )
            return Response(
                {
                    "applied": direct,
                    "request": change_request_data(cr) if cr else None,
                },
                status=status.HTTP_201_CREATED if cr else status.HTTP_200_OK,
            )


# --- Anmeldelinks (ohne Anmeldung erreichbar) ---

RATE = (10, 15 * 60)  # 10 Versuche je 15 Minuten und IP


def _rate_limited(request, kind: str) -> bool:
    return too_many(f"login-link:{kind}:{client_ip(request)}", RATE[0], RATE[1])


class RequestLinkSerializer(serializers.Serializer):
    email = serializers.EmailField()


class LoginLinkRequestView(APIView):
    """Anmeldelink per E-Mail anfordern. Antwortet immer gleich (keine Kontosuche)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        if _rate_limited(request, "request"):
            return Response(
                {"detail": gettext("Zu viele Versuche. Bitte später erneut.")}, status=429
            )
        data = RequestLinkSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=data.validated_data["email"]).first()
        if user is not None:
            set_rls(None, user.pk)
            if services.portal_accesses(user) and services.link_login_allowed(user):
                url = services.create_login_link(user)
                from core.i18n import language_of, user_language
                from outbox import mail

                with language_of(user):
                    subject = gettext("Ihr Anmeldelink für HUBIplan")
                    body = (
                        gettext("Guten Tag,")
                        + "\n\n"
                        + gettext(
                            "mit diesem Link melden Sie sich im Mitgliederbereich an "
                            "(gültig {days} Tage, einmal nutzbar):"
                        ).format(days=services.LINK_DAYS)
                        + f"\n\n{url}\n\n"
                        + gettext(
                            "Falls Sie den Link nicht angefordert haben, können Sie diese Mail "
                            "ignorieren."
                        )
                        + "\n"
                    )
                mail.send(
                    user.email,
                    subject,
                    body,
                    kind="anmeldelink",
                    fail_silently=True,
                    language=user_language(user),
                )
            set_rls(None, None)
        return Response(
            {
                "detail": gettext(
                    "Wenn zu dieser Adresse ein Mitgliederzugang besteht, ist ein "
                    "Anmeldelink unterwegs."
                )
            }
        )


class LoginLinkUseView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request, token: str):
        # Ohne Anmeldeklassen prüft DRF kein CSRF. Hier ausdrücklich, damit keine fremde
        # Seite einen Browser mit einem eigenen Link in ein anderes Konto einloggt.
        SessionAuthentication().enforce_csrf(request)
        if _rate_limited(request, "use"):
            return Response(
                {"detail": gettext("Zu viele Versuche. Bitte später erneut.")}, status=429
            )
        link = (
            LoginLink.objects.select_related("user")
            .select_for_update(of=("self",))
            .filter(token_hash=hash_token(token))
            .first()
        )
        if link is None or not link.is_open:
            raise NotFound(
                gettext("Der Link ist ungültig oder abgelaufen. Bitte fordern Sie einen neuen an.")
            )
        user = link.user
        set_rls(None, user.pk)
        if not services.link_login_allowed(user):
            raise PermissionDenied(
                gettext("Für dieses Konto ist die Anmeldung nur mit Passwort möglich.")
            )
        link.used_at = timezone.now()
        link.save(update_fields=["used_at"])
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        from peering.sso import record

        # Anmeldeweg vermerken (für Anmeldebestätigungen an andere Instanzen)
        record(request, user, "link")
        return Response({"id": user.pk, "email": user.email, "display": user.get_full_name()})
