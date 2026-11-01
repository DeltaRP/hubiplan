"""API der Abläufe: Art wechseln, Austritt, Wiedereintritt, Wechselanfragen."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.log import record

from . import services, workflows
from .models import ExitReason, Membership, MemberType, Person, TransferRequest
from .serializers import member_detail
from .views import _ClubMixin

ARCHIVED = "Diese Art wird nicht mehr verwendet."


class ChangeTypeSerializer(serializers.Serializer):
    member_type = serializers.IntegerField()
    valid_from = serializers.DateField()


class ExitSerializer(serializers.Serializer):
    exit_date = serializers.DateField()
    exit_reason = serializers.ChoiceField(choices=ExitReason.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=200)


class ReentrySerializer(serializers.Serializer):
    entry_date = serializers.DateField()
    member_type = serializers.IntegerField()
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=50)
    street = serializers.CharField(required=False, max_length=200)
    postal_code = serializers.CharField(required=False, max_length=10)
    city = serializers.CharField(required=False, max_length=100)
    country = serializers.CharField(required=False, max_length=100)


class _WorkflowView(_ClubMixin, APIView):
    def get_membership(self) -> Membership:
        return get_object_or_404(
            Membership.objects.select_related("person"),
            organization=self.org,
            pk=self.kwargs["pk"],
        )

    def member_type(self, pk) -> MemberType:
        member_type = MemberType.objects.filter(organization=self.org, pk=pk).first()
        if member_type is None:
            raise serializers.ValidationError({"member_type": gettext("Unbekannte Mitgliedsart.")})
        if member_type.is_archived:
            raise serializers.ValidationError({"member_type": ARCHIVED})
        return member_type


class ChangeTypeView(_WorkflowView):
    """Mitgliedsart wechseln: alte Art endet am Vortag, Zeitraum läuft weiter."""

    @transaction.atomic  # Fachänderung und Protokoll gemeinsam (Audit 31.10. D31-04)
    def post(self, request, org_id: int, pk: int):
        membership = self.get_membership()
        data = ChangeTypeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        on = data.validated_data["valid_from"]
        old = membership.current_type(on)
        new_type = self.member_type(data.validated_data["member_type"])
        workflows.change_type(membership, new_type, on)
        record(
            self.org,
            request.user,
            "update",
            membership,
            {
                "Mitgliedsart": [old.member_type.name if old else None, new_type.name],
                "ab": [None, on.isoformat()],
            },
            person=membership.person,
        )
        return Response(member_detail(membership, self.org))


class ExitView(_WorkflowView):
    """Austritt mit Grund. Die Person wandert ins Archiv (ehemalige Mitglieder)."""

    @transaction.atomic  # Fachänderung und Protokoll gemeinsam (Audit 31.10. D31-04)
    def post(self, request, org_id: int, pk: int):
        membership = self.get_membership()
        data = ExitSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        workflows.exit_membership(membership, v["exit_date"], v["exit_reason"], v.get("note", ""))
        record(
            self.org,
            request.user,
            "update",
            membership,
            {
                "Austritt": [None, v["exit_date"].isoformat()],
                "Austrittsgrund": [None, ExitReason(v["exit_reason"]).label],
            },
            person=membership.person,
        )
        return Response(member_detail(membership, self.org))


class ReentryView(_WorkflowView):
    """Wiedereintritt aus dem Archiv: neuer Zeitraum, alte Daten bleiben."""

    @transaction.atomic  # Fachänderung und Protokoll gemeinsam (Audit 31.10. D31-04)
    def post(self, request, org_id: int, pk: int):
        membership = self.get_membership()
        data = ReentrySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        member_type = self.member_type(v.pop("member_type"))
        entry_date = v.pop("entry_date")
        contact = {k: val for k, val in v.items() if k in services.CONTACT_FIELDS}
        if contact and not all(contact.get(f) for f in ("street", "postal_code", "city")):
            raise serializers.ValidationError(gettext("Bitte die vollständige Anschrift angeben."))
        workflows.reenter(membership, entry_date, member_type, contact or None)
        record(
            self.org,
            request.user,
            "update",
            membership,
            {
                "Wiedereintritt": [None, entry_date.isoformat()],
                "Mitgliedsart": [None, member_type.name],
            },
            person=membership.person,
        )
        return Response(member_detail(membership, self.org))


# --- Wechselanfragen ---


class TransferSerializer(serializers.ModelSerializer):
    person_name = serializers.SerializerMethodField()
    birth_date = serializers.DateField(source="person.birth_date", read_only=True)
    from_org_name = serializers.CharField(source="from_org.display_name", read_only=True)
    to_org_name = serializers.CharField(source="to_org.display_name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    decision_label = serializers.CharField(source="get_decision_display", read_only=True)
    direction = serializers.SerializerMethodField()

    class Meta:
        model = TransferRequest
        fields = [
            "id",
            "person_name",
            "birth_date",
            "from_org_name",
            "to_org_name",
            "member_type_name",
            "entry_date",
            "message",
            "status",
            "status_label",
            "decision",
            "decision_label",
            "response",
            "created_at",
            "decided_at",
            "direction",
        ]

    def get_person_name(self, obj) -> str:
        return f"{obj.person.first_name} {obj.person.last_name}"

    def get_direction(self, obj) -> str:
        return "incoming" if obj.from_org_id == self.context["org"].pk else "outgoing"


class TransferCreateSerializer(serializers.Serializer):
    person = serializers.IntegerField()
    member_type = serializers.IntegerField()
    entry_date = serializers.DateField()
    message = serializers.CharField(required=False, allow_blank=True, max_length=500)
    club_number = serializers.CharField(required=False, allow_blank=True, max_length=30)
    department_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=50)
    street = serializers.CharField(max_length=200)
    postal_code = serializers.CharField(max_length=10)
    city = serializers.CharField(max_length=100)
    country = serializers.CharField(required=False, max_length=100)


class TransferDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["exit", "change_type", "reject"])
    member_type = serializers.IntegerField(required=False)
    response = serializers.CharField(required=False, allow_blank=True, max_length=500)


class TransferListView(_ClubMixin, APIView):
    """Eingegangene und gestellte Wechselanfragen des Vereins."""

    def get(self, request, org_id: int):
        qs = TransferRequest.objects.filter(
            Q(from_org=self.org) | Q(to_org=self.org)
        ).select_related("person", "from_org", "to_org")
        return Response(TransferSerializer(qs, many=True, context={"org": self.org}).data)

    @transaction.atomic
    def post(self, request, org_id: int):
        data = TransferCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        person = Person.objects.filter(
            pk=v.pop("person"), scope=services.scope_for(self.org)
        ).first()
        if person is None:
            raise serializers.ValidationError({"person": gettext("Unbekannte Person.")})
        member_type = MemberType.objects.filter(
            organization=self.org, pk=v.pop("member_type")
        ).first()
        if member_type is None:
            raise serializers.ValidationError({"member_type": gettext("Unbekannte Mitgliedsart.")})
        if member_type.is_archived:
            raise serializers.ValidationError({"member_type": ARCHIVED})
        transfer = workflows.create_transfer(
            self.org,
            request.user,
            {
                "person": person,
                "member_type": member_type,
                "entry_date": v.pop("entry_date"),
                "message": v.pop("message", ""),
                "admission": v,
            },
        )
        record(self.org, request.user, "create", transfer, {}, person=person)
        record(transfer.from_org, request.user, "create", transfer, {}, person=person)
        return Response(
            TransferSerializer(transfer, context={"org": self.org}).data,
            status=status.HTTP_201_CREATED,
        )


class TransferDecisionView(_ClubMixin, APIView):
    """Der bisherige Verein entscheidet über eine eingegangene Anfrage."""

    @transaction.atomic  # Fachänderung und Protokoll gemeinsam (Audit 31.10. D31-04)
    def post(self, request, org_id: int, pk: int):
        transfer = get_object_or_404(TransferRequest, pk=pk, from_org=self.org)
        data = TransferDecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        new_type = None
        if v["decision"] == "change_type":
            new_type = MemberType.objects.filter(
                organization=self.org, pk=v.get("member_type"), is_archived=False
            ).first()
        workflows.decide_transfer(
            transfer, request.user, v["decision"], v.get("response", ""), new_type
        )
        changes = {"Status": ["offen", transfer.get_status_display()]}
        record(self.org, request.user, "update", transfer, changes, person=transfer.person)
        record(transfer.to_org, request.user, "update", transfer, changes, person=transfer.person)
        return Response(TransferSerializer(transfer, context={"org": self.org}).data)


class TransferCancelView(_ClubMixin, APIView):
    """Der neue Verein zieht seine offene Anfrage zurück."""

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        transfer = get_object_or_404(
            TransferRequest, pk=pk, to_org=self.org, status=TransferRequest.Status.PENDING
        )
        transfer = workflows.cancel_transfer(transfer)
        record(
            self.org,
            request.user,
            "update",
            transfer,
            {"Status": ["offen", "zurückgezogen"]},
            person=transfer.person,
        )
        return Response(TransferSerializer(transfer, context={"org": self.org}).data)
