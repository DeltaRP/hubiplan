"""Öffentliche Schnittstelle der Webseite: /api/public/site/v1/…

Ohne Anmeldung, nur lesen (außer Kontaktformular und Vorschau-Tausch). Im Zustand
„Wartung“ gibt es nur die Wartungsangaben, alle Daten nur mit gültiger Vorschau
(Kopfzeile ``X-Preview-Session``). Im Zustand „Aus“ gibt es nichts.
"""

from __future__ import annotations

import datetime

from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.ratelimit import client_ip, too_many
from core.tenancy import rls_bypass

from . import contact, designs, menu, results, services
from .models import BLOCKS, Website, WebsiteDomain
from .public import SiteView

API_VERSION = 1
PREVIEW_HEADER = "HTTP_X_PREVIEW_SESSION"
READ_LIMIT = 600  # Abrufe je Minute und IP


class _Public(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    # Ohne vollständige Daten erlaubt (Wartungsseite)
    maintenance_ok = False

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if too_many(f"website:read:{client_ip(request)}", READ_LIMIT, 60):
            from rest_framework.exceptions import Throttled

            raise Throttled()

    def dispatch(self, request, *args, **kwargs):
        with rls_bypass():
            return super().dispatch(request, *args, **kwargs)

    def options(self, request, *args, **kwargs):
        """Vorabfrage des Browsers (CORS): Das Kontaktformular schickt der Browser
        direkt hierher, damit Drosselung und Rechenaufgabe die echte Adresse sehen."""
        response = Response(status=204)
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "X-Preview-Session, Content-Type"
        response["Access-Control-Max-Age"] = "600"
        return response

    def load(self, request, key: str) -> SiteView:
        website = Website.objects.select_related("organization").filter(public_key=key).first()
        if website is None or not website.organization.is_active:
            raise Http404
        state = services.effective_state(website)
        self.preview = services.valid_session(website, request.META.get(PREVIEW_HEADER))
        if not services.module_enabled(website.organization):
            raise Http404
        if state == Website.State.OFF and not self.preview:
            raise Http404
        self.visible = state == Website.State.PUBLIC or self.preview
        self.state = state
        if not self.visible and not self.maintenance_ok:
            raise Http404
        return SiteView(website, request.build_absolute_uri("/"))

    def respond(self, data, site: SiteView | None = None, status: int = 200) -> Response:
        response = Response(data, status=status)
        return self.decorate(response, site)

    def decorate(self, response, site: SiteView | None):
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Headers"] = "X-Preview-Session, Content-Type"
        response["X-Content-Type-Options"] = "nosniff"
        if getattr(self, "preview", False):
            response["Cache-Control"] = "private, no-store"
            response["X-Robots-Tag"] = "noindex"
        else:
            response["Cache-Control"] = "public, max-age=300"
            if site and not site.site.allow_indexing:
                response["X-Robots-Tag"] = "noindex"
        return response


class ResolveView(_Public):
    """GET ?host=…: Welche Webseite gehört zu diesem Hostnamen?"""

    def get(self, request):
        host = (request.query_params.get("host") or "").strip().lower().split(":")[0]
        domain = (
            WebsiteDomain.objects.select_related("website__organization")
            .filter(hostname=host)
            .first()
        )
        if domain is None or not services.module_enabled(domain.website.organization):
            raise Http404
        return self.respond({"key": domain.website.public_key, "version": API_VERSION})


class SiteInfoView(_Public):
    """Grunddaten, Menü, Begrüßung; im Wartungsmodus nur die Wartungsangaben."""

    maintenance_ok = True

    def get(self, request, key: str):
        site = self.load(request, key)
        org = site.org
        from organizations import imprint
        from organizations.theme import effective_theme

        theme = effective_theme(org.ancestors())
        base = {
            "version": API_VERSION,
            "state": self.state,
            "preview": self.preview,
            "name": org.name,
            "short_name": org.short_name,
            "logo_url": site.abs(theme["logo_url"]) if theme["logo_url"] else None,
            "theme": {k: theme[k] for k in ("primary", "on_primary", "accent", "on_accent")},
            # Standarddesign und Farben je Rolle; alle Designs, damit die Vorschau
            # ein anderes zeigen kann, ohne es zu übernehmen
            "design": site.site.design,
            "palette": [{k: c[k] for k in ("color", "on_color")} for c in theme["palette"]],
            "designs": {
                key: designs.resolve(key, theme["palette"], site.site.color_roles)
                for key in designs.DESIGNS
            },
            "imprint_url": site.url("imprint/"),
            "allow_indexing": site.site.allow_indexing and self.state == Website.State.PUBLIC,
            # Sprache der festen Texte (hubiplan-website, W1); Standard Deutsch
            "language": site.site.language,
            "hubiplan_imprint": imprint.page_urls(org),
        }
        if not self.visible:
            base["maintenance_text"] = site.site.maintenance_text
            return self.respond(base, site, status=503)
        # Gehört zu: Dachverband eines Vereins, bei einer Untereinheit die Einheit darüber
        parent = (
            org.parent if org.parent and (org.parent.type == "federation" or site.is_unit) else None
        )
        from organizations.serializers import effective_contact

        contact_data = effective_contact(org)
        data = {
            **base,
            "founding_year": org.founding_year,
            "unit_label": org.department_label,
            "unit_label_plural": org.department_label_plural,
            "address": {"street": org.street, "postal_code": org.postal_code, "city": org.city},
            "email": contact_data.get("email") or None,
            "phone": contact_data.get("phone") or None,
            "member_of": {"name": parent.name, "website": parent.website or None}
            if parent
            else None,
            "blocks": {k: site.site.block_on(k) for k in BLOCKS},
            # Menü „Geschichte“: Unterpunkte „Chronik“ und „Ämter“ nur mit Inhalt (Ralf 2026-10-31)
            "has_history_text": site.site.block_on("history")
            and site.page("geschichte") is not None,
            "has_offices": site.site.block_on("offices") and bool(site.chairs()),
            # Bezeichnung für Menü und Überschrift der Majestäten
            "honors_label": site.honors_label() if site.site.block_on("honors") else None,
            # Menü „Würdenträger“: Unterpunkte je Würde und „Ehrungen“ (Ralf 2026-10-31)
            "honors_menu": site.honors_menu(),
            # Bausteine der Startseite (eingeschaltet, in Reihenfolge)
            "home": [k for k in site.site.home() if k != "results" or results.enabled(site)],
            # Wettbewerbsergebnisse (Schritt 5 der Wettbewerbe): Übersicht und Startseite
            "results_url": site.url("results/") if results.enabled(site) else None,
            "menu": site.menu(),
            # Ganzes Menü in Reihenfolge mit Unterpunkten (Ralf 2026-10-31: per Ziehen)
            "nav": menu.public_nav(site),
            # Eigene Namen der Bausteine für die Überschriften (Ralf 2026-11-01); nur gesetzte
            "names": site.site.names(),
            "greeting": site.greeting(),
            "social": site.social(org) if site.site.block_on("social") else [],
            # Beiträge aus Instagram/Facebook vorhanden? (Abruf über posts/)
            "posts": site.posts_available()
            if site.site.block_on("posts")
            else {"instagram": False, "facebook": False},
            "posts_url": site.url("posts/") if site.site.block_on("posts") else None,
            "units": [site.unit_summary(u) for u in site.units],
            "statute_url": self.statute_url(request, site)
            if site.site.block_on("statutes")
            else None,
            "statute_preview_url": site.url("statute/preview/")
            if site.site.block_on("statutes") and _statute_publication(site)
            else None,
            # Beitragsordnung (optional, Ralf 2026-10-31): wie die Satzung unter „Dokumente“
            "fee_rules_url": self.statute_url(request, site, FEE_RULES)
            if site.site.block_on("statutes")
            else None,
            "fee_rules_preview_url": site.url("fee-rules/preview/")
            if site.site.block_on("statutes") and _statute_publication(site, FEE_RULES)
            else None,
            # Gründungsurkunde (optional, Ralf 2026-10-31): ebenso unter „Dokumente“
            "founding_deed_url": self.statute_url(request, site, FOUNDING_DEED)
            if site.site.block_on("statutes")
            else None,
            "founding_deed_preview_url": site.url("founding-deed/preview/")
            if site.site.block_on("statutes") and _statute_publication(site, FOUNDING_DEED)
            else None,
            "calendar": {
                "json_url": site.url("events/"),
                "ics_url": site.url("events.ics"),
            }
            if site.site.block_on("events")
            else None,
        }
        return self.respond(data, site)

    def statute_url(self, request, site: SiteView, kind: str = "statute"):
        from django.urls import reverse

        pub = _statute_publication(site, kind)
        return (
            request.build_absolute_uri(reverse("public-statute", args=[pub.public_key]))
            if pub
            else None
        )


FEE_RULES = "fee_rules"
FOUNDING_DEED = "founding_deed"
# Alles, was unter „Dokumente“ erscheinen kann
DOCUMENT_KINDS = ("statute", FEE_RULES, FOUNDING_DEED)


def _statute_publication(site: SiteView, kind: str = "statute"):
    """Öffentliche Satzung der Seite (oder mit ``kind`` Beitragsordnung/Gründungsurkunde)."""
    from statutes.models import StatutePublication

    return StatutePublication.objects.filter(
        organization=site.area,
        department=site.org if site.is_unit else None,
        kind=kind,
        is_public=True,
    ).first()


class StatutePreviewView(_Public):
    """Erste Seite des aktuellen Dokuments (Satzung usw.) als PNG (unter „Dokumente“)."""

    kind = "statute"

    def get(self, request, key: str):
        site = self.load(request, key)
        if not site.site.block_on("statutes"):
            raise Http404
        from statutes import services as statutes
        from statutes.preview import first_page_png

        pub = _statute_publication(site, self.kind)
        if pub is None:
            raise Http404
        version = statutes.versions(pub.organization, pub.department, pub.kind).first()
        png = first_page_png(version) if version else None
        if png is None:
            raise Http404
        return self.decorate(HttpResponse(png, content_type="image/png"), site)


class PreviewExchangeSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=500)


class PreviewView(_Public):
    """POST: Vorschau-Schlüssel (Knopf oder Link) gegen eine Vorschau-Sitzung tauschen."""

    def post(self, request, key: str):
        website = Website.objects.select_related("organization").filter(public_key=key).first()
        if website is None:
            raise Http404
        if too_many(f"website:preview:{client_ip(request)}", 20, 60 * 60):
            from rest_framework.exceptions import Throttled

            raise Throttled()
        ser = PreviewExchangeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = services.exchange(website, ser.validated_data["token"])
        self.preview = True
        if result is None:
            return self.respond(
                {"detail": "Der Vorschau-Schlüssel ist ungültig oder abgelaufen."}, status=403
            )
        session, until = result
        return self.respond({"session": session, "until": until})


class BoardView(_Public):
    def get(self, request, key: str):
        site = self.load(request, key)
        board = site.site.block_on("board")
        offices = site.site.block_on("offices")
        # Ehrungen: eigene Seite unter „Würdenträger“, einzeln ausschaltbar (Ralf 2026-10-31)
        honorary = site.honorary() if site.site.block_on("honorary") else []
        if not board and not offices and not honorary:
            raise Http404
        # Frühere Amtsinhaber stehen unter „Ämter“ (Menü „Geschichte“), nicht beim Vorstand.
        return self.respond(
            {
                "roles": site.board() if board else [],
                "honorary": honorary,
                "chronicle": site.chairs() if offices else [],
            },
            site,
        )


class HonorsView(_Public):
    """Würden und Chronik (Majestäten): aktuelle Träger und alle früheren."""

    def get(self, request, key: str):
        site = self.load(request, key)
        if not site.site.block_on("honors"):
            raise Http404
        return self.respond({"dignities": site.honors()}, site)


class _ResultsBase(_Public):
    """Wettbewerbsergebnisse. Laufende Wettbewerbe ändern sich: kurze Zwischenspeicherung."""

    def short(self, response, live: bool):
        if live and not getattr(self, "preview", False):
            response["Cache-Control"] = "public, max-age=5"
        return response


class ResultsView(_ResultsBase):
    """GET: veröffentlichte Wettbewerbe, Reihen und Wanderpokale; ``?start=1``: die
    neuesten Wettbewerbe mit Siegern für die Startseite."""

    def get(self, request, key: str):
        site = self.load(request, key)
        if not results.enabled(site):
            raise Http404
        if request.query_params.get("start"):
            items = results.home(site)
            data = {"competitions": items, "poll_seconds": results.POLL_SECONDS}
            live = any(not c["final"] for c in items)
        else:
            data = results.overview(site)
            live = any(not c["final"] for c in data["competitions"])
        return self.short(self.respond(data, site), live)


class ResultDetailView(_ResultsBase):
    def get(self, request, key: str, token: str):
        site = self.load(request, key)
        comp = results.find(site, token) if results.enabled(site) else None
        if comp is None:
            raise Http404
        data = results.detail(site, comp)
        return self.short(self.respond(data, site), not data["final"])


class ResultVersionView(_ResultsBase):
    """Kleiner Stand eines Wettbewerbs: Die Seite fragt ihn während „live“ alle 15 Sekunden
    ab und lädt die Tabelle nur bei einer Änderung neu."""

    def get(self, request, key: str, token: str):
        site = self.load(request, key)
        comp = results.find(site, token) if results.enabled(site) else None
        if comp is None:
            raise Http404
        return self.short(self.respond(results.version(site, comp), site), True)


class ResultSeriesView(_ResultsBase):
    def get(self, request, key: str, token: str):
        site = self.load(request, key)
        series = results.find_series(site, token)
        if series is None:
            raise Http404
        return self.respond(results.series_detail(site, series), site)


class HonorsPhotoView(_Public):
    def get(self, request, key: str, token: str):
        site = self.load(request, key)
        if not site.site.block_on("honors"):
            raise Http404
        photo = site.reign_photo(token)
        if photo is None:
            raise Http404
        f = photo.small if request.query_params.get("size") == "small" else photo.file
        ctype = "image/png" if f.name.endswith(".png") else "image/jpeg"
        return self.decorate(FileResponse(f.open("rb"), content_type=ctype), site)


class UnitListView(_Public):
    def get(self, request, key: str):
        site = self.load(request, key)
        return self.respond({"units": [site.unit_summary(u) for u in site.units]}, site)


class UnitDetailView(_Public):
    def get(self, request, key: str, slug: str):
        site = self.load(request, key)
        unit = site.unit_by_slug(slug)
        if unit is None:
            raise Http404
        return self.respond(site.unit_detail(unit), site)


class PageView(_Public):
    def get(self, request, key: str, slug: str):
        site = self.load(request, key)
        page = site.page(slug)
        if page is None:
            raise Http404
        return self.respond(page, site)


class ImageView(_Public):
    def get(self, request, key: str, image_key: str):
        site = self.load(request, key)
        image = site.public_image(image_key)
        if image is None:
            raise Http404
        f = image.small if request.query_params.get("size") == "small" else image.file
        ctype = "image/png" if f.name.endswith(".png") else "image/jpeg"
        return self.decorate(FileResponse(f.open("rb"), content_type=ctype), site)


POST_KINDS = ("instagram", "facebook")
MAX_POSTS_PUBLIC = 50


class PostsView(_Public):
    """GET ?art=instagram|facebook&anzahl=N&einheit=<slug>: Beiträge aus den eigenen
    Kanälen, Bilder von dieser Instanz (Besucher haben keinen Kontakt zu Meta)."""

    def get(self, request, key: str):
        site = self.load(request, key)
        if not site.site.block_on("posts"):
            raise Http404
        kind = request.query_params.get("art") or None
        if kind and kind not in POST_KINDS:
            raise Http404
        try:
            limit = max(1, min(int(request.query_params.get("anzahl") or 12), MAX_POSTS_PUBLIC))
        except ValueError:
            limit = 12
        department_id = None
        slug = request.query_params.get("einheit")
        if slug:
            department_id = next((pk for pk, s in site.unit_slugs.items() if s == slug), None)
            if department_id is None:
                raise Http404
        return self.respond({"posts": site.posts(kind, department_id, limit)}, site)


class PostImageView(_Public):
    def get(self, request, key: str, image_key: str):
        site = self.load(request, key)
        image = site.public_post_image(image_key)
        if image is None:
            raise Http404
        f = image.small if request.query_params.get("size") == "small" else image.file
        ctype = "image/png" if f.name.endswith(".png") else "image/jpeg"
        return self.decorate(FileResponse(f.open("rb"), content_type=ctype), site)


class PhotoView(_Public):
    """Foto einer Person (nur mit Foto- und Veröffentlichungs-Einwilligung)."""

    def get(self, request, key: str, token: str):
        site = self.load(request, key)
        membership = site.photo_membership(token)
        if membership is None:
            raise Http404
        from members.photo_models import MemberPhoto

        photo = MemberPhoto.objects.filter(
            membership=membership, status=MemberPhoto.Status.APPROVED
        ).first()
        if photo is None:
            raise Http404
        f = photo.thumbnail if request.query_params.get("size") == "small" else photo.image
        return self.decorate(FileResponse(f.open("rb"), content_type="image/jpeg"), site)


class ImprintView(_Public):
    """Impressum und Datenschutzhinweise (auch im Wartungsmodus)."""

    maintenance_ok = True

    def get(self, request, key: str):
        site = self.load(request, key)
        from organizations import imprint

        from .privacy import public_privacy

        data = imprint.public_data(site.org)
        # Die Webseite hat eigene Datenschutzhinweise (nicht die für Mitglieder)
        data["privacy"] = public_privacy(site.site)
        return self.respond(data, site)


EVENT_DAYS_BACK = 30
EVENT_DAYS_AHEAD = 400


def _parent_events(site: SiteView):
    """Öffentliche Termine der Einheiten darüber, soweit sie nach unten freigegeben sind
    (wie im Kalender der Mitglieder): bei einer Untereinheit die der Untereinheiten
    darüber und der Einheit selbst, dazu die der Einheiten über dem Datenbereich
    (z. B. Dachverband)."""
    from events import services as events
    from events.models import Event
    from organizations.models import Organization
    from organizations.tree import UnitTree

    public = Event.objects.filter(visibility=Event.Visibility.PUBLIC)
    q = Q(pk__in=[])
    if site.is_unit:
        above = UnitTree.of(site.area.pk).ancestors(site.org.pk)[1:]
        q |= Q(organization=site.area, department_id__in=above) & events.down("department")
        q |= Q(organization=site.area, department__isnull=True) & events.down("organization")
    parents = [
        o.pk
        for o in site.area.ancestors()[1:]
        if o.type != Organization.Type.PLATFORM and o.is_active and events.module_on(o)
    ]
    if parents:
        q |= Q(organization_id__in=parents, department__isnull=True) & events.down("organization")
    return public.filter(q)


def _foreign_owner(site: SiteView, event) -> str | None:
    if event.organization_id != site.area.pk:
        return event.organization.name
    if site.is_unit and event.department_id != site.org.pk:
        if event.department_id is None:
            return site.area.name
        if event.department_id not in site.unit_slugs:
            return event.department.name
    return None


def _events(site: SiteView, unit_slug: str | None):
    from events.models import Event
    from events.recurrence import occurrences

    qs = Event.objects.filter(organization=site.area, visibility=Event.Visibility.PUBLIC)
    # Eigene Termine: bei einer Untereinheit die mit ihr als Untereinheit
    own = {"department": site.org} if site.is_unit else {"department__isnull": True}
    if unit_slug:
        unit = site.unit_by_slug(unit_slug)
        if unit is None:
            raise Http404
        qs = qs.filter(department=unit)
    elif site.site.include_unit_events:
        qs = qs.filter(**own) | qs.filter(department__in=site.units)
    else:
        qs = qs.filter(**own)
    if not unit_slug and site.site.include_parent_events:
        qs = qs | _parent_events(site)
    now = timezone.now()
    return occurrences(
        qs.select_related("category", "department", "organization").distinct(),
        now - datetime.timedelta(days=EVENT_DAYS_BACK),
        now + datetime.timedelta(days=EVENT_DAYS_AHEAD),
    )


class EventsView(_Public):
    def get(self, request, key: str):
        site = self.load(request, key)
        if not site.site.block_on("events"):
            raise Http404
        slug = request.query_params.get("einheit")
        items = _events(site, slug)
        unit_slugs = site.unit_slugs
        ics = site.url("events.ics") + (f"?einheit={slug}" if slug else "")
        return self.respond(
            {
                "ics_url": ics,
                "events": [
                    {
                        "id": o.key,
                        "title": o.event.title,
                        "starts_at": o.starts_at,
                        "ends_at": o.ends_at,
                        "all_day": o.event.all_day,
                        "location": o.event.location,
                        "address": o.event.address,
                        "description": o.event.description,
                        "category": o.event.category.name if o.event.category_id else None,
                        "color": o.event.category.color if o.event.category_id else None,
                        "unit": unit_slugs.get(o.event.department_id),
                        # Termin einer Einheit darüber: deren Name, sonst leer
                        "owner": _foreign_owner(site, o.event),
                        "is_cancelled": o.is_cancelled,
                        "note": o.note,
                    }
                    for o in items
                ],
            },
            site,
        )


class EventsIcsView(_Public):
    def get(self, request, key: str):
        site = self.load(request, key)
        if not site.site.block_on("events"):
            raise Http404
        from events import ical
        from organizations import imprint

        items = _events(site, request.query_params.get("einheit"))
        body = ical.calendar(
            site.org.name,
            items,
            request.get_host().split(":")[0],
            description=f"Impressum: {imprint.page_urls(site.org)['imprint']}",
        )
        response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
        response["Content-Disposition"] = 'inline; filename="termine.ics"'
        return self.decorate(response, site)


class ContactSerializer(serializers.Serializer):
    recipient = serializers.CharField(max_length=40)
    name = serializers.CharField(max_length=100)
    email = serializers.EmailField(max_length=200)
    subject = serializers.CharField(max_length=150)
    message = serializers.CharField(max_length=5000, min_length=10)
    copy = serializers.BooleanField(default=False)
    homepage = serializers.CharField(max_length=200, required=False, allow_blank=True)
    challenge = serializers.CharField(max_length=500)
    nonce = serializers.IntegerField(min_value=0)


class ContactView(_Public):
    """GET: Empfänger und Rechenaufgabe · POST: Nachricht senden."""

    def get(self, request, key: str):
        site = self.load(request, key)
        if not site.site.block_on("contact"):
            raise Http404
        response = self.respond(
            {"recipients": site.recipients(), "challenge": contact.challenge(site.site)}, site
        )
        response["Cache-Control"] = "private, no-store"
        return response

    def post(self, request, key: str):
        site = self.load(request, key)
        if not site.site.block_on("contact"):
            raise Http404
        ser = ContactSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            contact.submit(site, client_ip(request), ser.validated_data)
        except contact.Rejected as exc:
            body = {"detail": exc.message, **({"code": exc.code} if exc.code else {})}
            response = self.respond(body, site, status=exc.status)
            response["Cache-Control"] = "private, no-store"
            return response
        # Zurückgehalten oder verworfen sieht für den Absender gleich aus
        response = self.respond({"status": "ok"}, site)
        response["Cache-Control"] = "private, no-store"
        return response
