"""Verwaltung der Inhalte der Webseite (Recht „Inhalte der Webseite bearbeiten“)."""

from __future__ import annotations

from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import WEBSITE_CONTENT, WEBSITE_MANAGE
from audit.log import diff, record, snapshot
from core.api_base import ModelCleanMixin
from core.reorder import reorder_response

from . import content, services
from .content_models import WebsiteImage, WebsiteRevision, WebsiteText
from .views import _WebsiteMixin


class _ContentMixin(_WebsiteMixin):
    """Lesen und Ändern: Inhalte bearbeiten oder Webseite verwalten."""

    write_permission = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not (
            {WEBSITE_CONTENT, WEBSITE_MANAGE} & self.org_permissions
        ):
            raise NotFound()


def image_data(org_id: int, image: WebsiteImage | None, used: bool | None = None) -> dict | None:
    if image is None:
        return None
    base = f"/api/orgs/{org_id}/website/images/{image.pk}/file/?v={image.version}"
    data = {
        "id": image.pk,
        "key": image.key,
        "caption": image.caption,
        "alt_text": image.alt_text,
        "decorative": image.decorative,
        "width": image.width,
        "height": image.height,
        "url": base,
        "small_url": f"{base}&size=small",
        "original_url": f"{base}&size=original",
        "markdown": f"![{image.alt_text or image.caption}](bild:{image.key})",
        "department": image.department_id,
        "department_name": (image.department.short_name or image.department.name)
        if image.department_id
        else None,
        "crop": image.crop or {},
        "version": image.version,
        "uploaded_at": image.uploaded_at,
        "updated_at": image.updated_at,
    }
    if used is not None:
        data["used"] = used
    return data


def text_data(org_id: int, t: WebsiteText, full: bool = False) -> dict:
    data = {
        "id": t.pk,
        "kind": t.kind,
        "kind_label": t.get_kind_display(),
        "department": t.department_id,
        "department_name": t.department.name if t.department_id else None,
        "slug": t.slug,
        "menu_position": t.menu_position,
        "show_in_menu": t.show_in_menu,
        "title": t.title,
        "is_published": t.is_published,
        "has_changes": t.has_changes,
        "published_at": t.published_at,
        "updated_at": t.updated_at,
    }
    if full:
        data.update(
            {
                "body": t.body,
                "image": t.image_id,
                "image_data": image_data(org_id, t.image),
                "gallery": list(t.gallery or []),
                "gallery_interval": t.gallery_interval,
                "published_title": t.published_title,
                "published_body": t.published_body,
                "revisions": [
                    {
                        "id": r.pk,
                        "title": r.title,
                        "published_at": r.published_at,
                        "published_by": (r.published_by.get_full_name() or r.published_by.email)
                        if r.published_by
                        else "",
                    }
                    for r in t.revisions.select_related("published_by")[:20]
                ],
            }
        )
    return data


MAX_GALLERY = 10  # Ralf: bis zu 10 Fotos je Einheit


class TextSerializer(ModelCleanMixin, serializers.ModelSerializer):
    class Meta:
        model = WebsiteText
        fields = [
            "kind",
            "department",
            "slug",
            "menu_position",
            "show_in_menu",
            "title",
            "body",
            "image",
            "gallery",
            "gallery_interval",
        ]
        extra_kwargs = {"kind": {"required": False}}

    def extra_clean_attrs(self) -> dict:
        return {"website": self.context["website"]}

    def validate_kind(self, value):
        if self.instance is not None and value != self.instance.kind:
            raise serializers.ValidationError("Die Art eines Textes lässt sich nicht ändern.")
        if self.instance is None and value == WebsiteText.Kind.GREETING:
            raise serializers.ValidationError("Die Begrüßung gibt es schon.")
        return value

    def validate_department(self, value):
        if value is not None and not (
            services.units_below(self.context["website"].organization).filter(pk=value.pk).exists()
        ):
            raise serializers.ValidationError("Unbekannte Untereinheit.")
        return value

    def validate_gallery(self, value):
        if not isinstance(value, list) or not all(
            isinstance(v, int) and not isinstance(v, bool) for v in value
        ):
            raise serializers.ValidationError("Bitte eine Liste von Bildern angeben.")
        if len(value) > MAX_GALLERY:
            raise serializers.ValidationError(f"Höchstens {MAX_GALLERY} Bilder im Karussell.")
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Jedes Bild nur einmal.")
        known = set(
            WebsiteImage.objects.filter(website=self.context["website"], pk__in=value).values_list(
                "pk", flat=True
            )
        )
        if set(value) - known:
            raise serializers.ValidationError("Unbekanntes Bild.")
        return value

    def validate_image(self, value):
        if value is not None and value.website_id != self.context["website"].pk:
            raise serializers.ValidationError("Unbekanntes Bild.")
        return value

    def validate(self, attrs):
        kind = attrs.get("kind") or (self.instance.kind if self.instance else WebsiteText.Kind.PAGE)
        attrs["kind"] = kind
        department = attrs.get("department", self.instance.department if self.instance else None)
        if kind == WebsiteText.Kind.UNIT and department is None:
            raise serializers.ValidationError({"department": "Bitte die Untereinheit wählen."})
        if kind != WebsiteText.Kind.UNIT:
            attrs["department"] = None
        if kind == WebsiteText.Kind.PAGE and attrs.get("gallery"):
            raise serializers.ValidationError(
                {"gallery": "Ein Bilderkarussell gibt es nur auf Startseiten von Einheiten."}
            )
        attrs = super().validate(attrs)
        website = self.context["website"]
        clash = WebsiteText.objects.filter(website=website, kind=kind)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if (
            kind == WebsiteText.Kind.PAGE
            and clash.filter(
                slug=attrs.get("slug", self.instance.slug if self.instance else "")
            ).exists()
        ):
            raise serializers.ValidationError({"slug": "Diese Adresse ist schon vergeben."})
        if kind == WebsiteText.Kind.UNIT and clash.filter(department=department).exists():
            raise serializers.ValidationError(
                {"department": "Für diese Untereinheit gibt es schon einen Text."}
            )
        return attrs


class TextListView(_ContentMixin, APIView):
    """GET: alle Texte (Begrüßung wird bei Bedarf angelegt) · POST: neuer Text."""

    def get(self, request, org_id: int):
        website = self.website()
        if self.org_permissions & {WEBSITE_CONTENT, WEBSITE_MANAGE}:
            content.greeting(website)
        texts = WebsiteText.objects.filter(website=website).select_related("department")
        units = services.in_tree_order(services.units_below(self.org))
        return Response(
            {
                "texts": [text_data(self.org.pk, t) for t in texts],
                "units": [{"id": u.pk, "name": u.name} for u in units],
                "link_targets": content.link_targets(website),
            }
        )

    @transaction.atomic
    def post(self, request, org_id: int):
        website = self.website()
        ser = TextSerializer(data=request.data, context={"website": website})
        ser.is_valid(raise_exception=True)
        text = ser.save(organization=self.org, website=website, updated_by=request.user)
        record(self.org, request.user, "create", text, diff({}, snapshot(text)))
        return Response(text_data(self.org.pk, text, full=True), status=status.HTTP_201_CREATED)


class PageOrderView(_ContentMixin, APIView):
    """POST: Reihenfolge der eigenen Seiten im Menü (per Ziehen)."""

    def post(self, request, org_id: int):
        pages = WebsiteText.objects.filter(website=self.website(), kind=WebsiteText.Kind.PAGE)
        return reorder_response(request, self.org, pages, "menu_position")


class _TextMixin(_ContentMixin):
    def text(self) -> WebsiteText:
        return get_object_or_404(
            WebsiteText.objects.select_related("department", "image"),
            website=self.website(),
            pk=self.kwargs["pk"],
        )


class TextDetailView(_TextMixin, APIView):
    """GET/PUT: Entwurf · DELETE: Text löschen (nicht die Begrüßung)."""

    def get(self, request, org_id: int, pk: int):
        return Response(text_data(self.org.pk, self.text(), full=True))

    @transaction.atomic
    def put(self, request, org_id: int, pk: int):
        text = self.text()
        before = snapshot(text)
        ser = TextSerializer(
            text, data=request.data, partial=True, context={"website": text.website}
        )
        ser.is_valid(raise_exception=True)
        ser.save(updated_by=request.user)
        changes = diff(before, snapshot(text))
        changes.pop("updated_by", None)
        if changes:
            record(self.org, request.user, "update", text, changes)
        return Response(text_data(self.org.pk, text, full=True))

    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        text = self.text()
        if text.kind == WebsiteText.Kind.GREETING:
            raise ValidationError("Die Begrüßung lässt sich nicht löschen, nur leeren.")
        record(self.org, request.user, "delete", text, {"Text": [str(text), None]})
        text.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TextPublishView(_TextMixin, APIView):
    """POST: Entwurf veröffentlichen · DELETE: Veröffentlichung zurücknehmen."""

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        text = self.text()
        content.publish(text, request.user)
        record(self.org, request.user, "update", text, {"veröffentlicht": [None, str(text)]})
        return Response(text_data(self.org.pk, text, full=True))

    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        text = self.text()
        if text.is_published:
            content.unpublish(text, request.user)
            record(self.org, request.user, "update", text, {"veröffentlicht": [str(text), None]})
        return Response(text_data(self.org.pk, text, full=True))


class TextRestoreView(_TextMixin, APIView):
    """POST: frühere Fassung in den Entwurf holen."""

    @transaction.atomic
    def post(self, request, org_id: int, pk: int, rev: int):
        text = self.text()
        revision = get_object_or_404(WebsiteRevision, text=text, pk=rev)
        content.restore(text, revision, request.user)
        record(
            self.org, request.user, "update", text, {"Entwurf": [None, f"zurückgeholt: {revision}"]}
        )
        return Response(text_data(self.org.pk, text, full=True))


class ImageUploadSerializer(serializers.Serializer):
    caption = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    alt_text = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    decorative = serializers.BooleanField(required=False, default=False)
    department = serializers.IntegerField(required=False, allow_null=True, default=None)


def _department(website, value):
    """Untereinheit für „Gehört zu“ (leer: Verein allgemein)."""
    if value in (None, "", 0):
        return None
    dept = services.units_below(website.organization).filter(pk=value).first()
    if dept is None:
        raise ValidationError({"department": "Unbekannte Untereinheit."})
    return dept


def _image_files(request) -> tuple:
    """Hochgeladener Ausschnitt (``file``), optional ganzes Original und Ausschnitt."""
    upload = request.FILES.get("file")
    if upload is None:
        raise ValidationError({"file": "Bitte ein Bild auswählen."})
    original = request.FILES.get("original")
    crop = content.clean_crop(request.data.get("crop")) if original is not None else {}
    return upload, original, crop


def _with_department(qs):
    return qs.select_related("department")


class ImageListView(_ContentMixin, APIView):
    """GET: Bilder · POST: Bild hochladen (verkleinert, ohne Metadaten)."""

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, org_id: int):
        website = self.website()
        used = content.used_image_ids(website)
        return Response(
            [
                image_data(self.org.pk, i, used=i.pk in used)
                for i in _with_department(WebsiteImage.objects.filter(website=website))
            ]
        )

    @transaction.atomic
    def post(self, request, org_id: int):
        website = self.website()
        upload, original, crop = _image_files(request)
        ser = ImageUploadSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        image = content.store_image(
            website,
            upload,
            ser.validated_data["caption"],
            ser.validated_data["alt_text"],
            request.user,
            decorative=ser.validated_data["decorative"],
            original=original,
            crop=crop,
            department=_department(website, ser.validated_data["department"]),
        )
        record(self.org, request.user, "create", image, {"Bild": [None, str(image)]})
        return Response(image_data(self.org.pk, image, used=False), status=status.HTTP_201_CREATED)


class _ImageMixin(_ContentMixin):
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def image(self) -> WebsiteImage:
        return get_object_or_404(
            _with_department(WebsiteImage.objects), website=self.website(), pk=self.kwargs["pk"]
        )

    def data(self, image: WebsiteImage) -> dict:
        used = bool(content.image_usage(image))
        return image_data(self.org.pk, image, used=used)


class ImageDetailView(_ImageMixin, APIView):
    """GET: Bild mit Stellen · PUT: Angaben ändern · DELETE: löschen (benutzt: nach Rückfrage)."""

    def get(self, request, org_id: int, pk: int):
        image = self.image()
        usage = content.image_usage(image)
        return Response({**image_data(self.org.pk, image, used=bool(usage)), "usage": usage})

    @transaction.atomic
    def put(self, request, org_id: int, pk: int):
        image = self.image()
        ser = ImageUploadSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        before = snapshot(image)
        values = dict(ser.validated_data)
        if "department" in request.data:
            image.department = _department(image.website, values.pop("department", None))
        else:
            values.pop("department", None)
        for key, value in values.items():
            setattr(image, key, value)
        image.updated_by = request.user
        image.save()
        changes = diff(before, snapshot(image))
        if changes:
            record(self.org, request.user, "update", image, changes)
        return Response(self.data(image))

    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        image = self.image()
        places = content.image_in_use(image)
        older = content.image_in_revisions(image)
        confirmed = request.query_params.get("trotzdem") == "1" or (
            # ältere Oberfläche: Rückfrage nur zu früheren Fassungen
            not places and request.query_params.get("fruehere_fassungen") == "1"
        )
        if (places or older) and not confirmed:
            # Erst nach Rückfrage; die Rückfrage nennt alle Stellen
            lines = []
            if places:
                lines.append("Das Bild wird noch verwendet: " + "; ".join(places) + ".")
            if older:
                shown = ", ".join(older[:5]) + (
                    f" und {len(older) - 5} weitere" if len(older) > 5 else ""
                )
                lines.append(f"Es steht außerdem in früheren Fassungen: {shown}.")
            lines.append(
                "Beim Löschen wird das Bild dort entfernt, der übrige Inhalt bleibt."
                if places
                else "Nach dem Löschen lassen sie sich nur noch ohne dieses Bild zurückholen."
            )
            return Response(
                {"detail": " ".join(lines), "places": places, "revisions": older},
                status=status.HTTP_409_CONFLICT,
            )
        for text in content.remove_image_references(image, request.user):
            record(self.org, request.user, "update", text, {"Bild entfernt": [str(image), None]})
        record(self.org, request.user, "delete", image, {"Bild": [str(image), None]})
        content.delete_image(image)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ImageCropView(_ImageMixin, APIView):
    """POST: neuer Ausschnitt aus dem Original (``file`` = Ausschnitt, ``crop``)."""

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        image = self.image()
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Bitte ein Bild auswählen."})
        crop = content.clean_crop(request.data.get("crop"))
        content.recrop_image(image, upload, crop, request.user)
        record(self.org, request.user, "update", image, {"Ausschnitt": ["", "neu gewählt"]})
        return Response(self.data(image))


class ImageReplaceView(_ImageMixin, APIView):
    """POST: neue Datei für dasselbe Bild; Stellen und Angaben bleiben."""

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        image = self.image()
        upload, original, crop = _image_files(request)
        content.replace_image(image, upload, original, crop, request.user)
        record(self.org, request.user, "update", image, {"Datei": ["", "ersetzt"]})
        return Response(self.data(image))


class ImageCopyView(_ImageMixin, APIView):
    """POST: zweites Bild aus demselben Original mit eigenem Ausschnitt."""

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        image = self.image()
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Bitte ein Bild auswählen."})
        crop = content.clean_crop(request.data.get("crop"))
        copy = content.copy_image(image, upload, crop, request.user)
        record(self.org, request.user, "create", copy, {"Bild": [None, str(copy)]})
        return Response(image_data(self.org.pk, copy, used=False), status=status.HTTP_201_CREATED)


class ImageFileView(_ContentMixin, APIView):
    """GET: Bilddatei für die Verwaltung."""

    def get(self, request, org_id: int, pk: int):
        image = get_object_or_404(WebsiteImage, website=self.website(), pk=pk)
        size = request.query_params.get("size")
        f = image.small if size == "small" else image.file
        if size == "original" and image.original.name:
            f = image.original
        ctype = "image/png" if f.name.endswith(".png") else "image/jpeg"
        response = FileResponse(f.open("rb"), content_type=ctype)
        response["Cache-Control"] = "private, max-age=3600"
        response["X-Content-Type-Options"] = "nosniff"
        return response
