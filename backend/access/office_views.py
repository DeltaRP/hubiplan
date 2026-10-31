"""Mitglieder › Ämter: Inhaber aller Rollen, frühere Inhaber erfassen und importieren.

Lesen: Mitglieder ansehen · Ändern: Mitglieder bearbeiten (wie bei den Würden).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.log import diff, record, snapshot
from changes import idempotency
from core.api_base import OrgScopedMixin
from members.models import Membership, Person
from organizations.models import Department, Organization

from . import offices
from .catalog import MEMBERS_EDIT, MEMBERS_VIEW
from .models import Role


class _OfficesMixin(OrgScopedMixin):
    allowed_org_types = (Organization.Type.CLUB, Organization.Type.FEDERATION)
    read_permission = MEMBERS_VIEW
    write_permission = MEMBERS_EDIT


def _person(org, person_id):
    """Mitgliedsakte (auch ehemaliges Mitglied) der Einheit oder Fehler."""
    if person_id is None:
        return None
    ok = Membership.objects.filter(
        organization=org, person_id=person_id, purged_at__isnull=True
    ).exists()
    if not ok:
        raise ValidationError({"person": "Das Mitglied gehört nicht zu dieser Einheit."})
    return Person.objects.get(pk=person_id)


class EntrySerializer(serializers.Serializer):
    role = serializers.IntegerField()
    name = serializers.CharField(max_length=offices.NAME_MAX, allow_blank=True, required=False)
    person = serializers.IntegerField(required=False, allow_null=True)
    from_year = serializers.IntegerField()
    until_year = serializers.IntegerField()

    def validate(self, attrs):
        if message := offices.check_years(attrs["from_year"], attrs["until_year"]):
            raise ValidationError({"until_year": message})
        if not (attrs.get("name") or "").strip() and attrs.get("person") is None:
            raise ValidationError({"name": "Bitte einen Namen eintragen."})
        return attrs


class OfficesView(_OfficesMixin, APIView):
    """GET: alle Rollen mit heutigen und früheren Inhabern (jahresgenau).
    POST: früheren Inhaber eintragen."""

    def get(self, request, org_id: int):
        return Response(offices.overview(self.org))

    @transaction.atomic
    def post(self, request, org_id: int):
        ser = EntrySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        role = get_object_or_404(offices.roles_of(self.org), pk=d["role"])
        entry = offices.create_entry(
            role,
            name=d.get("name") or "",
            person=_person(self.org, d.get("person")),
            from_year=d["from_year"],
            until_year=d["until_year"],
        )
        record(
            self.org,
            request.user,
            "create",
            entry,
            diff({}, snapshot(entry)),
            person=entry.person,
        )
        return Response(offices.holder_entry(entry), status=status.HTTP_201_CREATED)


class OfficeEntryView(_OfficesMixin, APIView):
    """PUT: freien Eintrag ändern · DELETE: löschen. Nur freie Einträge früherer
    Inhaber; Konten und Mitglieder ändert man unter Rollen bzw. in der Akte."""

    def entry(self, pk: int):
        return get_object_or_404(
            offices.former_entries(self.org)
            .select_for_update(of=("self",))
            .select_related("person"),
            pk=pk,
        )

    @transaction.atomic
    def put(self, request, org_id: int, pk: int):
        entry = self.entry(pk)
        ser = EntrySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        before = snapshot(entry)
        entry.role = get_object_or_404(offices.roles_of(self.org), pk=d["role"])
        entry.person = _person(self.org, d.get("person"))
        name = (d.get("name") or "").strip()
        if entry.person is not None:
            name = f"{entry.person.first_name} {entry.person.last_name}".strip() or name
        entry.name = name
        entry.valid_from = offices.year_start(d["from_year"])
        entry.valid_until = offices.year_start(d["until_year"])
        entry.save()
        record(
            self.org,
            request.user,
            "update",
            entry,
            diff(before, snapshot(entry)),
            person=entry.person,
        )
        return Response(offices.holder_entry(entry))

    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        entry = self.entry(pk)
        record(
            self.org,
            request.user,
            "delete",
            entry,
            diff(snapshot(entry), {}),
            person=entry.person,
        )
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ImportPreviewView(_OfficesMixin, APIView):
    """POST (Datei): Zeilen lesen und Mitglieder vorschlagen. Speichert nichts."""

    parser_classes = [MultiPartParser, FormParser]
    read_permission = MEMBERS_EDIT

    def post(self, request, org_id: int):
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Bitte eine Datei auswählen."})
        if upload.size > 5 * 1024 * 1024:
            raise ValidationError({"file": "Die Datei darf höchstens 5 MB groß sein."})
        suffix = Path(upload.name).suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            for chunk in upload.chunks():
                tmp.write(chunk)
            tmp.flush()
            result = offices.preview(self.org, tmp.name, upload.name)
        if result["error"]:
            raise ValidationError({"file": result["error"]})
        return Response(result)


class ImportRowSerializer(serializers.Serializer):
    role = serializers.CharField(max_length=100)
    unit_id = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField(max_length=offices.NAME_MAX, allow_blank=True, required=False)
    person_id = serializers.IntegerField(required=False, allow_null=True)
    from_year = serializers.IntegerField()
    until_year = serializers.IntegerField()


class ImportSerializer(serializers.Serializer):
    rows = ImportRowSerializer(many=True)

    def validate_rows(self, value):
        if len(value) > offices.MAX_ROWS:
            raise serializers.ValidationError(f"Höchstens {offices.MAX_ROWS} Zeilen.")
        return value


class ImportView(_OfficesMixin, APIView):
    """POST (JSON): geprüfte Zeilen übernehmen. Fehlende Ämter werden als Rollen ohne
    Rechte angelegt, zunächst nicht auf der Webseite (bewusst freigeben)."""

    @transaction.atomic
    def post(self, request, org_id: int):
        ser = ImportSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        claim = idempotency.claim(request, f"offices.import.{self.org.pk}")
        if claim.done:
            return Response(claim.result, status=status.HTTP_200_OK)
        roles = {(r.name.strip().lower(), r.department_id): r for r in offices.roles_of(self.org)}
        units = {d.pk: d for d in Department.objects.filter(organization=self.org)}
        created_roles: list[str] = []
        created = 0
        for line, row in enumerate(ser.validated_data["rows"], start=1):
            if message := offices.check_years(row["from_year"], row["until_year"]):
                raise ValidationError(f"Zeile {line}: {message}")
            unit_id = row.get("unit_id")
            if unit_id is not None and unit_id not in units:
                raise ValidationError(f"Zeile {line}: Unbekannte Untereinheit.")
            try:
                person = _person(self.org, row.get("person_id"))
            except ValidationError:
                raise ValidationError(
                    f"Zeile {line}: Das Mitglied gehört nicht zu dieser Einheit."
                ) from None
            name = (row.get("name") or "").strip()
            if person is None and not name:
                raise ValidationError(f"Zeile {line}: Name fehlt.")
            key = (row["role"].strip().lower(), unit_id)
            role = roles.get(key)
            if role is None:
                role = Role(
                    organization=self.org,
                    department=units[unit_id] if unit_id else None,
                    name=row["role"].strip(),
                    is_board=False,
                    permissions=[],
                    in_chronicle=False,
                )
                role.save()
                roles[key] = role
                created_roles.append(
                    f"{role.name} ({units[unit_id].name})" if unit_id else role.name
                )
                record(self.org, request.user, "create", role, diff({}, snapshot(role)))
            entry = offices.create_entry(
                role,
                name=name,
                person=person,
                from_year=row["from_year"],
                until_year=row["until_year"],
            )
            record(
                self.org,
                request.user,
                "create",
                entry,
                diff({}, snapshot(entry)),
                person=entry.person,
            )
            created += 1
        result = {"created": created, "roles_created": created_roles}
        claim.remember(result)
        return Response(result, status=status.HTTP_201_CREATED)
