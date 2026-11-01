"""Würden und Chronik in der Verwaltung (Mitglieder › Würdenträger).

Lesen: Mitglieder ansehen · Ändern: Mitglieder bearbeiten.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import MEMBERS_EDIT, MEMBERS_VIEW
from audit.log import diff, record, snapshot
from changes import idempotency
from core.api_base import AuditMixin, OrgScopedMixin
from core.reorder import reorder_response
from members.models import Membership
from organizations.models import Department, Organization

from . import importer, numbering
from .models import Companion, Dignity, Reign, ReignPhoto


class _HonorsMixin(OrgScopedMixin):
    allowed_org_types = (Organization.Type.CLUB, Organization.Type.FEDERATION)
    read_permission = MEMBERS_VIEW
    write_permission = MEMBERS_EDIT


def origin_choices(org) -> list[Organization]:
    """Einheiten, aus denen ein Würdenträger kommen kann: die Untereinheiten im
    Datenbereich (z. B. Züge) und Vereine direkt darunter (beim Dachverband)."""
    units = list(Department.objects.filter(organization=org).order_by("sort_order", "name"))
    clubs = list(
        Organization.objects.filter(parent=org, type=Organization.Type.CLUB, is_active=True)
        .exclude(pk=org.pk)
        .order_by("name")
    )
    return units + clubs


def default_origin(org, person):
    """Untereinheit, der das Mitglied heute angehört (bei mehreren keine)."""
    from members.models import DepartmentMembership, today

    on = today()
    ids = set(
        DepartmentMembership.objects.filter(
            organization=org, membership__person=person, valid_from__lte=on
        )
        .exclude(valid_until__lt=on)
        .values_list("department_id", flat=True)
    )
    return Department.objects.filter(pk=ids.pop()).first() if len(ids) == 1 else None


def member_person_ids(org) -> set[int]:
    return set(
        Membership.objects.filter(organization=org, purged_at__isnull=True).values_list(
            "person_id", flat=True
        )
    )


# --- Würden ---


class DignitySerializer(serializers.ModelSerializer):
    unit_name = serializers.CharField(source="unit.name", read_only=True, default=None)
    plural = serializers.CharField(read_only=True)
    reign_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Dignity
        fields = [
            "id",
            "name",
            "unit",
            "unit_name",
            "sort_order",
            "is_public",
            "is_archived",
            "numbered",
            "count_each_reign",
            "share_down",
            "name_plural",
            "plural",
            "reign_count",
        ]

    def validate_unit(self, value):
        if value is None:
            return None
        org = self.context["org"]
        if not Department.objects.filter(pk=value.pk, organization=org).exists():
            raise serializers.ValidationError(gettext("Unbekannte Untereinheit."))
        return value

    def validate(self, attrs):
        org = self.context["org"]
        name = attrs.get("name", getattr(self.instance, "name", "")).strip()
        unit = attrs.get("unit", getattr(self.instance, "unit", None))
        qs = Dignity.objects.filter(organization=org, unit=unit, name__iexact=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError({"name": gettext("Diese Würde gibt es schon.")})
        if "name" in attrs:
            attrs["name"] = name
        return attrs


class DignityViewSet(_HonorsMixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = DignitySerializer

    def get_queryset(self):
        return (
            Dignity.objects.filter(organization=self.org)
            .select_related("unit")
            .annotate(reign_count=Count("reigns"))
            .order_by("unit__sort_order", "unit__name", "sort_order", "name")
        )

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "org": getattr(self, "org", None)}

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}

    @action(detail=False, methods=["post"])
    def reorder(self, request, *args, **kwargs):
        """Reihenfolge der Würden einer Einheit (``unit``; leer: die Einheit selbst)."""
        unit = request.data.get("unit")
        if unit is not None and not isinstance(unit, int):
            raise ValidationError({"unit": gettext("Unbekannte Einheit.")})
        return reorder_response(
            request,
            self.org,
            Dignity.objects.filter(organization=self.org, unit_id=unit),
            "sort_order",
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        """Löschen; mit ``?mit_regentschaften=1`` samt allen Regentschaften (Ralf 2026-10-30)."""
        reigns = list(instance.reigns.all())
        if reigns and self.request.query_params.get("mit_regentschaften") != "1":
            raise ValidationError(
                gettext(
                    "Zu dieser Würde gibt es {x} Regentschaften. Bitte bestätigen, dass sie "
                    "mitgelöscht werden, oder „nicht mehr verwendet“ setzen."
                ).format(x=len(reigns))
            )
        for reign in reigns:
            record(self.org, self.request.user, "delete", reign, diff(snapshot(reign), {}))
            photo = getattr(reign, "photo", None)
            if photo is not None:
                _remove_photo(photo)
            reign.delete()
        record(self.org, self.request.user, "delete", instance, diff(snapshot(instance), {}))
        instance.delete()


# --- Regentschaften ---


class CompanionSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = Companion
        fields = ["id", "label", "person", "name", "display_name", "sort_order"]
        extra_kwargs = {"id": {"read_only": True}, "sort_order": {"required": False}}


def photo_data(org_id: int, reign: Reign) -> dict | None:
    photo = getattr(reign, "photo", None)
    if photo is None:
        return None
    base = f"/api/orgs/{org_id}/honors/reigns/{reign.pk}/photo/"
    return {"url": base, "small_url": f"{base}?size=small", "width": photo.width}


class ReignSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    period_text = serializers.CharField(read_only=True)
    dignity_name = serializers.CharField(source="dignity.name", read_only=True)
    companions = CompanionSerializer(many=True, required=False)
    photo = serializers.SerializerMethodField()
    ordinal_text = serializers.SerializerMethodField()
    numbered_name = serializers.SerializerMethodField()
    origin_text = serializers.CharField(read_only=True)

    class Meta:
        model = Reign
        fields = [
            "id",
            "dignity",
            "dignity_name",
            "year",
            "end_year",
            "valid_from",
            "valid_until",
            "period_text",
            "person",
            "name",
            "display_name",
            "ordinal",
            "ordinal_text",
            "numbered_name",
            "note",
            "origin",
            "origin_name",
            "origin_text",
            "companions",
            "photo",
        ]

    def get_photo(self, obj) -> dict | None:
        return photo_data(self.context["org"].pk, obj)

    def _ordinal(self, obj) -> int | None:
        """Wirksame Ordnungszahl; je Würde einmal für alle ihre Regentschaften berechnet."""
        if not obj.dignity.numbered:
            return None
        cache = self.context.setdefault("_ordinals", {})
        if obj.dignity_id not in cache:
            reigns = Reign.objects.filter(
                organization=self.context["org"], dignity_id=obj.dignity_id
            ).select_related("person")
            cache[obj.dignity_id] = numbering.ordinals(
                reigns, per_reign=obj.dignity.count_each_reign
            )
        return cache[obj.dignity_id].get(obj.pk)

    def get_ordinal_text(self, obj) -> str:
        number = self._ordinal(obj)
        return numbering.roman(number) if number else ""

    def get_numbered_name(self, obj) -> str:
        first, last = numbering.split_name(obj.person, obj.display_name)
        return numbering.numbered_name(first, last, self._ordinal(obj))

    def _check_person(self, person):
        if person is not None and person.pk not in self.context["people"]:
            raise serializers.ValidationError(gettext("Bitte ein Mitglied dieser Einheit wählen."))
        return person

    def validate_person(self, value):
        return self._check_person(value)

    def validate_dignity(self, value):
        if value.organization_id != self.context["org"].pk:
            raise serializers.ValidationError(gettext("Unbekannte Würde."))
        return value

    def validate_origin(self, value):
        if value is not None and value.pk not in {
            o.pk for o in origin_choices(self.context["org"])
        }:
            raise serializers.ValidationError(gettext("Bitte eine Einheit unterhalb wählen."))
        return value

    def validate_companions(self, value):
        for c in value:
            self._check_person(c.get("person"))
            if not c.get("person") and not (c.get("name") or "").strip():
                raise serializers.ValidationError(
                    gettext("Bitte für jede Begleitperson einen Namen.")
                )
        return value

    def validate(self, attrs):
        get = lambda k: attrs.get(k, getattr(self.instance, k, None))  # noqa: E731
        probe = Reign(
            organization=self.context["org"],
            year=get("year"),
            end_year=get("end_year"),
            valid_from=get("valid_from"),
            valid_until=get("valid_until"),
            person=get("person"),
            name=get("name") or "",
            ordinal=get("ordinal"),
        )
        try:
            probe.clean()
        except Exception as exc:  # noqa: BLE001
            raise serializers.ValidationError(getattr(exc, "message_dict", str(exc))) from exc
        person = get("person")
        if person is not None:
            # Name als Stand für die Chronik mitschreiben
            attrs["name"] = f"{person.first_name} {person.last_name}".strip()
        if attrs.get("origin") is not None:
            attrs["origin_name"] = ""
        elif "origin_name" in attrs:
            attrs["origin_name"] = attrs["origin_name"].strip()
        # Herkunft vorbelegen: Untereinheit, der das Mitglied angehört (nur beim Anlegen)
        if (
            self.instance is None
            and person is not None
            and "origin" not in attrs
            and not attrs.get("origin_name")
        ):
            attrs["origin"] = default_origin(self.context["org"], person)
        return attrs

    def _save_companions(self, reign: Reign, companions: list[dict] | None) -> None:
        if companions is None:
            return
        reign.companions.all().delete()
        for index, c in enumerate(companions):
            person = c.get("person")
            Companion.objects.create(
                organization=reign.organization,
                reign=reign,
                label=(c.get("label") or importer.DEFAULT_COMPANION).strip()[:60],
                person=person,
                name=(
                    f"{person.first_name} {person.last_name}".strip()
                    if person
                    else c.get("name", "").strip()
                ),
                sort_order=index,
            )

    def create(self, validated_data):
        companions = validated_data.pop("companions", [])
        reign = super().create(validated_data)
        self._save_companions(reign, companions)
        return reign

    def update(self, instance, validated_data):
        companions = validated_data.pop("companions", None)
        reign = super().update(instance, validated_data)
        self._save_companions(reign, companions)
        return reign


class ReignViewSet(_HonorsMixin, AuditMixin, viewsets.ModelViewSet):
    """?wuerde=<id> · ?person=<id> · ?jahr=<Jahr> · ?suche=<Text>"""

    serializer_class = ReignSerializer

    def get_queryset(self):
        qs = (
            Reign.objects.filter(organization=self.org)
            .select_related("dignity", "person", "photo", "origin")
            .prefetch_related("companions__person")
        )
        params = self.request.query_params
        if params.get("wuerde", "").isdigit():
            qs = qs.filter(dignity_id=int(params["wuerde"]))
        if params.get("person", "").isdigit():
            pid = int(params["person"])
            qs = qs.filter(Q(person_id=pid) | Q(companions__person_id=pid)).distinct()
        if params.get("jahr", "").isdigit():
            qs = qs.filter(year=int(params["jahr"]))
        if params.get("suche"):
            text = params["suche"].strip()
            qs = qs.filter(
                Q(name__icontains=text)
                | Q(companions__name__icontains=text)
                | Q(note__icontains=text)
            ).distinct()
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        org = getattr(self, "org", None)
        ctx["org"] = org
        if org is not None and self.request.method not in ("GET", "HEAD", "OPTIONS"):
            ctx["people"] = member_person_ids(org)
        return ctx

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}

    @transaction.atomic
    def perform_destroy(self, instance):
        record(self.org, self.request.user, "delete", instance, diff(snapshot(instance), {}))
        photo = getattr(instance, "photo", None)
        if photo is not None:
            _remove_photo(photo)
        instance.delete()


def _remove_photo(photo: ReignPhoto) -> None:
    files = [photo.file, photo.small]
    photo.delete()

    def _remove():
        for f in files:
            if f.name:
                f.storage.delete(f.name)

    transaction.on_commit(_remove)


class ReignPhotoView(_HonorsMixin, APIView):
    """GET: Foto · POST: Foto hochladen (ersetzt ein vorhandenes) · DELETE: entfernen."""

    parser_classes = [MultiPartParser, FormParser]

    def reign(self, pk: int) -> Reign:
        return get_object_or_404(Reign, organization=self.org, pk=pk)

    def get(self, request, org_id: int, pk: int):
        photo = get_object_or_404(ReignPhoto, reign=self.reign(pk))
        f = photo.small if request.query_params.get("size") == "small" else photo.file
        ctype = "image/png" if f.name.endswith(".png") else "image/jpeg"
        response = FileResponse(f.open("rb"), content_type=ctype)
        response["Cache-Control"] = "private, max-age=3600"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        from website.content import process_image

        reign = self.reign(pk)
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": gettext("Bitte ein Foto auswählen.")})
        full, ext, width, height, small, ext_small = process_image(upload)
        old = getattr(reign, "photo", None)
        if old is not None:
            _remove_photo(old)
        photo = ReignPhoto(
            organization=self.org,
            reign=reign,
            key=ReignPhoto.new_key(),
            width=width,
            height=height,
            uploaded_by=request.user,
        )
        photo.file.save(f"foto.{ext}", ContentFile(full), save=False)
        photo.small.save(f"foto-klein.{ext_small}", ContentFile(small), save=False)
        photo.save()
        record(self.org, request.user, "update", reign, {"Foto": [None, "hochgeladen"]})
        reign.photo = photo
        return Response(photo_data(self.org.pk, reign), status=status.HTTP_201_CREATED)

    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        reign = self.reign(pk)
        photo = getattr(reign, "photo", None)
        if photo is not None:
            _remove_photo(photo)
            record(self.org, request.user, "update", reign, {"Foto": ["vorhanden", None]})
        return Response(status=status.HTTP_204_NO_CONTENT)


class PeopleView(_HonorsMixin, APIView):
    """GET ?suche=: Mitglieder (auch ehemalige) für die Auswahl, mit Personennummer."""

    def get(self, request, org_id: int):
        term = request.query_params.get("suche", "").strip()
        if len(term) < 2:
            return Response([])
        qs = Membership.objects.filter(
            organization=self.org, purged_at__isnull=True
        ).select_related("person")
        for word in term.split()[:3]:
            qs = qs.filter(
                Q(person__first_name__icontains=word) | Q(person__last_name__icontains=word)
            )
        rows = qs.order_by("person__last_name", "person__first_name")[:10]
        return Response(
            [
                {
                    "id": m.person_id,
                    "first_name": m.person.first_name,
                    "last_name": m.person.last_name,
                    "birth_year": m.person.birth_date.year if m.person.birth_date else None,
                }
                for m in rows
            ]
        )


class OriginsView(_HonorsMixin, APIView):
    """GET: Einheiten zur Auswahl „aus“ bei einer Regentschaft."""

    def get(self, request, org_id: int):
        return Response([{"id": o.pk, "name": o.name} for o in origin_choices(self.org)])


# --- Weitergegebene Würden der Einheit darüber ---


class SharedView(_HonorsMixin, APIView):
    """GET: Würden, die die Einheit darüber (z. B. der Dachverband) an ihre Untereinheiten
    weitergibt, mit allen Regentschaften; nur lesend (Ralf 2026-10-31)."""

    def get(self, request, org_id: int):
        from core.tenancy import scope_of

        parent_id = scope_of(self.org.pk)
        if not parent_id or parent_id == self.org.pk:
            return Response([])
        owner = Organization.objects.filter(pk=parent_id).first()
        result = []
        dignities = Dignity.objects.filter(
            organization_id=parent_id, unit=None, share_down=True, is_archived=False
        )
        for dignity in dignities:
            # Nur die eigenen Träger (Herkunft = diese Einheit), Ralf 2026-10-31
            reigns = list(
                Reign.objects.filter(organization_id=parent_id, dignity=dignity, origin=self.org)
                .select_related("person")
                .prefetch_related("companions")
            )
            numbers = (
                numbering.ordinals(reigns, per_reign=dignity.count_each_reign)
                if dignity.numbered
                else {}
            )
            rows = []
            for r in reigns:
                first, last = numbering.split_name(r.person, r.display_name)
                rows.append(
                    {
                        "id": r.pk,
                        "period_text": r.period_text,
                        "year": r.sort_year,
                        "numbered_name": numbering.numbered_name(first, last, numbers.get(r.pk)),
                        "note": r.note,
                        "companions": [
                            {"label": c.label, "name": c.display_name} for c in r.companions.all()
                        ],
                    }
                )
            if not rows:
                continue
            result.append(
                {
                    "id": dignity.pk,
                    "name": dignity.name,
                    "owner": owner.name if owner else "",
                    "reigns": rows,
                }
            )
        return Response(result)


# --- Excel-Import ---


class ImportPreviewView(_HonorsMixin, APIView):
    """POST (Datei): Zeilen lesen und Mitglieder vorschlagen. Speichert nichts."""

    parser_classes = [MultiPartParser, FormParser]
    read_permission = MEMBERS_EDIT

    def post(self, request, org_id: int):
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": gettext("Bitte eine Datei auswählen.")})
        if upload.size > 5 * 1024 * 1024:
            raise ValidationError({"file": gettext("Die Datei darf höchstens 5 MB groß sein.")})
        suffix = Path(upload.name).suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            for chunk in upload.chunks():
                tmp.write(chunk)
            tmp.flush()
            result = importer.preview(self.org, tmp.name, upload.name)
        if result["error"]:
            raise ValidationError({"file": result["error"]})
        return Response(result)


class ImportCompanionSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=60, allow_blank=True, required=False)
    name = serializers.CharField(max_length=200, allow_blank=True, required=False)
    person_id = serializers.IntegerField(required=False, allow_null=True)


class ImportRowSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=1000, max_value=2999)
    end_year = serializers.IntegerField(
        min_value=1000, max_value=2999, required=False, allow_null=True
    )
    dignity = serializers.CharField(max_length=100)
    name = serializers.CharField(max_length=200, allow_blank=True, required=False)
    person_id = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(max_length=200, allow_blank=True, required=False)
    ordinal = serializers.IntegerField(min_value=1, max_value=3999, required=False, allow_null=True)
    origin = serializers.IntegerField(required=False, allow_null=True)
    origin_name = serializers.CharField(max_length=200, allow_blank=True, required=False)
    companions = ImportCompanionSerializer(many=True, required=False)


class ImportSerializer(serializers.Serializer):
    rows = ImportRowSerializer(many=True)

    def validate_rows(self, value):
        if len(value) > importer.MAX_ROWS:
            raise serializers.ValidationError(
                gettext("Höchstens {MAX_ROWS} Zeilen.").format(MAX_ROWS=importer.MAX_ROWS)
            )
        return value


class ImportView(_HonorsMixin, APIView):
    """POST (JSON): geprüfte Zeilen übernehmen; fehlende Würden werden angelegt."""

    @transaction.atomic
    def post(self, request, org_id: int):
        ser = ImportSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        # Dieselbe Übernahme erneut gesendet: nichts doppelt anlegen
        claim = idempotency.claim(request, f"honors.import.{self.org.pk}")
        if claim.done:
            return Response(claim.result, status=status.HTTP_200_OK)
        rows = ser.validated_data["rows"]
        people = member_person_ids(self.org)
        from members.models import Person

        persons = {p.pk: p for p in Person.objects.filter(pk__in=people)}
        dignities = {
            d.name.lower(): d for d in Dignity.objects.filter(organization=self.org, unit=None)
        }
        created_dignities = []
        created = 0
        origins = {o.pk: o for o in origin_choices(self.org)}

        def person_of(pid, line):
            if pid is None:
                return None
            if pid not in persons:
                raise ValidationError(
                    gettext("Zeile {line}: Das Mitglied gehört nicht zu dieser Einheit.").format(
                        line=line
                    )
                )
            return persons[pid]

        for line, row in enumerate(rows, start=1):
            if row.get("end_year") and row["end_year"] < row["year"]:
                raise ValidationError(
                    gettext("Zeile {line}: Das Endjahr liegt vor dem Startjahr.").format(line=line)
                )
            person = person_of(row.get("person_id"), line)
            if row.get("origin") and row["origin"] not in origins:
                raise ValidationError(
                    gettext("Zeile {line}: Unbekannte Einheit bei „aus“.").format(line=line)
                )
            name = (row.get("name") or "").strip()
            if person is None and not name:
                raise ValidationError(gettext("Zeile {line}: Name fehlt.").format(line=line))
            key = row["dignity"].strip().lower()
            dignity = dignities.get(key)
            if dignity is None:
                dignity = Dignity.objects.create(
                    organization=self.org,
                    name=row["dignity"].strip(),
                    sort_order=len(dignities),
                    # Erst intern: veröffentlicht wird nach bewusster Freigabe (UI-Audit NMF-11)
                    is_public=False,
                )
                dignities[key] = dignity
                created_dignities.append(dignity.name)
            reign = Reign.objects.create(
                organization=self.org,
                dignity=dignity,
                year=row["year"],
                end_year=row.get("end_year") if (row.get("end_year") or 0) > row["year"] else None,
                person=person,
                name=f"{person.first_name} {person.last_name}".strip() if person else name,
                note=(row.get("note") or "").strip(),
                ordinal=row.get("ordinal"),
                origin=origins.get(row.get("origin")),
                origin_name=""
                if origins.get(row.get("origin"))
                else (row.get("origin_name") or "").strip(),
            )
            for index, c in enumerate(row.get("companions") or []):
                cperson = person_of(c.get("person_id"), line)
                cname = (c.get("name") or "").strip()
                if cperson is None and not cname:
                    continue
                Companion.objects.create(
                    organization=self.org,
                    reign=reign,
                    label=(c.get("label") or importer.DEFAULT_COMPANION).strip(),
                    person=cperson,
                    name=f"{cperson.first_name} {cperson.last_name}".strip() if cperson else cname,
                    sort_order=index,
                )
            created += 1
        record(
            self.org,
            request.user,
            "create",
            self.org,
            {"Chronik (Import)": [None, f"{created} Regentschaften"]},
        )
        result = {"created": created, "dignities_created": created_dignities}
        claim.remember(result)
        return Response(result, status=status.HTTP_201_CREATED)
