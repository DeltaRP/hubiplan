"""Serializer für Termine und Kategorien."""

from __future__ import annotations

import datetime

from django.utils import timezone
from django.utils.translation import gettext
from rest_framework import serializers

from core.api_base import ModelCleanMixin

from .models import Event, EventCategory, EventException


class CategorySerializer(ModelCleanMixin, serializers.ModelSerializer):
    class Meta:
        model = EventCategory
        fields = ["id", "name", "color", "is_active"]

    def validate_name(self, value):
        value = value.strip()
        org = self.context["org"]
        qs = EventCategory.objects.filter(organization=org, name__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(gettext("Diese Kategorie gibt es schon."))
        return value


def _midnight(value: datetime.datetime) -> datetime.datetime:
    local = timezone.localtime(value)
    return timezone.make_aware(
        datetime.datetime.combine(local.date(), datetime.time.min),
        timezone.get_current_timezone(),
    )


class EventWriteSerializer(ModelCleanMixin, serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(
        queryset=EventCategory.objects.all(), allow_null=True, required=False
    )

    class Meta:
        model = Event
        fields = [
            "title",
            "description",
            "location",
            "address",
            "category",
            "all_day",
            "starts_at",
            "ends_at",
            "visibility",
            "repeat",
            "repeat_interval",
            "repeat_until",
            "is_cancelled",
            "cancel_note",
            "rsvp_enabled",
            "rsvp_deadline",
            "rsvp_capacity",
            "rsvp_guests",
            "remind_days",
            "share_up",
            "share_down",
            "notify",
        ]
        extra_kwargs = {
            "ends_at": {"required": False},
            "share_up": {"allow_null": True, "required": False},
            "share_down": {"allow_null": True, "required": False},
        }

    # Eingeladene per E-Mail benachrichtigen (Einladung bzw. Änderung oder Absage)
    notify = serializers.BooleanField(write_only=True, required=False, default=False)

    def extra_clean_attrs(self) -> dict:
        return {
            "organization": self.context["org"],
            "department": self.context.get("department"),
        }

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(gettext("Bitte einen Titel angeben."))
        return value

    def validate_category(self, value):
        if value is not None and value.organization_id != self.context["org"].pk:
            raise serializers.ValidationError(gettext("Unbekannte Kategorie."))
        return value

    def validate(self, attrs):
        inst = self.instance
        all_day = attrs.get("all_day", inst.all_day if inst else False)
        starts = attrs.get("starts_at", inst.starts_at if inst else None)
        ends = attrs.get("ends_at", inst.ends_at if inst else None)
        if starts is None:
            raise serializers.ValidationError({"starts_at": gettext("Bitte den Beginn angeben.")})
        if ends is None:
            ends = starts if all_day else starts + datetime.timedelta(hours=2)
        if all_day:
            starts, ends = _midnight(starts), _midnight(ends)
        attrs["starts_at"], attrs["ends_at"] = starts, ends
        if attrs.get("repeat", inst.repeat if inst else "none") == Event.Repeat.NONE:
            attrs["repeat_interval"] = 1
            attrs["repeat_until"] = None
        if not attrs.get("is_cancelled", inst.is_cancelled if inst else False):
            attrs["cancel_note"] = ""
        if not attrs.get("rsvp_enabled", inst.rsvp_enabled if inst else False):
            attrs["rsvp_deadline"] = None
            attrs["rsvp_capacity"] = None
            attrs["rsvp_guests"] = False
        self.notify = attrs.pop("notify", False)
        return super().validate(attrs)


class ExceptionSerializer(serializers.Serializer):
    original_start = serializers.DateTimeField()
    is_cancelled = serializers.BooleanField(default=False)
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)

    def validate(self, attrs):
        starts, ends = attrs.get("starts_at"), attrs.get("ends_at")
        if ends and not starts:
            raise serializers.ValidationError(
                {"starts_at": gettext("Bitte auch den Beginn angeben.")}
            )
        if starts and ends and ends < starts:
            raise serializers.ValidationError(
                {"ends_at": gettext("Das Ende liegt vor dem Beginn.")}
            )
        return attrs


def exception_data(exc: EventException) -> dict:
    return {
        "original_start": exc.original_start,
        "is_cancelled": exc.is_cancelled,
        "starts_at": exc.starts_at,
        "ends_at": exc.ends_at,
        "note": exc.note,
    }
