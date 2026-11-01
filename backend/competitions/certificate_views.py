"""Urkundenvorlagen, Urkunden und Startkarten (Wettbewerbe Schritt 6)."""

from __future__ import annotations

import datetime
import io
import re

from django.core.files.base import ContentFile
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from PIL import Image, UnidentifiedImageError
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.log import record
from core.api_base import AuditMixin

from . import certificates
from .models import CertificateTemplate, Competition
from .views import _Mixin

# Hintergrund: A4 mit 200 dpi reicht für den Druck
BACKGROUND_MAX_SIDE = 2400
BACKGROUND_MAX_BYTES = 10 * 1024 * 1024


class CertificateTemplateSerializer(serializers.ModelSerializer):
    has_background = serializers.SerializerMethodField()

    class Meta:
        model = CertificateTemplate
        fields = [
            "id",
            "name",
            "heading",
            "text",
            "landscape",
            "show_logo",
            "place_line",
            "signers",
            "has_background",
        ]

    def get_has_background(self, obj) -> bool:
        return bool(obj.background)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(gettext("Bitte einen Namen angeben."))
        return value

    def validate_signers(self, value):
        if not isinstance(value, list) or len(value) > 2:
            raise serializers.ValidationError(gettext("Höchstens zwei Unterschriften."))
        out = []
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError(gettext("Ungültige Angabe."))
            name = str(item.get("name") or "").strip()[:80]
            function = str(item.get("function") or "").strip()[:80]
            if name or function:
                out.append({"name": name, "function": function})
        return out


class CertificateTemplateViewSet(_Mixin, AuditMixin, viewsets.ModelViewSet):
    serializer_class = CertificateTemplateSerializer

    def get_queryset(self):
        return CertificateTemplate.objects.filter(organization=self.org)

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}

    def perform_destroy(self, instance):
        files = [instance.background] if instance.background else []
        super().perform_destroy(instance)
        _delete_later(files)


def _delete_later(files) -> None:
    names = [(f.storage, f.name) for f in files if f and f.name]

    def _remove():
        for storage, name in names:
            storage.delete(name)

    transaction.on_commit(_remove)


def clean_background(upload) -> bytes:
    """Prüft das Bild und schreibt es als JPEG ohne Metadaten neu (höchstens 2400 px)."""
    from organizations.homepage_preview import FORMATS, MAX_PIXELS

    if upload.size > BACKGROUND_MAX_BYTES:
        raise ValidationError({"file": gettext("Das Bild darf höchstens 10 MB groß sein.")})
    content = upload.read()
    try:
        probe = Image.open(io.BytesIO(content))
        if probe.format not in FORMATS:
            raise ValidationError({"file": gettext("Bitte PNG, JPG oder WebP hochladen.")})
        if probe.width * probe.height > MAX_PIXELS:
            raise ValidationError({"file": gettext("Das Bild hat zu viele Pixel.")})
        probe.verify()
        img = Image.open(io.BytesIO(content))
        img.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError({"file": gettext("Die Datei ist kein gültiges Bild.")}) from exc
    if img.mode in ("RGBA", "LA", "P", "PA"):
        rgba = img.convert("RGBA")
        img = Image.new("RGB", rgba.size, (255, 255, 255))
        img.paste(rgba, mask=rgba.getchannel("A"))
    else:
        img = img.convert("RGB")
    img.thumbnail((BACKGROUND_MAX_SIDE, BACKGROUND_MAX_SIDE), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88, optimize=True)
    return buf.getvalue()


class CertificateBackgroundView(_Mixin, APIView):
    """POST (Datei ``file``): Hintergrundbild der Vorlage · DELETE: entfernen."""

    parser_classes = [MultiPartParser, FormParser]

    def template(self, pk) -> CertificateTemplate:
        return get_object_or_404(CertificateTemplate, pk=pk, organization=self.org)

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        tpl = self.template(pk)
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": gettext("Bitte ein Bild auswählen.")})
        data = clean_background(upload)
        old = [tpl.background] if tpl.background else []
        tpl.background.save("hintergrund.jpg", ContentFile(data), save=False)
        tpl.save(update_fields=["background", "updated_at"])
        _delete_later(old)
        record(self.org, request.user, "update", tpl, {"Hintergrundbild": [None, "hochgeladen"]})
        return Response(CertificateTemplateSerializer(tpl).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        tpl = self.template(pk)
        if tpl.background:
            old = [tpl.background]
            tpl.background = ""
            tpl.save(update_fields=["background", "updated_at"])
            _delete_later(old)
            record(self.org, request.user, "update", tpl, {"Hintergrundbild": ["vorhanden", None]})
        return Response(CertificateTemplateSerializer(tpl).data)


def _pdf(body: bytes, name: str) -> HttpResponse:
    resp = HttpResponse(body, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{name}.pdf"'
    resp["Cache-Control"] = "private, no-store"
    return resp


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9ÄÖÜäöüß_-]+", "-", text).strip("-") or "Wettbewerb"


class CertificatePreviewView(_Mixin, APIView):
    """GET: Probeurkunde der Vorlage mit erfundenen Werten."""

    manage_only = False

    def get(self, request, org_id: int, pk: int):
        tpl = get_object_or_404(CertificateTemplate, pk=pk, organization=self.org)
        comp = Competition(
            organization=self.org,
            title="Vereinsmeisterschaft",
            date=datetime.date.today(),
            location=tpl.place_line or "Musterstadt",
        )
        values = {
            "wettbewerb": comp.title,
            "datum": f"{comp.date:%d.%m.%Y}",
            "jahr": str(comp.date.year),
            "ort": comp.location,
            "verein": self.org.name,
            "name": "Max Muster",
            "einheit": "Zug 1",
            "platz": "1",
            "wertung": "Einzelwertung",
            "wert": "48",
            "mit_wert": " mit 48",
            "titel": f"Vereinsmeister {comp.date.year}",
            "preis": "",
        }
        body = certificates.certificates_pdf(comp, tpl, [certificates.Recipient(values)])
        return _pdf(body, "Probeurkunde")


class CertificatesView(_Mixin, APIView):
    """GET ?vorlage=&bis=3&wertung=&starter=&unterschrift=1: Urkunden aller Platzierten als
    PDF. ``unterschrift=1`` setzt die hinterlegte Unterschrift dessen ein, der die Urkunden
    erzeugt (Mein Konto › Unterschrift), über die erste Unterschriftszeile."""

    manage_only = False

    def get(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        q = request.query_params
        tpl_id = q.get("vorlage") or comp.certificate_template_id
        tpl = (
            get_object_or_404(CertificateTemplate, pk=tpl_id, organization=self.org)
            if tpl_id
            else None
        )
        try:
            up_to = max(1, min(int(q.get("bis", 3)), 100))
            scoring = int(q["wertung"]) if q.get("wertung") else None
            starter = int(q["starter"]) if q.get("starter") else None
        except ValueError:
            raise ValidationError(gettext("Ungültige Angabe.")) from None
        items = certificates.recipients(comp, up_to=up_to, scoring=scoring, starter=starter)
        signature = None
        if q.get("unterschrift") == "1":
            from accounts.models import StoredSignature

            stored = StoredSignature.objects.filter(user=request.user).first()
            if stored is None:
                raise ValidationError(
                    gettext("Unter Mein Konto › Unterschrift ist keine Unterschrift hinterlegt.")
                )
            signature = stored.strokes
        body = certificates.certificates_pdf(comp, tpl, items, signature=signature)
        return _pdf(body, f"Urkunden-{_slug(comp.title)}")


class StartCardsView(_Mixin, APIView):
    """GET ?art=karten|aufkleber&sortierung=name|einheit|startnummer: Startkarten als PDF."""

    manage_only = False

    def get(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        labels = request.query_params.get("art") == "aufkleber"
        order = request.query_params.get("sortierung", "name")
        body = certificates.start_cards_pdf(comp, order=order, labels=labels)
        return _pdf(body, f"Startkarten-{_slug(comp.title)}")
