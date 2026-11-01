"""Briefbogen pflegen und Briefvorlagen erzeugen."""

from __future__ import annotations

from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import DOCS_MANAGE, ORG_EDIT
from audit.log import diff, record, snapshot
from core.api_base import ModelCleanMixin, OrgScopedMixin
from organizations.models import Department, Organization

from . import data as service
from . import docx, preview
from .models import Letterhead, LetterheadChoice

EDIT_FIELDS = [
    "mode",
    "form",
    "logo_position",
    "tagline",
    "font",
    "salutation",
    "closing",
    "show_bank",
    "account",
    "show_email",
    "show_phone",
    "show_website",
    "show_board",
    "show_register",
    "show_social",
]

MAX_SIGNATURE_BYTES = 1_000_000


class LetterheadSerializer(ModelCleanMixin, serializers.ModelSerializer):
    account = serializers.IntegerField(source="account_id", allow_null=True, required=False)

    class Meta:
        model = Letterhead
        fields = [*EDIT_FIELDS, "updated_at"]
        read_only_fields = ["updated_at"]

    def validate_mode(self, value):
        org = self.instance.organization if self.instance else None
        if value == Letterhead.Mode.INHERIT and org is not None and org.type != "unit":
            raise serializers.ValidationError(
                gettext("Nur Untereinheiten übernehmen einen Briefbogen.")
            )
        if value == Letterhead.Mode.OWN and org is not None and not service.may_have_own(org):
            raise serializers.ValidationError(
                gettext("Einen eigenen Briefbogen gibt es nur mit eigenem Arbeitsbereich.")
            )
        return value

    def validate_account(self, value):
        # Konten liegen im Datenbereich der Einheit; gewählt werden darf nur ein eigenes
        if value is None:
            return value
        org = self.instance.organization
        if value not in {a["id"] for a in service.bank_accounts(org)}:
            raise serializers.ValidationError(
                gettext("Bitte ein aktives Bankkonto mit IBAN wählen.")
            )
        return value


def _hints(owner: Organization, letter: service.LetterData) -> list[str]:
    hints = []
    lh = letter.settings
    if lh.show_bank and letter.bank is None:
        hints.append("Es gibt kein aktives Bankkonto mit IBAN (Finanzen › Konten).")
    if lh.show_board and not letter.board:
        hints.append(
            "Niemand hat eine Rolle mit „vertritt die Einheit“ oder „auf dem Briefbogen nennen“."
        )
    if lh.show_social and not letter.social:
        hints.append(
            "Es sind keine Social-Media-Kanäle eingetragen (Einstellungen › Organisation)."
        )
    if lh.logo_position != Letterhead.LogoPosition.NONE and not letter.logo:
        hints.append("Es ist kein Logo/Wappen hinterlegt (Einstellungen › Erscheinungsbild).")
    if not (owner.street and owner.city):
        hints.append("Die Anschrift ist unvollständig.")
    return hints


def _state(org: Organization) -> dict:
    letterhead = service.ensure(org)
    owner, _ = service.owner_of(org)
    letter = service.letter_data(org)
    return {
        "organization": {"id": org.pk, "name": org.name, "type": org.type},
        "letterhead": LetterheadSerializer(letterhead).data,
        "may_have_own": service.may_have_own(org),
        "owner": {"id": owner.pk, "name": owner.name, "is_self": owner.pk == org.pk},
        "accounts": service.bank_accounts(owner),
        "board": letter.board,
        "hints": _hints(owner, letter),
    }


def _update(request, org: Organization, audit_org: Organization) -> dict:
    letterhead = service.ensure(org)
    serializer = LetterheadSerializer(letterhead, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        before = snapshot(letterhead)
        obj = serializer.save()
        changes = diff(before, snapshot(obj))
        if changes:
            record(audit_org, request.user, "update", obj, changes)
    return _state(org)


def _file(content: bytes, name: str, content_type: str, inline: bool = False) -> HttpResponse:
    response = HttpResponse(content, content_type=content_type)
    disposition = "inline" if inline else "attachment"
    response["Content-Disposition"] = f'{disposition}; filename="{name}"'
    response["Cache-Control"] = "no-store"
    return response


class _OrgLetterheadMixin(OrgScopedMixin):
    """Briefbogen einer Einheit und ihrer Untereinheiten (lesen: jede Rolle)."""

    write_permission = ORG_EDIT
    allowed_org_types = (Organization.Type.FEDERATION, Organization.Type.CLUB)

    def target(self, unit_id) -> Organization:
        if not unit_id:
            return self.org
        try:
            pk = int(unit_id)
        except (TypeError, ValueError):
            raise NotFound() from None
        return get_object_or_404(Department, pk=pk, organization=self.org)


class OrgLetterheadView(_OrgLetterheadMixin, APIView):
    def get(self, request, org_id: int):
        return Response(_state(self.org))

    def patch(self, request, org_id: int):
        return Response(_update(request, self.org, self.org))


class UnitLetterheadView(_OrgLetterheadMixin, APIView):
    def get(self, request, org_id: int, unit_id: int):
        return Response(_state(self.target(unit_id)))

    def patch(self, request, org_id: int, unit_id: int):
        return Response(_update(request, self.target(unit_id), self.org))


class OrgLetterheadPreviewView(_OrgLetterheadMixin, APIView):
    """Vorschau (PDF) der neutralen Vorlage, ohne persönlichen Teil."""

    def get(self, request, org_id: int):
        unit = self.target(request.query_params.get("unit"))
        pdf = preview.render(service.letter_data(unit))
        return _file(pdf, "vorschau.pdf", "application/pdf", inline=True)


class OrgLetterheadDownloadView(_OrgLetterheadMixin, APIView):
    """Neutrale Vorlage (ohne persönlichen Teil) herunterladen."""

    def get(self, request, org_id: int):
        unit = self.target(request.query_params.get("unit"))
        fmt = request.query_params.get("type", "dotx")
        if fmt not in docx.MIME:
            raise serializers.ValidationError({"type": gettext("Bitte dotx oder docx wählen.")})
        letter = service.letter_data(unit)
        return _file(docx.build(letter, fmt), docx.filename(letter, fmt), docx.MIME[fmt])


class PublishSerializer(serializers.Serializer):
    folder = serializers.IntegerField()
    format = serializers.ChoiceField(choices=["dotx", "docx"], default="dotx")
    unit = serializers.IntegerField(required=False, allow_null=True)


class OrgLetterheadPublishView(_OrgLetterheadMixin, APIView):
    """Neutrale Vorlage in der Dokumentenablage ablegen (neue Fassung, falls vorhanden)."""

    def post(self, request, org_id: int):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from documents import services as doc_services
        from documents.models import Document, Folder
        from documents.views import _save_version

        if DOCS_MANAGE not in self.org_permissions:
            raise PermissionDenied(
                gettext("Dafür fehlt dir die Berechtigung für die Dokumentenablage.")
            )
        params = PublishSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        unit = self.target(params.validated_data.get("unit"))
        folder = Folder.objects.filter(
            organization=self.org, pk=params.validated_data["folder"], department__isnull=True
        ).first()
        if folder is None:
            raise serializers.ValidationError({"folder": gettext("Diesen Ordner gibt es nicht.")})
        fmt = params.validated_data["format"]
        letter = service.letter_data(unit)
        name = docx.filename(letter, fmt)
        upload = SimpleUploadedFile(name, docx.build(letter, fmt), content_type=docx.MIME[fmt])
        viewer = doc_services.org_viewer(self.org, self.org_permissions)
        title = f"Briefvorlage {unit.name}"
        with transaction.atomic():
            doc = Document.objects.filter(
                organization=self.org, folder=folder, title=title, deleted_at__isnull=True
            ).first()
            created = doc is None
            if created:
                doc = Document.objects.create(
                    organization=self.org,
                    folder=folder,
                    title=title,
                    date=timezone.localdate(),
                    note="Aus HUBIplan erzeugt (ohne persönliche Angaben).",
                    created_by=request.user,
                )
            _save_version(viewer, doc, upload, request.user)
            record(
                self.org,
                request.user,
                "create" if created else "update",
                doc,
                {"Dokument": [None, f"{title} ({folder.name})"]},
            )
        return Response({"document": doc.pk, "title": title, "created": created}, status=201)


# --- Persönliche Vorlage ---


def _context_data(user, ctx: service.SenderContext) -> dict:
    own = service.own_contact(user, ctx)
    return {
        "key": ctx.key,
        "organization": {"id": ctx.org.pk, "name": ctx.org.name, "type": ctx.org.type},
        "units": [
            {
                "id": u.pk,
                "name": u.name,
                "is_self": u.pk == ctx.org.pk,
                "contact": service.unit_contact(u),
            }
            for u in ctx.units()
        ],
        "functions": [
            {"key": f.key, "name": f.name, "contact_email": f.contact_email} for f in ctx.functions
        ],
        "name": service.user_name(user, ctx),
        "own": {
            "email": own["email"],
            "phone": own["phone"],
            "address": own["address"],
        },
    }


def _choice_data(choice: LetterheadChoice) -> dict:
    return {
        "unit": choice.unit_id,
        "context": choice.context,
        "function": choice.function,
        "function_text": choice.function_text,
        "title": choice.title,
        "contacts": choice.contacts,
        "with_logo": choice.with_logo,
        "format": choice.file_format,
        "downloaded_at": choice.downloaded_at,
    }


def _sender_for_choice(user, ctx, unit, choice: LetterheadChoice) -> service.Sender:
    return service.build_sender(
        user,
        ctx,
        unit,
        choice.function,
        choice.function_text,
        choice.title,
        [c for c in choice.contacts if c in service.CONTACT_KEYS],
    )


def notices(user, contexts: list[service.SenderContext]) -> list[dict]:
    """Hinweise: Vorlage veraltet, neue Funktion ohne Vorlage."""
    by_key = {c.key: c for c in contexts}
    choices = {c.unit_id: c for c in LetterheadChoice.objects.filter(user=user)}
    result = []
    for choice in choices.values():
        if choice.downloaded_at is None or choice.hint_dismissed:
            continue
        ctx = by_key.get(choice.context)
        if ctx is None:
            continue
        unit = next((u for u in ctx.units() if u.pk == choice.unit_id), None)
        if unit is None:
            continue
        letter = service.letter_data(
            unit, choice.with_logo, _sender_for_choice(user, ctx, unit, choice)
        )
        changes = service.changed_sections(choice.checksums, service.checksums(letter))
        if changes:
            result.append(
                {
                    "kind": "outdated",
                    "unit": {"id": unit.pk, "name": unit.name},
                    "context": ctx.key,
                    "changes": changes,
                }
            )
    today = timezone.localdate()
    for ctx in contexts:
        if ctx.org.pk in choices:
            continue
        newest = max(f.since for f in ctx.functions)
        if (today - newest).days <= service.NEW_FUNCTION_DAYS:
            result.append(
                {
                    "kind": "new",
                    "unit": {"id": ctx.org.pk, "name": ctx.org.name},
                    "context": ctx.key,
                    "function": ctx.functions[-1].name,
                }
            )
    return result


class RequestSerializer(serializers.Serializer):
    context = serializers.CharField()
    unit = serializers.IntegerField()
    function = serializers.CharField()
    function_text = serializers.CharField(required=False, allow_blank=True, max_length=150)
    title = serializers.CharField(required=False, allow_blank=True, max_length=30)
    contacts = serializers.CharField(required=False, allow_blank=True)
    with_logo = serializers.BooleanField(required=False, default=True)
    format = serializers.ChoiceField(choices=["dotx", "docx"], default="dotx")
    signature = serializers.ImageField(required=False, allow_null=True)

    def validate_contacts(self, value: str) -> list[str]:
        items = [v.strip() for v in (value or "").split(",") if v.strip()]
        unknown = [v for v in items if v not in service.CONTACT_KEYS]
        if unknown:
            raise serializers.ValidationError(gettext("Unbekannter Kontaktweg."))
        return items

    def validate_signature(self, value):
        if value is not None and value.size > MAX_SIGNATURE_BYTES:
            raise serializers.ValidationError(gettext("Die Unterschrift ist größer als 1 MB."))
        return value


class _PersonalMixin:
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def resolve(self, request):
        params = RequestSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        v = params.validated_data
        ctx = next((c for c in service.contexts_for(request.user) if c.key == v["context"]), None)
        if ctx is None:
            raise NotFound(gettext("Dafür hast du keine passende Funktion."))
        unit = next((u for u in ctx.units() if u.pk == v["unit"]), None)
        if unit is None:
            raise NotFound()
        if not any(f.key == v["function"] for f in ctx.functions):
            raise serializers.ValidationError(
                {"function": gettext("Bitte eine deiner Funktionen wählen.")}
            )
        signature = None
        if v.get("signature"):
            signature = v["signature"].read()
            if docx.load_picture(signature, "unterschrift") is None:
                raise serializers.ValidationError(
                    {"signature": gettext("Das ist kein lesbares Bild.")}
                )
        contacts = list(v.get("contacts") or [])
        sender = service.build_sender(
            request.user,
            ctx,
            unit,
            v["function"],
            v.get("function_text", ""),
            v.get("title", ""),
            contacts,
            signature,
        )
        letter = service.letter_data(unit, v["with_logo"], sender)
        return ctx, unit, v, contacts, letter


class MyLetterheadsView(APIView):
    def get(self, request):
        contexts = service.contexts_for(request.user)
        choices = LetterheadChoice.objects.filter(user=request.user)
        return Response(
            {
                "contexts": [_context_data(request.user, c) for c in contexts],
                "choices": [_choice_data(c) for c in choices],
                "notices": notices(request.user, contexts),
            }
        )


class MyLetterheadPreviewView(_PersonalMixin, APIView):
    def post(self, request):
        _ctx, _unit, _v, _contacts, letter = self.resolve(request)
        return _file(preview.render(letter), "vorschau.pdf", "application/pdf", inline=True)


class MyLetterheadDownloadView(_PersonalMixin, APIView):
    def post(self, request):
        ctx, unit, v, contacts, letter = self.resolve(request)
        fmt = v["format"]
        content = docx.build(letter, fmt)
        # Die Wahl merken (ohne Unterschrift und ohne Inhalte), dazu Prüfwerte
        LetterheadChoice.objects.update_or_create(
            user=request.user,
            unit=unit,
            defaults={
                "context": ctx.key,
                "function": v["function"],
                "function_text": v.get("function_text", ""),
                "title": v.get("title", ""),
                "contacts": contacts,
                "with_logo": v["with_logo"],
                "file_format": fmt,
                "checksums": service.checksums(letter),
                "downloaded_at": timezone.now(),
                "hint_dismissed": False,
            },
        )
        return _file(content, docx.filename(letter, fmt), docx.MIME[fmt])


class DismissSerializer(serializers.Serializer):
    unit = serializers.IntegerField()
    context = serializers.CharField()


class MyLetterheadDismissView(APIView):
    """Hinweis ausblenden („später“): bis sich wieder etwas ändert."""

    def post(self, request):
        params = DismissSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        v = params.validated_data
        ctx = next((c for c in service.contexts_for(request.user) if c.key == v["context"]), None)
        unit = next((u for u in ctx.units() if u.pk == v["unit"]), None) if ctx else None
        if unit is None:
            raise NotFound()
        choice = LetterheadChoice.objects.filter(user=request.user, unit=unit).first()
        if choice is None:
            LetterheadChoice.objects.create(
                user=request.user,
                unit=unit,
                context=ctx.key,
                function=ctx.functions[0].key,
                hint_dismissed=True,
            )
        elif choice.downloaded_at is not None and choice.context == ctx.key:
            # Veraltet zur Kenntnis genommen: neuer Stand gilt als gesehen
            letter = service.letter_data(
                unit, choice.with_logo, _sender_for_choice(request.user, ctx, unit, choice)
            )
            choice.checksums = service.checksums(letter)
            choice.save(update_fields=["checksums", "updated_at"])
        return Response(status=204)
