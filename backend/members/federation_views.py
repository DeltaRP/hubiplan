"""Dachverbandsansicht über alle angeschlossenen Vereine (Meilenstein 6).

Nur wenn die Plattform den Zugriff für diesen Dachverband freigeschaltet hat
(„nur lesen“ oder „lesen und ändern“). Jeder Zugriff wird protokolliert – im
Dachverband und bei Einzelansichten zusätzlich im betroffenen Verein.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import MEMBERS_EDIT, MEMBERS_VIEW
from audit.log import diff, record, snapshot
from core.api_base import OrgScopedMixin

from . import services
from .models import Membership, MembershipPeriod, MemberTypeAssignment, today
from .serializers import MemberUpdateSerializer, member_detail
from .views import MemberPagination, member_rows


class _FederationMixin(OrgScopedMixin):
    allowed_org_types = ("federation",)
    read_permission = MEMBERS_VIEW
    write_permission = MEMBERS_EDIT

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        access = self.org.federation_member_access
        if access == "none":
            raise PermissionDenied(
                gettext("Die Plattform hat den Zugriff auf Mitgliedsdaten nicht freigegeben.")
            )
        if request.method not in ("GET", "HEAD", "OPTIONS") and access != "write":
            raise PermissionDenied(gettext("Der Dachverband darf Mitgliedsdaten nur lesen."))


def federation_queryset(federation):
    on = today()
    open_period = MembershipPeriod.objects.filter(
        membership=OuterRef("pk"), entry_date__lte=on
    ).filter(Q(exit_date__isnull=True) | Q(exit_date__gte=on))
    current_type = MemberTypeAssignment.objects.filter(
        membership=OuterRef("pk"), valid_from__lte=on
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
    first_entry = MembershipPeriod.objects.filter(membership=OuterRef("pk")).order_by("entry_date")
    last_exit = MembershipPeriod.objects.filter(membership=OuterRef("pk")).order_by("-entry_date")
    return (
        Membership.objects.filter(scope=federation)
        .select_related("person", "person__federation", "organization")
        .annotate(
            is_current=Exists(open_period),
            current_type_id=Subquery(current_type.values("member_type_id")[:1]),
            current_type_name=Subquery(current_type.values("member_type__name")[:1]),
            current_type_reported=Subquery(current_type.values("member_type__reported")[:1]),
            current_type_active=Subquery(current_type.values("member_type__active")[:1]),
            entry_date=Subquery(first_entry.values("entry_date")[:1]),
            exit_date=Subquery(last_exit.values("exit_date")[:1]),
        )
    )


def filter_federation(qs, params):
    search = (params.get("suche") or "").strip()
    for word in search.split():
        q = Q(person__last_name__icontains=word) | Q(person__first_name__icontains=word)
        if word.isdigit():
            q |= Q(person__federation__member_number=int(word))
        qs = qs.filter(q)
    status = params.get("status", "aktiv")
    if status == "aktiv":
        qs = qs.filter(is_current=True)
    elif status == "ehemalig":
        qs = qs.filter(is_current=False)
    if params.get("verein"):
        qs = qs.filter(organization_id=params["verein"])
    if params.get("gemeldet") == "1":
        qs = qs.filter(current_type_reported=True)
    if params.get("aktiv") == "1":
        qs = qs.filter(current_type_active=True)
    title = str(params.get("ehrentitel") or "")
    if title == "mit" or title.isdigit():
        from .honorary import current_awards

        # nur Ehrungen des Dachverbands (Verbandsbereich der Mitgliedschaft)
        awards = current_awards().filter(
            person_id=OuterRef("person_id"), organization_id=OuterRef("scope_id")
        )
        if title.isdigit():
            awards = awards.filter(title_id=int(title))
        qs = qs.filter(Exists(awards))
    ordering = {
        "name": ("person__last_name", "person__first_name"),
        "-name": ("-person__last_name", "-person__first_name"),
        "verein": ("organization__name", "person__last_name"),
        "nummer": ("person__federation__member_number",),
    }.get(params.get("sortierung", "name"), ("person__last_name", "person__first_name"))
    return qs.order_by(*ordering, "pk")


def federation_rows(memberships, full_names: bool = False) -> list[dict]:
    """Zeilen je Mitgliedschaft; Kontakt/Abteilungen aus Sicht des jeweiligen Vereins."""
    by_club: dict[int, list] = {}
    for m in memberships:
        by_club.setdefault(m.organization_id, []).append(m)
    rows_by_id = {}
    for items in by_club.values():
        club = items[0].organization
        for row in member_rows(items, club, full_names):
            row["club"] = club.name if full_names else club.display_name
            row["club_id"] = club.pk
            rows_by_id[row["id"]] = row
    return [rows_by_id[m.pk] for m in memberships]


class FederationMemberListView(_FederationMixin, APIView):
    def get(self, request, org_id: int):
        qs = filter_federation(federation_queryset(self.org), request.query_params)
        paginator = MemberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        record(
            self.org,
            request.user,
            "view",
            self.org,
            {"Mitgliederliste": [None, dict(request.query_params.items())]},
        )
        return paginator.get_paginated_response(federation_rows(page))


class FederationClubsView(_FederationMixin, APIView):
    def get(self, request, org_id: int):
        return Response(
            [
                {"id": c.pk, "name": c.display_name}
                for c in self.org.children.filter(type="club", is_active=True)
            ]
        )


class FederationMemberDetailView(_FederationMixin, APIView):
    def membership(self) -> Membership:
        return get_object_or_404(
            Membership.objects.select_related("person", "organization"),
            scope=self.org,
            pk=self.kwargs["pk"],
        )

    def get(self, request, org_id: int, pk: int):
        m = self.membership()
        data = member_detail(m, m.organization)
        data["club"] = m.organization.name
        # Ferne Vereine (Verbund): ändern nur dort, hier höchstens vorschlagen
        data["remote"] = m.organization.is_remote
        data["readonly"] = (
            self.org.federation_member_access != "write"
            or MEMBERS_EDIT not in self.org_permissions
            or m.organization.is_remote
        )
        # Zugriff protokollieren: im Dachverband und im betroffenen Verein
        changes = {"Zugriff durch Dachverband": [None, self.org.name]}
        record(self.org, request.user, "view", m, changes, person=m.person)
        record(m.organization, request.user, "view", m, changes, person=m.person)
        return Response(data)

    @transaction.atomic
    def patch(self, request, org_id: int, pk: int):
        m = self.membership()
        if m.organization.is_remote:
            raise PermissionDenied(
                gettext(
                    "Die Person gehört zu einer Einheit auf einer anderen Instanz. Bitte "
                    "eine Korrektur vorschlagen."
                )
            )
        data = MemberUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        person = m.person
        before = snapshot(person)
        for f in ("last_name", "first_name", "birth_date", "gender"):
            if f in values:
                setattr(person, f, values[f])
        person.save()
        changes = diff(before, snapshot(person))
        contact = {k: values[k] for k in services.CONTACT_FIELDS if k in values}
        if contact:
            old = services.contact_for(person, m.organization)
            new = services.save_contact(person, m.organization, contact)
            changes.update(diff(snapshot(old) if old else {}, snapshot(new)))
        changes.pop("Verbandsbereich", None)
        changes.pop("person", None)
        if not changes:
            raise serializers.ValidationError(gettext("Keine Änderungen."))
        changes["geändert durch Dachverband"] = [None, self.org.name]
        record(self.org, request.user, "update", m, changes, person=person)
        record(m.organization, request.user, "update", m, changes, person=person)
        detail = member_detail(m, m.organization)
        detail["club"] = m.organization.name
        detail["readonly"] = False
        return Response(detail)
