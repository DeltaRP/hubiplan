"""Ehrungen: Bezeichnungen je Verein oder Dachverband, Verleihung am Mitglied.

- Vereine und Dachverbände legen ihre Ehrungen selbst an (Mitglieder › Einrichtung).
  Je Ehrung optional eine Beitragsanpassung: beitragsfrei, fester Jahresbeitrag
  oder Abschlag in Prozent. Ehrungen des Vereins wirken auf den Vereinsbeitrag,
  Ehrungen des Dachverbands auf den Verbandsbeitrag des Vereins für dieses Mitglied.
- Verliehen wird mit Von-/Bis-Datum; mehrere Ehrungen gleichzeitig sind möglich.
  Hat ein Mitglied mehrere Ehrungen mit Beitragsanpassung, gilt die günstigste.
- Ein Verein sieht zusätzlich die Ehrungen, die der Dachverband seinen Mitgliedern
  verliehen hat (nur lesen).
"""

from __future__ import annotations

import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from access.catalog import MEMBERS_EDIT, MEMBERS_VIEW, ORG_EDIT
from audit.log import diff, record, snapshot
from core.api_base import AuditMixin, OrgScopedMixin
from core.reorder import reorder_response
from organizations.models import Organization

from .models import HonoraryTitle, HonoraryTitleAward, Membership, overlaps, today

CENT = Decimal("0.01")


# --- Abfragen ---


def current_awards(on: datetime.date | None = None):
    on = on or today()
    return HonoraryTitleAward.objects.filter(valid_from__lte=on).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=on)
    )


def visible_orgs(org: Organization) -> list[int]:
    """Organisationen, deren Ehrungen ``org`` an seinen Mitgliedern sieht."""
    ids = [org.pk]
    if org.type == Organization.Type.CLUB and org.parent_id:
        ids.append(org.parent_id)
    return ids


def titles_by_person(person_ids, org: Organization, on=None, full_names=False):
    """Person → aktuelle Ehrungen (Namen), eigene zuerst, dann die des Dachverbands."""
    result: dict[int, list[str]] = {}
    own_first = sorted(
        current_awards(on)
        .filter(person_id__in=person_ids, organization_id__in=visible_orgs(org))
        .select_related("title"),
        key=lambda a: (a.organization_id != org.pk, a.title.sort_order, a.title.name),
    )
    for a in own_first:
        names = result.setdefault(a.person_id, [])
        if a.title.name not in names:
            names.append(a.title.name)
    return result


def adjusted_fee(titles, normal: Decimal) -> tuple[Decimal, str] | None:
    """Beitrag nach Ehrungen (günstigste gilt) und Name der Ehrung, sonst None."""
    best = None
    for t in titles:
        if t.fee_mode == HonoraryTitle.FeeMode.FREE:
            amount = Decimal("0.00")
        elif t.fee_mode == HonoraryTitle.FeeMode.AMOUNT and t.fee_amount is not None:
            amount = t.fee_amount
        elif t.fee_mode == HonoraryTitle.FeeMode.DISCOUNT and t.fee_discount_percent is not None:
            factor = (Decimal(100) - t.fee_discount_percent) / Decimal(100)
            amount = (normal * factor).quantize(CENT, ROUND_HALF_UP)
        else:
            continue
        if best is None or amount < best[0]:
            best = (amount, t.name)
    return best


def fee_titles(org_id: int, person_id: int, on: datetime.date) -> list[HonoraryTitle]:
    """Ehrungen mit Beitragsanpassung, die ``org_id`` der Person am Stichtag verliehen hat."""
    return [
        a.title
        for a in current_awards(on)
        .filter(organization_id=org_id, person_id=person_id)
        .exclude(title__fee_mode=HonoraryTitle.FeeMode.NONE)
        .select_related("title")
    ]


# --- Bezeichnungen ---


class HonoraryTitleSerializer(serializers.ModelSerializer):
    in_use = serializers.SerializerMethodField()
    own = serializers.SerializerMethodField()
    owner_name = serializers.CharField(source="organization.display_name", read_only=True)
    fee_text = serializers.CharField(read_only=True)
    plural = serializers.CharField(read_only=True)

    class Meta:
        model = HonoraryTitle
        fields = [
            "id",
            "name",
            "name_plural",
            "plural",
            "fee_mode",
            "fee_amount",
            "fee_discount_percent",
            "fee_text",
            "is_archived",
            "sort_order",
            "is_public",
            "year_only",
            "in_use",
            "own",
            "owner_name",
        ]

    def get_in_use(self, obj) -> bool:
        return obj.awards.exists()

    def get_own(self, obj) -> bool:
        org = self.context.get("org")
        return org is not None and obj.organization_id == org.pk

    def validate_name(self, value: str) -> str:
        value = value.strip()
        org = self.context["org"]
        qs = HonoraryTitle.objects.filter(organization=org, name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Diese Ehrung gibt es schon.")
        return value

    def validate(self, attrs):
        get = lambda k: attrs.get(k, getattr(self.instance, k, None))  # noqa: E731
        mode = get("fee_mode") or HonoraryTitle.FeeMode.NONE
        amount, percent = get("fee_amount"), get("fee_discount_percent")
        if mode == HonoraryTitle.FeeMode.AMOUNT:
            if amount is None:
                raise serializers.ValidationError({"fee_amount": "Bitte einen Betrag angeben."})
            if amount < 0:
                raise serializers.ValidationError(
                    {"fee_amount": "Der Beitrag darf nicht negativ sein."}
                )
        if mode == HonoraryTitle.FeeMode.DISCOUNT and (percent is None or not (0 < percent <= 100)):
            raise serializers.ValidationError(
                {"fee_discount_percent": "Der Abschlag liegt zwischen 0 und 100 Prozent."}
            )
        return attrs


class HonoraryTitleViewSet(OrgScopedMixin, AuditMixin, viewsets.ModelViewSet):
    """Ehrungen der Organisation (lesen: jede Rolle; ändern: Organisation bearbeiten).

    ``?alle=1`` liefert im Verein zusätzlich die Ehrungen des Dachverbands (nur lesen).
    """

    serializer_class = HonoraryTitleSerializer
    allowed_org_types = (Organization.Type.CLUB, Organization.Type.FEDERATION)
    write_permission = ORG_EDIT

    def get_queryset(self):
        qs = HonoraryTitle.objects.select_related("organization")
        if self.action == "list" and self.request.query_params.get("alle") == "1":
            return qs.filter(organization_id__in=visible_orgs(self.org)).order_by(
                "organization__type", "sort_order", "name"
            )
        return qs.filter(organization=self.org)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["org"] = getattr(self, "org", None)
        return ctx

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}

    @action(detail=False, methods=["post"])
    def reorder(self, request, *args, **kwargs):
        return reorder_response(
            request, self.org, HonoraryTitle.objects.filter(organization=self.org), "sort_order"
        )

    @action(detail=True, methods=["get"])
    def usage(self, request, org_id: int, pk: int):
        title = self.get_object()
        count = title.awards.count()
        return Response(
            {
                "deletable": count == 0,
                "reasons": [f"{count} Mal verliehen (auch frühere Verleihungen)"] if count else [],
                "is_archived": title.is_archived,
            }
        )

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        title = self.get_object()
        if title.awards.exists():
            return Response(
                {
                    "detail": f"„{title.name}“ ist verliehen und kann nur archiviert werden.",
                    "can_archive": not title.is_archived,
                },
                status=status.HTTP_409_CONFLICT,
            )
        self.perform_destroy(title)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def archive(self, request, org_id: int, pk: int):
        return self._set_archived(True)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def restore(self, request, org_id: int, pk: int):
        return self._set_archived(False)

    def _set_archived(self, archived: bool):
        title = self.get_object()
        if title.is_archived != archived:
            title.is_archived = archived
            title.save(update_fields=["is_archived"])
            record(
                self.org,
                self.request.user,
                "update",
                title,
                {"archiviert": [not archived, archived]},
            )
        return Response(self.get_serializer(title).data)


# --- Verleihungen ---


class AwardSerializer(serializers.ModelSerializer):
    title_name = serializers.CharField(source="title.name", read_only=True)
    fee_text = serializers.CharField(source="title.fee_text", read_only=True)
    owner_name = serializers.CharField(source="organization.display_name", read_only=True)
    year_only = serializers.BooleanField(source="title.year_only", read_only=True)

    class Meta:
        model = HonoraryTitleAward
        fields = [
            "id",
            "title",
            "title_name",
            "fee_text",
            "owner_name",
            "valid_from",
            "valid_until",
            "note",
            "year_only",
        ]

    def get_fields(self):
        fields = super().get_fields()
        org = self.context.get("org")
        if org is not None:
            fields["title"].queryset = HonoraryTitle.objects.filter(organization=org)
        return fields

    def validate(self, attrs):
        start = attrs.get("valid_from", getattr(self.instance, "valid_from", None))
        end = attrs.get("valid_until", getattr(self.instance, "valid_until", None))
        title = attrs.get("title", getattr(self.instance, "title", None))
        if title is not None and title.year_only and start:
            # Nur Jahr der Verleihung: 1.1. des Jahres
            start = start.replace(month=1, day=1)
            attrs["valid_from"] = start
        if end and start and end < start:
            raise serializers.ValidationError({"valid_until": "Das Ende liegt vor dem Beginn."})
        if self.instance is None and title is not None and title.is_archived:
            raise serializers.ValidationError({"title": "Diese Ehrung ist archiviert."})
        person_id = self.context["person_id"]
        others = HonoraryTitleAward.objects.filter(
            organization=self.context["org"], person_id=person_id, title=title
        )
        if self.instance:
            others = others.exclude(pk=self.instance.pk)
        for other in others:
            if overlaps(start, end, other.valid_from, other.valid_until):
                raise serializers.ValidationError(
                    "Das Mitglied hat diese Ehrung im Zeitraum bereits."
                )
        return attrs


def awards_of(person_id: int, org: Organization) -> dict:
    """Ehrungen einer Person aus Sicht von ``org``: eigene und (Verein) die des Dachverbands."""
    qs = HonoraryTitleAward.objects.filter(person_id=person_id).select_related(
        "title", "organization"
    )
    own = qs.filter(organization=org)
    data = {"own": AwardSerializer(own, many=True).data}
    if org.type == Organization.Type.CLUB and org.parent_id:
        data["federation"] = AwardSerializer(
            qs.filter(organization_id=org.parent_id), many=True
        ).data
    return data


class _AwardViewSet(viewsets.ModelViewSet):
    serializer_class = AwardSerializer
    http_method_names = ["get", "post", "patch", "delete", "options", "head"]

    def get_membership(self) -> Membership:  # pragma: no cover - je Unterklasse
        raise NotImplementedError

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if getattr(self, "org", None) is not None:
            ctx["org"] = self.org
            ctx["person_id"] = self.get_membership().person_id
        return ctx

    def get_queryset(self):
        return HonoraryTitleAward.objects.filter(
            organization=self.org, person_id=self.get_membership().person_id
        ).select_related("title", "organization")

    def audit_orgs(self, membership: Membership) -> list[Organization]:
        return [self.org]

    def _record(self, action_: str, instance, changes: dict):
        membership = self.get_membership()
        for org in self.audit_orgs(membership):
            record(org, self.request.user, action_, instance, changes, person=membership.person)

    def perform_create(self, serializer):
        membership = self.get_membership()
        instance = serializer.save(organization=self.org, person_id=membership.person_id)
        self._record("create", instance, diff({}, snapshot(instance)))

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        instance = serializer.save()
        changes = diff(before, snapshot(instance))
        if changes:
            self._record("update", instance, changes)

    def perform_destroy(self, instance):
        self._record("delete", instance, diff(snapshot(instance), {}))
        instance.delete()


class MemberAwardViewSet(OrgScopedMixin, _AwardViewSet):
    """Ehrungen des Vereins an einem Mitglied, auch an eigenen Mitgliedern eines
    Dachverbands (Audit 31.10. M31-02; die Freigabe für Vereinsdaten gilt dafür nicht)."""

    allowed_org_types = (Organization.Type.CLUB, Organization.Type.FEDERATION)
    read_permission = MEMBERS_VIEW
    write_permission = MEMBERS_EDIT

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not self.org.keeps_members:
            raise NotFound()

    def get_membership(self) -> Membership:
        if not hasattr(self, "_membership"):
            self._membership = get_object_or_404(
                Membership.objects.select_related("person"),
                organization=self.org,
                pk=self.kwargs["member_pk"],
            )
        return self._membership


class FederationAwardViewSet(OrgScopedMixin, _AwardViewSet):
    """Ehrungen des Dachverbands an einem Mitglied eines seiner Vereine.

    Die Ehrungen gehören dem Dachverband; dafür genügt der Lesezugriff auf die
    Mitgliedsdaten der Vereine.
    """

    allowed_org_types = (Organization.Type.FEDERATION,)
    read_permission = MEMBERS_VIEW
    write_permission = MEMBERS_EDIT

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if self.org.federation_member_access == "none":
            raise PermissionDenied(
                "Die Plattform hat den Zugriff auf Mitgliedsdaten nicht freigegeben."
            )

    def audit_orgs(self, membership: Membership) -> list[Organization]:
        return [self.org, membership.organization]

    def get_membership(self) -> Membership:
        if not hasattr(self, "_membership"):
            self._membership = get_object_or_404(
                Membership.objects.select_related("person", "organization"),
                scope=self.org,
                pk=self.kwargs["member_pk"],
            )
        return self._membership
