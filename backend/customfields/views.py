from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import MEMBERS_EDIT, MEMBERS_VIEW, ORG_EDIT
from audit.log import diff, record, snapshot
from core.api_base import AuditMixin, ModelCleanMixin, OrgScopedMixin
from members.models import Membership

from .models import TYPE_KEYS, FieldDefinition, FieldValue, clean_value, make_key


def definitions_for(org):
    """Eigene Felder plus verbandsweite Felder des Dachverbands (bei Vereinen)."""
    q = Q(organization=org)
    if org.federation is not None:
        q |= Q(organization=org.federation, federation_wide=True)
    return FieldDefinition.objects.filter(q).select_related("organization")


class SubfieldSerializer(serializers.Serializer):
    key = serializers.SlugField(required=False, allow_blank=True)
    label = serializers.CharField(max_length=100)
    type = serializers.ChoiceField(choices=sorted(TYPE_KEYS))
    choices = serializers.ListField(child=serializers.CharField(max_length=100), required=False)


class FieldDefinitionSerializer(ModelCleanMixin, serializers.ModelSerializer):
    subfields = SubfieldSerializer(many=True, required=False)
    inherited = serializers.SerializerMethodField()
    owner_name = serializers.CharField(source="organization.display_name", read_only=True)
    in_use = serializers.SerializerMethodField()
    key = serializers.SlugField(required=False, allow_blank=True, max_length=50)

    class Meta:
        model = FieldDefinition
        fields = [
            "id",
            "label",
            "key",
            "field_type",
            "choices",
            "repeatable",
            "subfields",
            "federation_wide",
            "help_text",
            "sort_order",
            "is_archived",
            "inherited",
            "owner_name",
            "in_use",
        ]

    def get_inherited(self, obj) -> bool:
        return obj.organization_id != self.context["org"].pk

    def get_in_use(self, obj) -> bool:
        return obj.values.exists()

    def extra_clean_attrs(self) -> dict:
        return {"organization": self.context["org"]}

    def validate(self, attrs):
        if not attrs.get("key") and (self.instance is None or "label" in attrs):
            attrs["key"] = make_key(attrs.get("label") or self.instance.label)
        if attrs.get("key"):
            qs = FieldDefinition.objects.filter(organization=self.context["org"], key=attrs["key"])
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"label": gettext("Ein Feld mit dieser Bezeichnung gibt es schon.")}
                )
        subfields = attrs.get("subfields")
        if subfields is not None:
            attrs["subfields"] = [
                {
                    "key": sub.get("key") or make_key(sub["label"]),
                    "label": sub["label"],
                    "type": sub["type"],
                    "choices": sub.get("choices", []),
                }
                for sub in subfields
            ]
        if self.instance is not None:
            self._check_used_structure(attrs)
        return super().validate(attrs)

    def _check_used_structure(self, attrs) -> None:
        """Benutzte Felder: Struktur nur so ändern, dass keine Werte verloren gehen."""
        field = self.instance
        values = list(field.values.values_list("value", flat=True))
        if not values:
            return
        n = len(values)
        errors = {}
        if "repeatable" in attrs and attrs["repeatable"] != field.repeatable:
            errors["repeatable"] = (
                f"Das Feld ist bei {n} Personen ausgefüllt; „wiederholbar“ lässt sich nicht mehr "
                "umstellen. Bitte ein neues Feld anlegen und dieses archivieren."
            )
        if (
            not field.repeatable
            and "field_type" in attrs
            and attrs["field_type"] != field.field_type
        ):
            errors["field_type"] = (
                f"Das Feld ist bei {n} Personen ausgefüllt; der Typ lässt sich nicht mehr ändern. "
                "Bitte ein neues Feld anlegen und dieses archivieren."
            )
        if field.repeatable and "subfields" in attrs:
            new = {sub["key"]: sub for sub in attrs["subfields"]}
            drop = []
            for old in field.subfields:
                used = sum(
                    1
                    for rows in values
                    if isinstance(rows, list)
                    and any(
                        isinstance(r, dict) and r.get(old["key"]) not in (None, "") for r in rows
                    )
                )
                if not used:
                    continue
                if old["key"] not in new:
                    drop.append(old["key"])
                    if not self.context.get("with_values"):
                        errors["subfields"] = (
                            f"„{old['label']}“ ist bei {used} Personen ausgefüllt. "
                            "Entfernen geht nur ausdrücklich samt diesen Werten."
                        )
                elif new[old["key"]]["type"] != old["type"]:
                    errors["subfields"] = (
                        f"„{old['label']}“ ist bei {used} Personen ausgefüllt; "
                        "der Typ lässt sich nicht mehr ändern."
                    )
            self._drop_keys = drop
        if errors:
            raise serializers.ValidationError(errors)

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        drop = getattr(self, "_drop_keys", [])
        if drop:
            # Ausdrücklich bestätigt: Werte entfernter Unterfelder löschen
            for value in instance.values.all():
                rows = [
                    {k: v for k, v in row.items() if k not in drop}
                    for row in (value.value or [])
                    if isinstance(row, dict)
                ]
                rows = [row for row in rows if any(v not in (None, "") for v in row.values())]
                if rows:
                    value.value = rows
                    value.save(update_fields=["value", "updated_at"])
                else:
                    value.delete()
        return instance


class FieldDefinitionViewSet(OrgScopedMixin, AuditMixin, viewsets.ModelViewSet):
    """Zusatzfelder des Vereins oder Dachverbands (verbandsweite werden mitgezeigt)."""

    serializer_class = FieldDefinitionSerializer
    write_permission = ORG_EDIT
    allowed_org_types = ("club", "federation")

    def get_queryset(self):
        # Verbandsweite Felder sieht ein Verein nur; Nutzung zählt nur der Eigentümer.
        if self.request.method in ("GET", "HEAD", "OPTIONS") and self.action != "usage":
            return definitions_for(self.org)
        return FieldDefinition.objects.filter(organization=self.org)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["org"] = getattr(self, "org", None)
        ctx["with_values"] = self.request.query_params.get("mit_werten") in ("1", "true", "ja")
        return ctx

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}

    def _usage(self, field: FieldDefinition) -> dict:
        count = field.values.count()
        return {
            "deletable": count == 0,
            "value_count": count,
            "is_archived": field.is_archived,
        }

    @action(detail=True, methods=["get"])
    def usage(self, request, org_id: int, pk: int):
        """Vorschau: wird das Feld gelöscht, oder hat es schon Werte?"""
        return Response(self._usage(self.get_object()))

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        """Unbenutzt: löschen. Mit Werten: 409, außer ``?mit_werten=1`` (dann samt Werten)."""
        field = self.get_object()
        usage = self._usage(field)
        with_values = request.query_params.get("mit_werten") in ("1", "true", "ja")
        if usage["value_count"] and not with_values:
            return Response(
                {
                    "detail": gettext(
                        "„{label}“ ist bei {x} Personen ausgefüllt. Bitte archivieren oder "
                        "ausdrücklich samt Werten löschen."
                    ).format(label=field.label, x=usage["value_count"]),
                    **usage,
                    "can_archive": not field.is_archived,
                },
                status=status.HTTP_409_CONFLICT,
            )
        changes = diff(snapshot(field), {})
        if usage["value_count"]:
            changes["gelöschte Werte"] = [usage["value_count"], 0]
            field.values.all().delete()
        record(self.org, request.user, "delete", field, changes)
        field.delete()
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
        field = self.get_object()
        if field.is_archived != archived:
            field.is_archived = archived
            field.save(update_fields=["is_archived"])
            record(
                self.org,
                self.request.user,
                "update",
                field,
                {"archiviert": [not archived, archived]},
            )
        return Response(self.get_serializer(field).data)


class MemberFieldsView(OrgScopedMixin, APIView):
    """Reiter „Zusatzfelder“ der Mitgliedsakte."""

    read_permission = MEMBERS_VIEW
    write_permission = MEMBERS_EDIT
    # Auch eigene Mitglieder eines Dachverbands (Audit 31.10. M31-02)
    allowed_org_types = ("club", "federation")

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not self.org.keeps_members:
            raise NotFound()

    def membership(self) -> Membership:
        return get_object_or_404(
            Membership.objects.select_related("person"), organization=self.org, pk=self.kwargs["pk"]
        )

    def payload(self, membership: Membership) -> list[dict]:
        definitions = [d for d in definitions_for(self.org) if not d.is_archived]
        values = {
            v.definition_id: v.value
            for v in FieldValue.objects.filter(person=membership.person, definition__in=definitions)
        }
        ctx = {"org": self.org}
        return [
            {
                "definition": FieldDefinitionSerializer(d, context=ctx).data,
                "value": values.get(d.pk, [] if d.repeatable else None),
            }
            for d in definitions
        ]

    def get(self, request, org_id: int, pk: int):
        return Response(self.payload(self.membership()))

    @transaction.atomic
    def put(self, request, org_id: int, pk: int):
        membership = self.membership()
        incoming = request.data.get("values", {})
        if not isinstance(incoming, dict):
            raise serializers.ValidationError({"values": gettext("Ungültige Daten.")})
        definitions = {str(d.pk): d for d in definitions_for(self.org) if not d.is_archived}
        errors = {}
        changes = {}
        for def_id, raw in incoming.items():
            definition = definitions.get(str(def_id))
            if definition is None:
                errors[def_id] = "Unbekanntes Feld."
                continue
            try:
                value = clean_value(definition, raw)
            except DjangoValidationError as exc:
                errors[def_id] = " ".join(exc.messages)
                continue
            current = FieldValue.objects.filter(
                definition=definition, person=membership.person
            ).first()
            old = current.value if current else None
            if value in (None, []) and current:
                current.delete()
            elif value not in (None, []):
                FieldValue.objects.update_or_create(
                    definition=definition,
                    person=membership.person,
                    defaults={"value": value, "organization": definition.organization},
                )
            if old != value and not (old is None and value in (None, [])):
                changes[definition.label] = [old, value]
        if errors:
            raise serializers.ValidationError(errors)
        if changes:
            record(self.org, request.user, "update", membership, changes, person=membership.person)
        return Response(self.payload(membership))
