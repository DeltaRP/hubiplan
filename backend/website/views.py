"""Verwaltung der Webseite in HUBIplan (Einrichtung, Zustand, Domains, Vorschau)
und Einwilligungen zur Veröffentlichung in der Mitgliederakte."""

from __future__ import annotations

import re
from urllib.parse import quote

from django.conf import settings
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import MEMBERS_EDIT, WEBSITE_CONTENT, WEBSITE_MANAGE
from audit.log import diff, record, snapshot
from core.api_base import ModelCleanMixin, OrgScopedMixin
from core.tenancy import rls_bypass
from members.models import Membership
from members.views import _ClubMixin
from organizations.models import Organization
from organizations.theme import effective_theme

from . import designs, menu, privacy, services
from .models import (
    BLOCK_HINTS,
    BLOCKS,
    HOME_HINTS,
    HOME_NEEDS_BLOCK,
    HOME_SECTIONS,
    HOSTNAME_RE,
    PREVIEW_LINK_MAX_DAYS,
    PreviewLink,
    PublicationConsent,
    Website,
    WebsiteDomain,
    is_extra_block,
    normalize_home_sections,
)

MENU_ITEM_FIELDS = ("label", "hint", "toggle", "heading", "parent")

SETTINGS_FIELDS = [
    "state",
    "maintenance_text",
    "blocks",
    "menu",
    "home_sections",
    "design",
    "color_roles",
    "name_format",
    "show_vacant",
    "missing_consent",
    "units_mode",
    "unit_ids",
    "include_unit_events",
    "include_parent_events",
    "include_parent_honors",
    "allow_indexing",
    "contact_limit_per_hour",
    "privacy_mode",
    "privacy_text",
    "privacy_url",
]


class WebsiteSerializer(ModelCleanMixin, serializers.ModelSerializer):
    class Meta:
        model = Website
        fields = SETTINGS_FIELDS

    def validate_unit_ids(self, value):
        if not isinstance(value, list) or not all(isinstance(v, int) for v in value):
            raise serializers.ValidationError("Bitte eine Liste von Untereinheiten angeben.")
        org = self.context["org"]
        known = set(services.units_below(org).values_list("pk", flat=True))
        if set(value) - known:
            raise serializers.ValidationError("Unbekannte Untereinheit.")
        return sorted(set(value))

    def validate_blocks(self, value):
        if not isinstance(value, dict) or not all(isinstance(v, bool) for v in value.values()):
            raise serializers.ValidationError("Bausteine bitte als Schalter angeben.")
        result = {key: bool(value.get(key, True)) for key in BLOCKS}
        # Unterpunkte von „Würdenträger“ (je Würde, Ehrungen): nur bekannte, nur „aus“ merken
        if self.instance is not None:
            toggles = {
                item["toggle"]
                for item in menu.items(self.instance).values()
                if is_extra_block(item["toggle"])
            }
            for key, on in value.items():
                if key in toggles and not on:
                    result[key] = False
        return result

    def validate_home_sections(self, value):
        if not isinstance(value, list) or not all(
            isinstance(v, dict) and isinstance(v.get("key"), str) and isinstance(v.get("on"), bool)
            for v in value
        ):
            raise serializers.ValidationError("Bausteine der Startseite bitte als Liste angeben.")
        unknown = {v["key"] for v in value} - set(HOME_SECTIONS)
        if unknown:
            raise serializers.ValidationError(f"Unbekannter Baustein: {sorted(unknown)[0]}")
        return normalize_home_sections(value)

    def validate_menu(self, value):
        if self.instance is None:
            return []
        try:
            return menu.validate(value, menu.items(self.instance))
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate_color_roles(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Farbzuordnung bitte je Design angeben.")
        return designs.normalize_color_roles(value)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["home_sections"] = normalize_home_sections(instance.home_sections)
        data["menu"] = menu.normalize(instance.menu, menu.items(instance))
        data["color_roles"] = designs.normalize_color_roles(instance.color_roles)
        return data


def domain_data(d: WebsiteDomain) -> dict:
    return {"id": d.pk, "hostname": d.hostname, "is_primary": d.is_primary}


def link_data(link: PreviewLink) -> dict:
    return {
        "id": link.pk,
        "label": link.label,
        "expires_at": link.expires_at,
        "revoked_at": link.revoked_at,
        "is_active": link.is_active,
        "created_at": link.created_at,
        "created_by": (link.created_by.get_full_name() or link.created_by.email)
        if link.created_by
        else "",
    }


def site_url(website: Website) -> str | None:
    # Testserver: alle Webseiten laufen unter einer festen Adresse (z. B. …/webseite/)
    if settings.WEBSITE_PUBLIC_URL:
        return settings.WEBSITE_PUBLIC_URL.rstrip("/") + "/"
    primary = next(iter(website.domains.all()), None)
    return f"https://{primary.hostname}/" if primary else None


class _WebsiteMixin(OrgScopedMixin):
    """Lesen: Webseite verwalten oder Inhalte bearbeiten · Ändern: Webseite verwalten."""

    allowed_org_types = (
        Organization.Type.FEDERATION,
        Organization.Type.CLUB,
        Organization.Type.UNIT,
    )
    read_permission = None
    write_permission = WEBSITE_MANAGE

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not ({WEBSITE_MANAGE, WEBSITE_CONTENT} & self.org_permissions):
            raise NotFound()
        if request.method not in ("GET", "HEAD", "OPTIONS") and not services.module_enabled(
            self.org
        ):
            raise NotFound("Das Modul „Webseite“ ist für diese Einheit nicht freigeschaltet.")

    def website(self) -> Website:
        website = services.website_of(self.org)
        if website is None:
            raise NotFound("Für diese Einheit ist keine Webseite eingerichtet.")
        return website


class WebsiteView(_WebsiteMixin, APIView):
    """GET: Stand · POST: Webseite einrichten · PUT: Einstellungen · DELETE: entfernen."""

    def payload(self, website: Website | None) -> dict:
        data = {
            "module_enabled": services.module_enabled(self.org),
            "can_manage": WEBSITE_MANAGE in self.org_permissions,
            "can_edit_content": WEBSITE_CONTENT in self.org_permissions
            or WEBSITE_MANAGE in self.org_permissions,
            "preview_only": services.preview_only(),
            "block_labels": {
                **BLOCKS,
                "units": self.org.department_label_plural or BLOCKS["units"],
            },
            "block_hints": BLOCK_HINTS,
            "home_labels": {
                **HOME_SECTIONS,
                "units": self.org.department_label_plural or HOME_SECTIONS["units"],
            },
            "home_hints": HOME_HINTS,
            "home_needs_block": HOME_NEEDS_BLOCK,
            "designs": designs.catalog(),
            "units": [
                {"id": u.pk, "name": u.name}
                for u in services.in_tree_order(services.units_below(self.org))
            ],
            "website": None,
        }
        if website is not None:
            palette = effective_theme(self.org.ancestors())["palette"]
            data["palette"] = palette
            data["website"] = {
                **WebsiteSerializer(website).data,
                "public_key": website.public_key,
                "effective_state": services.effective_state(website),
                "url": site_url(website),
                # Farben je Rolle für alle Designs (Skizzen in der Auswahl)
                "design_colors": {
                    key: designs.resolve(key, palette, website.color_roles)
                    for key in designs.DESIGNS
                },
                "privacy_generated_at": website.privacy_generated_at,
                "privacy_published_text": website.privacy_published_text,
                "privacy_published_at": website.privacy_published_at,
                "checks": privacy.checks(website),
                # Mögliche Menüpunkte (Bausteine, Textseiten, Würden) in Standardreihenfolge
                "menu_items": [
                    {"key": key, **{f: item[f] for f in MENU_ITEM_FIELDS}}
                    for key, item in menu.items(website).items()
                ],
                "domains": [domain_data(d) for d in website.domains.all()],
                "preview_links": [
                    link_data(link)
                    for link in website.preview_links.select_related("created_by")
                    if link.revoked_at is None
                ],
            }
        return data

    def get(self, request, org_id: int):
        return Response(self.payload(services.website_of(self.org)))

    @transaction.atomic
    def post(self, request, org_id: int):
        if services.website_of(self.org) is not None:
            raise ValidationError("Die Webseite ist schon eingerichtet.")
        website = Website.objects.create(organization=self.org, public_key=Website.new_key())
        record(self.org, request.user, "create", website, {"Webseite": [None, "eingerichtet"]})
        return Response(self.payload(website), status=status.HTTP_201_CREATED)

    @transaction.atomic
    def put(self, request, org_id: int):
        website = self.website()
        before = snapshot(website)
        old_state = website.state
        ser = WebsiteSerializer(website, data=request.data, partial=True, context={"org": self.org})
        ser.is_valid(raise_exception=True)
        ser.save()
        if website.state == Website.State.PUBLIC:
            missing = privacy.blocking(website)
            if old_state == Website.State.PUBLIC:
                # Schon öffentlich: nur verhindern, dass die Datenschutzhinweise wegfallen
                missing = [m for m in missing if m.startswith("Datenschutzhinweise")]
            if missing:
                raise ValidationError(
                    {"state": ["Vor dem Veröffentlichen fehlt noch: " + " · ".join(missing)]}
                )
        changes = diff(before, snapshot(website))
        if changes:
            record(self.org, request.user, "update", website, changes)
        return Response(self.payload(website))

    @transaction.atomic
    def delete(self, request, org_id: int):
        website = self.website()
        record(self.org, request.user, "delete", website, {"Webseite": ["eingerichtet", None]})
        website.delete()
        return Response(self.payload(None))


class PrivacyGenerateView(WebsiteView):
    """POST: Datenschutzhinweise der Webseite aus den Einstellungen (neu) erzeugen."""

    http_method_names = ["post", "options"]

    @transaction.atomic
    def post(self, request, org_id: int):
        website = self.website()
        before = snapshot(website)
        privacy.generate(website)
        website.privacy_mode = "text"
        website.save()
        changes = diff(before, snapshot(website))
        if changes:
            record(self.org, request.user, "update", website, changes)
        return Response(self.payload(website))


class PrivacyPublishView(WebsiteView):
    """POST: Entwurf der Datenschutzhinweise veröffentlichen (UI-Audit NAF-02)."""

    http_method_names = ["post", "options"]

    @transaction.atomic
    def post(self, request, org_id: int):
        website = self.website()
        if not website.privacy_text.strip():
            raise serializers.ValidationError({"privacy_text": "Der Entwurf ist leer."})
        before = website.privacy_published_at
        website.privacy_published_text = website.privacy_text
        website.privacy_published_at = timezone.now()
        website.save(update_fields=["privacy_published_text", "privacy_published_at", "updated_at"])
        record(
            self.org,
            request.user,
            "update",
            website,
            {
                "Datenschutzhinweise veröffentlicht": [
                    str(before or ""),
                    str(website.privacy_published_at),
                ]
            },
        )
        return Response(self.payload(website))


class DomainSerializer(serializers.Serializer):
    hostname = serializers.CharField(max_length=253)
    is_primary = serializers.BooleanField(default=False)

    def validate_hostname(self, value: str) -> str:
        host = value.strip().lower().rstrip(".")
        host = re.sub(r"^https?://", "", host).split("/", 1)[0]
        if not re.match(HOSTNAME_RE, host):
            raise serializers.ValidationError("Bitte eine Domain wie „www.beispiel.de“ angeben.")
        with rls_bypass():
            taken = WebsiteDomain.objects.filter(hostname=host).exists()
        if taken:
            raise serializers.ValidationError("Diese Domain ist schon vergeben.")
        return host


class DomainListView(_WebsiteMixin, APIView):
    """POST: Domain hinzufügen."""

    @transaction.atomic
    def post(self, request, org_id: int):
        website = self.website()
        ser = DomainSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        primary = ser.validated_data["is_primary"] or not website.domains.exists()
        if primary:
            website.domains.update(is_primary=False)
        try:
            with transaction.atomic():
                domain = WebsiteDomain.objects.create(
                    organization=self.org,
                    website=website,
                    hostname=ser.validated_data["hostname"],
                    is_primary=primary,
                )
        except IntegrityError as exc:
            raise ValidationError({"hostname": ["Diese Domain ist schon vergeben."]}) from exc
        record(self.org, request.user, "create", domain, diff({}, snapshot(domain)))
        return Response(domain_data(domain), status=status.HTTP_201_CREATED)


class DomainDetailView(_WebsiteMixin, APIView):
    """PUT: als Hauptadresse setzen · DELETE: Domain entfernen."""

    def domain(self, pk: int) -> WebsiteDomain:
        return get_object_or_404(WebsiteDomain, website=self.website(), pk=pk)

    @transaction.atomic
    def put(self, request, org_id: int, pk: int):
        domain = self.domain(pk)
        if not domain.is_primary:
            domain.website.domains.update(is_primary=False)
            domain.is_primary = True
            domain.save(update_fields=["is_primary"])
            record(self.org, request.user, "update", domain, {"Hauptadresse": [False, True]})
        return Response(domain_data(domain))

    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        domain = self.domain(pk)
        website = domain.website
        record(self.org, request.user, "delete", domain, diff(snapshot(domain), {}))
        domain.delete()
        if domain.is_primary:
            first = website.domains.first()
            if first is not None:
                first.is_primary = True
                first.save(update_fields=["is_primary"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class PreviewLinkSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=100, required=False, allow_blank=True)
    days = serializers.IntegerField(min_value=1, max_value=PREVIEW_LINK_MAX_DAYS, default=7)


def preview_url(website: Website, token: str) -> str | None:
    base = site_url(website)
    return f"{base}vorschau?schluessel={quote(token)}" if base else None


class PreviewLinkListView(_WebsiteMixin, APIView):
    """POST: Vorschau-Link zum Weitergeben erzeugen (der Link erscheint nur einmal)."""

    @transaction.atomic
    def post(self, request, org_id: int):
        website = self.website()
        ser = PreviewLinkSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        link, token = PreviewLink.create(
            website, ser.validated_data["days"], ser.validated_data.get("label", ""), request.user
        )
        record(
            self.org,
            request.user,
            "create",
            link,
            {
                "Vorschau-Link": [
                    None,
                    f"gültig bis {timezone.localtime(link.expires_at):%d.%m.%Y %H:%M}",
                ]
            },
        )
        return Response(
            {**link_data(link), "token": token, "url": preview_url(website, token)},
            status=status.HTTP_201_CREATED,
        )


class PreviewLinkDetailView(_WebsiteMixin, APIView):
    """DELETE: Vorschau-Link widerrufen."""

    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        link = get_object_or_404(PreviewLink, website=self.website(), pk=pk)
        if link.revoked_at is None:
            link.revoked_at = timezone.now()
            link.save(update_fields=["revoked_at"])
            record(
                self.org, request.user, "update", link, {"Vorschau-Link": ["aktiv", "widerrufen"]}
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PreviewOpenView(_WebsiteMixin, APIView):
    """POST: kurzlebigen Schlüssel für „Vorschau öffnen“ erzeugen.

    Auch mit dem Recht „Inhalte bearbeiten“, damit Redakteure ihre Texte prüfen können.
    """

    write_permission = None

    def post(self, request, org_id: int):
        website = self.website()
        token = services.open_token(website)
        return Response({"token": token, "url": preview_url(website, token)})


# --- Einwilligungen in der Mitgliederakte ---


class ConsentSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=PublicationConsent.Category.choices)
    active = serializers.BooleanField()
    source = serializers.ChoiceField(
        choices=[PublicationConsent.Source.BOARD, PublicationConsent.Source.PAPER],
        default=PublicationConsent.Source.BOARD,
    )
    on = serializers.DateField(required=False)

    def validate_on(self, value):
        if value > timezone.localdate():
            raise serializers.ValidationError("Das Datum darf nicht in der Zukunft liegen.")
        return value


class MemberPublicationView(_ClubMixin, APIView):
    """GET: Einwilligungen/Widersprüche eines Mitglieds · PUT: eine Kategorie ändern."""

    write_permission = MEMBERS_EDIT

    def membership(self) -> Membership:
        return get_object_or_404(Membership, organization=self.org, pk=self.kwargs["pk"])

    def get(self, request, org_id: int, pk: int):
        return Response({"categories": services.status(self.membership())})

    @transaction.atomic
    def put(self, request, org_id: int, pk: int):
        membership = self.membership()
        ser = ConsentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        before, after = services.set_entry(
            membership,
            data["category"],
            data["active"],
            data["source"],
            request.user,
            data.get("on"),
        )
        if before != after:
            label = PublicationConsent.Category(data["category"]).label
            kind = (
                "Widerspruch"
                if data["category"] in PublicationConsent.OBJECTION_CATEGORIES
                else "Einwilligung"
            )
            record(
                self.org,
                request.user,
                "update",
                membership,
                {f"Webseite: {kind} {label}": [before, after]},
                person=membership.person,
            )
        return Response({"categories": services.status(membership)})


# --- zurückgehaltene Nachrichten aus dem Kontaktformular ---


def held_data(m) -> dict:
    return {
        "id": m.pk,
        "recipient_name": m.recipient_name,
        "sender_name": m.sender_name,
        "sender_email": m.sender_email,
        "subject": m.subject,
        "body": m.body,
        "reason": m.reason,
        "created_at": m.created_at,
    }


class HeldListView(_WebsiteMixin, APIView):
    """GET: zurückgehaltene Nachrichten (nur „Webseite verwalten“)."""

    read_permission = WEBSITE_MANAGE

    def get(self, request, org_id: int):
        from .contact_models import HeldMessage

        return Response([held_data(m) for m in HeldMessage.objects.filter(website=self.website())])


class HeldDetailView(_WebsiteMixin, APIView):
    """POST: freigeben und zustellen · DELETE: verwerfen."""

    read_permission = WEBSITE_MANAGE

    def message(self, pk: int):
        from .contact_models import HeldMessage

        return get_object_or_404(HeldMessage, website=self.website(), pk=pk)

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        from . import contact
        from .public import SiteView

        message = self.message(pk)
        target = SiteView(message.website).resolve_recipient(message.recipient)
        if target is None:
            raise ValidationError("Den Empfänger gibt es nicht mehr. Bitte verwerfen.")
        name, emails = target
        delivered = contact.deliver(
            message.website,
            name,
            emails,
            {
                "name": message.sender_name,
                "email": message.sender_email,
                "subject": message.subject,
                "message": message.body,
            },
        )
        if not delivered:
            # Nachricht bleibt in der Liste; die gescheiterte Mail steht im Postausgang
            # (kein raise: der Eintrag im Postausgang soll gespeichert bleiben)
            return Response(
                {
                    "detail": "Die Nachricht konnte nicht zugestellt werden und bleibt in "
                    "der Liste. Bitte den Postausgang prüfen und später erneut freigeben."
                },
                status=status.HTTP_409_CONFLICT,
            )
        record(
            self.org,
            request.user,
            "delete",
            message,
            {"Nachricht von der Webseite": [f"zurückgehalten ({message.reason})", "zugestellt"]},
        )
        message.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        message = self.message(pk)
        record(
            self.org,
            request.user,
            "delete",
            message,
            {"Nachricht von der Webseite": [f"zurückgehalten ({message.reason})", "verworfen"]},
        )
        message.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
