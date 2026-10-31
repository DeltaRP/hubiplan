"""API für Mitgliederfotos und persönliche Upload-Links."""

from __future__ import annotations

import datetime

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import MEMBERS_VIEW, PHOTOS_MANAGE
from audit.log import record
from core.ratelimit import client_ip, too_many
from core.tenancy import rls_bypass, tenant_context
from devices.push import notify_membership
from organizations.imprint import ensure as ensure_imprint
from organizations.theme import effective_theme

from . import photos, services
from .models import Membership
from .photo_models import MemberPhoto, PhotoUploadLink, hash_token
from .views import _ClubMixin

LINK_DAYS = 14


def photo_info(membership: Membership, org_id: int) -> dict:
    """Foto-Angaben für die Mitgliedsakte."""
    result = {"approved": None, "pending": None}
    for photo in MemberPhoto.objects.filter(membership=membership):
        version = int(photo.updated_at.timestamp())
        base = (
            f"/api/orgs/{org_id}/members/{membership.pk}/photo/?status={photo.status}&v={version}"
        )
        result[photo.status] = {
            "url": base,
            "thumbnail_url": f"{base}&size=thumb",
            "source": photo.source,
            "source_label": photo.get_source_display(),
            "uploaded_at": photo.updated_at,
        }
    return result


class _PhotoView(_ClubMixin, APIView):
    read_permission = MEMBERS_VIEW
    write_permission = PHOTOS_MANAGE
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def membership(self) -> Membership:
        return get_object_or_404(
            Membership.objects.select_related("person"), organization=self.org, pk=self.kwargs["pk"]
        )

    def respond(self, membership):
        membership.refresh_from_db()
        return Response(
            {
                "photo": photo_info(membership, self.org.pk),
                "photo_consent_at": membership.photo_consent_at,
                "photo_consent_source": membership.photo_consent_source,
            }
        )


class MemberPhotoView(_PhotoView):
    """GET: Bild ausliefern · POST: hochladen/ersetzen · DELETE: löschen."""

    def get(self, request, org_id: int, pk: int):
        membership = self.membership()
        status_ = request.query_params.get("status", "approved")
        if status_ == "pending" and PHOTOS_MANAGE not in self.org_permissions:
            raise Http404
        photo = MemberPhoto.objects.filter(membership=membership, status=status_).first()
        if photo is None:
            raise Http404
        field = photo.thumbnail if request.query_params.get("size") == "thumb" else photo.image
        response = FileResponse(field.open("rb"), content_type="image/jpeg")
        response["Cache-Control"] = "private, max-age=86400"
        return response

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        membership = self.membership()
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": "Bitte ein Bild wählen."})
        consent = str(request.data.get("consent", "")).lower() in ("1", "true", "ja", "on")
        if not membership.photo_consent_at:
            if not consent:
                raise serializers.ValidationError(
                    {"consent": "Bitte bestätigen, dass die Einwilligung des Mitglieds vorliegt."}
                )
            membership.photo_consent_at = timezone.localdate()
            membership.photo_consent_source = "board"
            membership.save(update_fields=["photo_consent_at", "photo_consent_source"])
        processed = photos.process(upload)
        had = MemberPhoto.objects.filter(membership=membership, status="approved").exists()
        photos.store(membership, processed, "approved", "board", request.user)
        record(
            self.org,
            request.user,
            "update" if had else "create",
            membership,
            {"Foto": [None, "ersetzt" if had else "hochgeladen"]},
            person=membership.person,
        )
        return self.respond(membership)

    def delete(self, request, org_id: int, pk: int):
        membership = self.membership()
        status_ = request.query_params.get("status", "approved")
        if photos.remove(membership, status_):
            record(
                self.org,
                request.user,
                "delete",
                membership,
                {"Foto": ["vorhanden", None]},
                person=membership.person,
            )
        return self.respond(membership)


class PhotoRotateView(_PhotoView):
    def post(self, request, org_id: int, pk: int):
        membership = self.membership()
        photo = MemberPhoto.objects.filter(membership=membership, status="approved").first()
        if photo is None:
            raise serializers.ValidationError("Kein Foto vorhanden.")
        degrees = 90 if request.data.get("direction") == "left" else -90
        photos.rotate(photo, degrees)
        record(
            self.org,
            request.user,
            "update",
            membership,
            {"Foto": [None, "gedreht"]},
            person=membership.person,
        )
        return self.respond(membership)


class PhotoApproveView(_PhotoView):
    """Vom Mitglied hochgeladenes Foto freigeben oder ablehnen."""

    def post(self, request, org_id: int, pk: int):
        membership = self.membership()
        if request.data.get("decision") == "reject":
            photos.remove(membership, "pending")
            record(
                self.org,
                request.user,
                "delete",
                membership,
                {"Foto des Mitglieds": [None, "abgelehnt"]},
                person=membership.person,
            )
            notify_membership(membership.pk, "Dein Foto wurde nicht übernommen", self.org.name)
        else:
            photos.approve(membership)
            record(
                self.org,
                request.user,
                "update",
                membership,
                {"Foto des Mitglieds": [None, "freigegeben"]},
                person=membership.person,
            )
            notify_membership(membership.pk, "Dein Foto wurde freigegeben", self.org.name)
        return self.respond(membership)


class ConsentSerializer(serializers.Serializer):
    photo_consent_at = serializers.DateField(allow_null=True)


class PhotoConsentView(_PhotoView):
    """Einwilligung festhalten oder widerrufen (Widerruf löscht die Fotos)."""

    write_permission = PHOTOS_MANAGE

    @transaction.atomic
    def patch(self, request, org_id: int, pk: int):
        membership = self.membership()
        data = ConsentSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        before = membership.photo_consent_at
        membership.photo_consent_at = data.validated_data["photo_consent_at"]
        membership.photo_consent_source = "board" if membership.photo_consent_at else ""
        membership.save(update_fields=["photo_consent_at", "photo_consent_source"])
        if membership.photo_consent_at is None:
            # Ohne Einwilligung kein Foto
            for s in ("approved", "pending"):
                photos.remove(membership, s)
        record(
            self.org,
            request.user,
            "update",
            membership,
            {
                "Foto-Einwilligung": [
                    str(before) if before else None,
                    str(membership.photo_consent_at) if membership.photo_consent_at else None,
                ]
            },
            person=membership.person,
        )
        return self.respond(membership)


# --- Upload-Links ---


def link_data(link: PhotoUploadLink) -> dict:
    return {
        "id": link.pk,
        "state": link.state,
        "created_at": link.created_at,
        "expires_at": link.expires_at,
        "used_at": link.used_at,
        "sent_to": link.sent_to,
    }


class PhotoLinkView(_PhotoView):
    """Upload-Links eines Mitglieds anzeigen (GET) und erzeugen (POST)."""

    read_permission = PHOTOS_MANAGE

    def get(self, request, org_id: int, pk: int):
        membership = self.membership()
        return Response([link_data(link) for link in membership.photo_links.all()])

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        membership = self.membership()
        token = PhotoUploadLink.new_token()
        link = PhotoUploadLink.objects.create(
            organization=self.org,
            membership=membership,
            token_hash=hash_token(token),
            created_by=request.user,
            expires_at=timezone.now() + datetime.timedelta(days=LINK_DAYS),
        )
        url = f"{settings.FRONTEND_URL}/foto/{token}"
        if str(request.data.get("send_email", "")).lower() in ("1", "true", "on"):
            contact = services.contact_for(membership.person, self.org)
            if contact is None or not contact.email:
                raise serializers.ValidationError(
                    "Für dieses Mitglied ist keine E-Mail-Adresse hinterlegt."
                )
            send_mail(
                f"Ihr Foto für {self.org.name}",
                (
                    f"Hallo {membership.person.first_name},\n\n"
                    f"{self.org.name} bittet Sie um ein Foto für die Mitgliederverwaltung.\n"
                    f"Über diesen persönlichen Link können Sie es hochladen und zuschneiden "
                    f"(gültig bis {timezone.localtime(link.expires_at):%d.%m.%Y}, "
                    f"einmal nutzbar):\n\n"
                    f"{url}\n\n"
                    f"{self.org.name} verwendet das Foto in der Mitgliederverwaltung und auf "
                    f"Ihrem digitalen Mitgliedsausweis. Wer den QR-Code oder Link Ihres "
                    f"Ausweises öffnet, sieht dort auch das Foto. Sie können Ihre Einwilligung "
                    f"jederzeit beim Vorstand widerrufen; das Foto wird dann gelöscht.\n"
                ),
                settings.DEFAULT_FROM_EMAIL,
                [contact.email],
            )
            link.sent_to = contact.email
            link.save(update_fields=["sent_to"])
        record(
            self.org,
            request.user,
            "create",
            membership,
            {
                "Foto-Upload-Link": [
                    None,
                    f"gültig bis {link.expires_at:%d.%m.%Y}"
                    + (f", gesendet an {link.sent_to}" if link.sent_to else ""),
                ]
            },
            person=membership.person,
        )
        # Die Adresse wird nur dieses eine Mal angezeigt; gespeichert ist nur der Hash.
        return Response({**link_data(link), "url": url}, status=status.HTTP_201_CREATED)


class PhotoLinkRevokeView(_PhotoView):
    def post(self, request, org_id: int, pk: int, link_id: int):
        membership = self.membership()
        link = get_object_or_404(PhotoUploadLink, membership=membership, pk=link_id)
        if link.revoked_at is None:
            link.revoked_at = timezone.now()
            link.save(update_fields=["revoked_at"])
            record(
                self.org,
                request.user,
                "update",
                membership,
                {"Foto-Upload-Link": [None, "widerrufen"]},
                person=membership.person,
            )
        return Response(link_data(link))


# --- Öffentliche Upload-Seite (ohne Konto) ---

RATE_GET = (30, 600)  # 30 Aufrufe je 10 Minuten und IP
RATE_POST = (5, 600)  # 5 Uploads je 10 Minuten und IP


def _rate_limited(request, kind: str, limit: tuple[int, int]) -> bool:
    return too_many(f"photo-link:{kind}:{client_ip(request)}", limit[0], limit[1])


def _valid_link(token: str) -> PhotoUploadLink:
    with rls_bypass():
        link = (
            PhotoUploadLink.objects.select_related("membership__person", "organization")
            .filter(token_hash=hash_token(token))
            .first()
        )
    # Deaktivierte Organisation: Link gesperrt (Audit B-V05)
    if link is None or link.state != "open" or not link.organization.is_active:
        raise Http404
    return link


class PublicPhotoUploadView(APIView):
    """Persönliche Upload-Seite für Mitglieder: zeigt nur Vorname und Vereinslogo."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, token: str):
        if _rate_limited(request, "get", RATE_GET):
            return Response({"detail": "Zu viele Aufrufe. Bitte später erneut."}, status=429)
        link = _valid_link(token)
        org = link.organization
        theme = effective_theme(org.ancestors())
        return Response(
            {
                "first_name": link.membership.person.first_name,
                "organization": org.name,
                "imprint_key": ensure_imprint(org).public_key,
                "logo_url": theme["logo_url"],
                "theme": {k: theme[k] for k in ("primary", "on_primary", "accent", "on_accent")},
                "expires_at": link.expires_at,
                "needs_approval": org.photo_approval_required,
            }
        )

    def post(self, request, token: str):
        if _rate_limited(request, "post", RATE_POST):
            return Response({"detail": "Zu viele Versuche. Bitte später erneut."}, status=429)
        link = _valid_link(token)
        if str(request.data.get("consent", "")).lower() not in ("1", "true", "on"):
            raise serializers.ValidationError(
                {"consent": "Bitte stimmen Sie der Verwendung des Fotos zu."}
            )
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": "Bitte ein Bild wählen."})
        processed = photos.process(upload)
        org = link.organization
        membership = link.membership
        with tenant_context(org.pk), transaction.atomic():
            # Einmal nutzbar: Link sperren, bevor gespeichert wird
            # Alle Bedingungen erneut prüfen: Während der Bildverarbeitung kann der
            # Link widerrufen worden oder abgelaufen sein (Audit 29.10. ID-V02)
            now = timezone.now()
            claimed = PhotoUploadLink.objects.filter(
                pk=link.pk, used_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now
            ).update(used_at=now)
            if not claimed:
                raise Http404
            status_ = "pending" if org.photo_approval_required else "approved"
            photos.store(membership, processed, status_, "member")
            Membership.objects.filter(pk=membership.pk).update(
                photo_consent_at=timezone.localdate(), photo_consent_source="member"
            )
            record(
                org,
                None,
                "update",
                membership,
                {
                    "Foto": [
                        None,
                        "vom Mitglied über Upload-Link hochgeladen"
                        + (" (wartet auf Freigabe)" if status_ == "pending" else ""),
                    ],
                    "Foto-Einwilligung": [None, f"{timezone.localdate():%d.%m.%Y} (Mitglied)"],
                },
                person=membership.person,
            )
        return Response({"status": status_}, status=status.HTTP_201_CREATED)


# --- Mitgliederbereich und App: eigenes Foto ---

RATE_PORTAL = (5, 600)  # 5 Uploads je 10 Minuten und Konto


class _PortalPhotoMixin:
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        from portal.views import _portal_access

        self.access = _portal_access(request.user, kwargs["access_id"])
        self.club = self.access.organization

    def membership(self) -> Membership:
        return Membership.objects.select_related("person").get(pk=self.access.membership_id)

    def state(self) -> dict:
        with tenant_context(self.club.pk, self.request.user.pk):
            m = self.membership()
            base = f"/api/portal/{self.access.pk}/photo/image/"
            out: dict = {
                "consent_at": m.photo_consent_at,
                "consent_source": m.photo_consent_source,
                # Fotos aus der App gibt der Vorstand immer erst frei
                "needs_approval": True,
                "organization": self.club.name,
                "approved": None,
                "pending": None,
            }
            for photo in MemberPhoto.objects.filter(membership=m):
                version = int(photo.updated_at.timestamp())
                out[photo.status] = {
                    "url": f"{base}?status={photo.status}&v={version}",
                    "thumbnail_url": f"{base}?status={photo.status}&size=thumb&v={version}",
                    "uploaded_at": photo.updated_at,
                }
        return out


class PortalPhotoView(_PortalPhotoMixin, APIView):
    """Eigenes Foto: GET Stand · POST hochladen (mit Einwilligung, wartet auf Freigabe) ·
    DELETE Einwilligung widerrufen und alle Fotos löschen."""

    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, access_id: int):
        return Response(self.state())

    def post(self, request, access_id: int):
        if too_many(f"portal-photo:{request.user.pk}", RATE_PORTAL[0], RATE_PORTAL[1]):
            return Response({"detail": "Zu viele Versuche. Bitte später erneut."}, status=429)
        if str(request.data.get("consent", "")).lower() not in ("1", "true", "on"):
            raise serializers.ValidationError(
                {"consent": "Bitte stimme der Verwendung des Fotos zu."}
            )
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": "Bitte ein Bild wählen."})
        processed = photos.process(upload)
        with tenant_context(self.club.pk, request.user.pk), transaction.atomic():
            m = self.membership()
            photos.store(
                m, processed, MemberPhoto.Status.PENDING, MemberPhoto.Source.APP, request.user
            )
            Membership.objects.filter(pk=m.pk).update(
                photo_consent_at=timezone.localdate(), photo_consent_source="app"
            )
            record(
                self.club,
                request.user,
                "update",
                m,
                {
                    "Foto": [None, "vom Mitglied in der App hochgeladen (wartet auf Freigabe)"],
                    "Foto-Einwilligung": [None, f"{timezone.localdate():%d.%m.%Y} (Mitglied, App)"],
                },
                person=m.person,
            )
        return Response(self.state(), status=status.HTTP_201_CREATED)

    def delete(self, request, access_id: int):
        with tenant_context(self.club.pk, request.user.pk), transaction.atomic():
            m = self.membership()
            had = MemberPhoto.objects.filter(membership=m).exists()
            for photo in MemberPhoto.objects.filter(membership=m):
                photo.delete_files()
                photo.delete()
            Membership.objects.filter(pk=m.pk).update(
                photo_consent_at=None, photo_consent_source=""
            )
            if had or m.photo_consent_at:
                record(
                    self.club,
                    request.user,
                    "update",
                    m,
                    {
                        "Foto": ["vorhanden" if had else None, "vom Mitglied gelöscht"],
                        "Foto-Einwilligung": ["erteilt", "vom Mitglied widerrufen"],
                    },
                    person=m.person,
                )
        return Response(self.state())


class PortalPhotoImageView(_PortalPhotoMixin, APIView):
    """Eigenes Foto als Bild (freigegeben oder wartend)."""

    def get(self, request, access_id: int):
        status_ = request.query_params.get("status", "approved")
        with tenant_context(self.club.pk, request.user.pk):
            photo = MemberPhoto.objects.filter(
                membership_id=self.access.membership_id, status=status_
            ).first()
            if photo is None:
                raise Http404
            field = photo.thumbnail if request.query_params.get("size") == "thumb" else photo.image
            response = FileResponse(field.open("rb"), content_type="image/jpeg")
        response["Cache-Control"] = "private, max-age=86400"
        return response
