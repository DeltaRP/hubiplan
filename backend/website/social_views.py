"""Verwaltung der Social-Media-Beiträge der Webseite.

Kanäle anlegen, verbinden und trennen: Recht „Webseite verwalten“.
Beiträge freigeben, ausblenden und Alternativtexte: auch „Inhalte bearbeiten“.
"""

from __future__ import annotations

from django.db import transaction
from django.http import FileResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import WEBSITE_MANAGE
from access.permissions import permissions_in
from audit.log import record
from core.tenancy import rls_bypass

from . import services, social
from .content_views import _ContentMixin
from .social_models import SocialFeed, SocialPost, SocialPostImage
from .views import _WebsiteMixin


def feed_data(feed: SocialFeed) -> dict:
    return {
        "id": feed.pk,
        "kind": feed.kind,
        "kind_label": feed.get_kind_display(),
        "department": feed.department_id,
        "department_name": feed.department.name if feed.department_id else None,
        "mode": feed.mode,
        "max_posts": feed.max_posts,
        "show_link": feed.show_link,
        "strip_hashtags": feed.strip_hashtags,
        "is_active": feed.is_active,
        "app_id": feed.app_id,
        "config_id": feed.config_id,
        "via_facebook": feed.via_facebook,
        "has_secret": bool(feed.app_secret),
        "status": feed.status,
        "status_label": feed.get_status_display(),
        "account_name": feed.account_name,
        "token_expires_at": feed.token_expires_at,
        "last_sync_at": feed.last_sync_at,
        "last_error": feed.last_error,
        "connected_at": feed.connected_at,
        "pages": social.pending_pages(feed) if feed.status == SocialFeed.Status.CHOOSE else [],
        "post_count": feed.posts.count(),
        "pending_count": feed.posts.filter(state=SocialPost.State.PENDING).count(),
    }


def post_data(org_id: int, post: SocialPost) -> dict:
    return {
        "id": post.pk,
        "feed": post.feed_id,
        "media_type": post.media_type,
        "text": post.text,
        "permalink": post.permalink,
        "published_at": post.published_at,
        "state": post.state,
        "state_label": post.get_state_display(),
        "images": [
            {
                "id": i.pk,
                "url": f"/api/orgs/{org_id}/website/social/images/{i.pk}/file/",
                "small_url": f"/api/orgs/{org_id}/website/social/images/{i.pk}/file/?size=small",
                "alt_text": i.alt_text,
                "is_video": i.is_video,
                "width": i.width,
                "height": i.height,
            }
            for i in post.images.all()
        ],
    }


class FeedSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SocialFeed.Kind.choices, required=False)
    department = serializers.IntegerField(required=False, allow_null=True)
    mode = serializers.ChoiceField(choices=SocialFeed.Mode.choices, required=False)
    max_posts = serializers.IntegerField(
        min_value=1, max_value=social.MAX_POSTS_LIMIT, required=False
    )
    show_link = serializers.BooleanField(required=False)
    strip_hashtags = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)
    app_id = serializers.RegexField(r"^\d{0,40}$", required=False, allow_blank=True)
    config_id = serializers.RegexField(r"^\d{0,40}$", required=False, allow_blank=True)
    via_facebook = serializers.BooleanField(required=False)
    # Nur schreiben; leer lassen = unverändert
    app_secret = serializers.RegexField(
        r"^[A-Za-z0-9]{0,128}$", required=False, allow_blank=True, write_only=True
    )


SETTINGS = ("mode", "max_posts", "show_link", "strip_hashtags", "is_active")
# Anmeldung: Änderung erst beim nächsten Verbinden wirksam
LOGIN_SETTINGS = ("app_id", "config_id", "via_facebook")


class _FeedMixin(_WebsiteMixin):
    def feed(self) -> SocialFeed:
        return get_object_or_404(
            SocialFeed.objects.select_related("department"),
            website=self.website(),
            pk=self.kwargs["pk"],
        )


class FeedListView(_WebsiteMixin, APIView):
    """GET: Kanäle, Weiterleitungsadresse, Untereinheiten · POST: Kanal anlegen."""

    def get(self, request, org_id: int):
        website = self.website()
        feeds = SocialFeed.objects.filter(website=website).select_related("department")
        units = services.in_tree_order(services.units_below(self.org))
        return Response(
            {
                "feeds": [feed_data(f) for f in feeds],
                "redirect_uri": social.redirect_uri(),
                "units": [{"id": u.pk, "name": u.name} for u in units],
                "can_manage": WEBSITE_MANAGE in self.org_permissions,
            }
        )

    @transaction.atomic
    def post(self, request, org_id: int):
        website = self.website()
        ser = FeedSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        if "kind" not in data:
            raise ValidationError({"kind": "Bitte Instagram oder Facebook wählen."})
        department = None
        if data.get("department"):
            department = services.units_below(self.org).filter(pk=data["department"]).first()
            if department is None:
                raise ValidationError({"department": "Diese Untereinheit gibt es hier nicht."})
        if SocialFeed.objects.filter(
            website=website, kind=data["kind"], department=department
        ).exists():
            raise ValidationError({"kind": "Diesen Kanal gibt es hier schon."})
        feed = SocialFeed(
            organization=self.org,
            website=website,
            department=department,
            kind=data["kind"],
        )
        for key in LOGIN_SETTINGS:
            if key in data:
                setattr(feed, key, data[key])
        for key in SETTINGS:
            if key in data:
                setattr(feed, key, data[key])
        social.set_secret(feed, data.get("app_secret", ""))
        feed.save()
        record(self.org, request.user, "create", feed, {"Kanal": [None, str(feed)]})
        return Response(feed_data(feed), status=status.HTTP_201_CREATED)


class FeedDetailView(_FeedMixin, APIView):
    """PUT: Einstellungen, App-ID/-Geheimnis · DELETE: Kanal mit allen Beiträgen löschen."""

    @transaction.atomic
    def put(self, request, org_id: int, pk: int):
        feed = self.feed()
        ser = FeedSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        changes = {}
        for key in SETTINGS:
            if key in data and getattr(feed, key) != data[key]:
                changes[key] = [getattr(feed, key), data[key]]
                setattr(feed, key, data[key])
        for key in LOGIN_SETTINGS:
            if key in data and data[key] != getattr(feed, key):
                changes[key] = [getattr(feed, key), data[key]]
                setattr(feed, key, data[key])
        if data.get("app_secret"):
            social.set_secret(feed, data["app_secret"])
            changes["App-Geheimnis"] = ["…", "neu"]
        feed.save()
        if changes:
            record(self.org, request.user, "update", feed, changes)
        # Der Modus gilt nur für künftige Beiträge; wartende bleiben wartend (UX-Audit 31.10. N07)
        return Response(feed_data(feed))

    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        feed = self.feed()
        record(self.org, request.user, "delete", feed, {"Kanal": [str(feed), None]})
        social.delete_feed(feed)
        return Response(status=status.HTTP_204_NO_CONTENT)


class FeedConnectView(_FeedMixin, APIView):
    """POST: Adresse bei Meta zum Verbinden · DELETE: trennen (löscht Zugang und Beiträge)."""

    def post(self, request, org_id: int, pk: int):
        feed = self.feed()
        try:
            url = social.start_connect(feed, request.user)
        except social.MetaError as exc:
            raise ValidationError(str(exc)) from exc
        return Response({"url": url})

    @transaction.atomic
    def delete(self, request, org_id: int, pk: int):
        feed = self.feed()
        record(self.org, request.user, "update", feed, {"Verbindung": [str(feed), "getrennt"]})
        social.disconnect(feed)
        return Response(feed_data(feed))


class FeedPageView(_FeedMixin, APIView):
    """POST {page}: Facebook-Seite auswählen, wenn das Konto mehrere verwaltet."""

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        feed = self.feed()
        try:
            social.choose_page(feed, str(request.data.get("page") or ""))
        except social.MetaError as exc:
            raise ValidationError(str(exc)) from exc
        record(self.org, request.user, "update", feed, {"Verbindung": [None, str(feed)]})
        return Response(feed_data(feed))


class FeedPublishPendingView(_FeedMixin, APIView):
    """POST: alle wartenden Beiträge des Kanals auf einmal freigeben (ausdrücklich, N07)."""

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        feed = self.feed()
        published = feed.posts.filter(state=SocialPost.State.PENDING).update(
            state=SocialPost.State.VISIBLE
        )
        if published:
            record(
                self.org,
                request.user,
                "update",
                feed,
                {"Wartende Beiträge freigegeben": [None, published]},
            )
        return Response({**feed_data(feed), "published": published})


class FeedSyncView(_FeedMixin, APIView):
    """POST: jetzt abrufen."""

    def post(self, request, org_id: int, pk: int):
        feed = self.feed()
        if not feed.is_connected:
            raise ValidationError("Der Kanal ist nicht verbunden.")
        created = social.sync_feed(feed)
        feed.refresh_from_db()
        return Response({**feed_data(feed), "created": created})


class PostListView(_ContentMixin, APIView):
    """GET ?kanal=<id>: abgerufene Beiträge (neueste zuerst)."""

    def get(self, request, org_id: int):
        qs = SocialPost.objects.filter(feed__website=self.website()).prefetch_related("images")
        feed = request.query_params.get("kanal")
        if feed and feed.isdigit():
            qs = qs.filter(feed_id=int(feed))
        return Response([post_data(self.org.pk, p) for p in qs[:200]])


class PostStateSerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=SocialPost.State.choices, required=False)
    alt_texts = serializers.DictField(
        child=serializers.CharField(max_length=300, allow_blank=True), required=False
    )


class PostDetailView(_ContentMixin, APIView):
    """PUT {state, alt_texts}: freigeben, ausblenden, Alternativtexte der Bilder."""

    @transaction.atomic
    def put(self, request, org_id: int, pk: int):
        post = get_object_or_404(SocialPost, feed__website=self.website(), pk=pk)
        ser = PostStateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        if "state" in data and data["state"] != post.state:
            record(
                self.org,
                request.user,
                "update",
                post,
                {"Status": [post.get_state_display(), SocialPost.State(data["state"]).label]},
            )
            post.state = data["state"]
            post.save(update_fields=["state"])
        for image_id, alt in (data.get("alt_texts") or {}).items():
            SocialPostImage.objects.filter(
                post=post, pk=int(image_id) if image_id.isdigit() else 0
            ).update(alt_text=alt)
        return Response(post_data(self.org.pk, post))


class PostImageFileView(_ContentMixin, APIView):
    def get(self, request, org_id: int, pk: int):
        image = get_object_or_404(SocialPostImage, post__feed__website=self.website(), pk=pk)
        f = image.small if request.query_params.get("size") == "small" else image.file
        ctype = "image/png" if f.name.endswith(".png") else "image/jpeg"
        response = FileResponse(f.open("rb"), content_type=ctype)
        response["Cache-Control"] = "private, max-age=3600"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class CallbackView(APIView):
    """Rückleitung von Meta nach dem Zustimmen (fest in der Meta-App eingetragen).

    Gilt nur für die Person, die das Verbinden gestartet hat, höchstens 15 Minuten
    lang, und nur, solange sie das Recht „Webseite verwalten“ hat.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        state = request.query_params.get("state", "")
        with rls_bypass():
            feed = social.feed_for_state(state, request.user)
            if feed is None:
                return HttpResponseRedirect(
                    social.frontend_return(False, "Anmeldung abgelaufen, bitte neu verbinden.")
                )
            if WEBSITE_MANAGE not in permissions_in(request.user, feed.organization):
                raise NotFound()
            if request.query_params.get("error"):
                feed.oauth_state = ""
                feed.save(update_fields=["oauth_state"])
                reason = request.query_params.get("error_description") or "abgebrochen"
                return HttpResponseRedirect(social.frontend_return(False, reason))
            try:
                social.finish_connect(feed, request.query_params.get("code", ""))
            except social.MetaError as exc:
                feed.refresh_from_db()
                feed.last_error = str(exc)[:500]
                feed.save(update_fields=["last_error"])
                return HttpResponseRedirect(social.frontend_return(False, str(exc)))
            record(
                feed.organization, request.user, "update", feed, {"Verbindung": [None, str(feed)]}
            )
            if feed.status == SocialFeed.Status.OK:
                social.sync_feed(feed)
        return HttpResponseRedirect(social.frontend_return(True))
