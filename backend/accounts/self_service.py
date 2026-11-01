"""„Mein Konto“: Name, Passwort und Anmelde-E-Mail selbst ändern.

Gilt für alle angemeldeten Benutzer – Vorstände, Abteilungsrollen und Mitglieder.
Eine neue E-Mail-Adresse wird erst wirksam, wenn der Link an sie bestätigt ist.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import password_validation, update_session_auth_hash
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.i18n import language_of, user_language
from core.ratelimit import too_many
from outbox import mail

from .models import EmailChange, User
from .security import revoke_links, secure_account

EMAIL_CHANGE_DAYS = 2


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def account_data(user: User) -> dict:
    pending = (
        user.email_changes.filter(used_at__isnull=True, expires_at__gt=timezone.now())
        .order_by("-created_at")
        .first()
    )
    return {
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "has_password": user.has_usable_password(),
        "pending_email": pending.new_email if pending else None,
    }


def _too_many(user_id: int, kind: str, limit: int = 10) -> bool:
    return too_many(f"konto:{kind}:{user_id}", limit, 3600)


class NameSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150, allow_blank=True, required=False)
    last_name = serializers.CharField(max_length=150, allow_blank=True, required=False)


class AccountView(APIView):
    """GET: eigene Kontodaten · PATCH: Vor- und Nachname."""

    def get(self, request):
        return Response(account_data(request.user))

    def patch(self, request):
        data = NameSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = request.user
        for key, value in data.validated_data.items():
            setattr(user, key, value.strip())
        user.save(update_fields=list(data.validated_data))
        return Response(account_data(user))


class PasswordSerializer(serializers.Serializer):
    # Passwörter unverändert prüfen und speichern, auch mit Leerzeichen am Rand (AT-F02)
    current_password = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=False
    )
    new_password = serializers.CharField(trim_whitespace=False)


class PasswordView(APIView):
    """Passwort ändern – oder erstmals festlegen (Konten mit Anmeldelink)."""

    def post(self, request):
        data = PasswordSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = request.user
        if _too_many(user.pk, "passwort"):
            return Response(
                {"detail": gettext("Zu viele Versuche. Bitte später erneut.")}, status=429
            )
        had_password = user.has_usable_password()
        if had_password and not user.check_password(data.validated_data.get("current_password")):
            raise serializers.ValidationError(
                {"current_password": gettext("Das bisherige Passwort stimmt nicht.")}
            )
        new = data.validated_data["new_password"]
        try:
            password_validation.validate_password(new, user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from exc
        user.set_password(new)
        user.save(update_fields=["password"])
        update_session_auth_hash(request, user)  # angemeldet bleiben
        # Vorher verschickte Links und QR-Codes gelten nicht mehr. Beim Wechsel eines
        # bestehenden Passworts werden auch alle App-Geräte abgemeldet (wie beim Reset);
        # beim erstmaligen Festlegen bleiben sie, denn es gab kein altes Passwort.
        secure_account(user, devices=had_password)
        with language_of(user):
            if had_password:
                subject = gettext("Ihr Passwort wurde geändert")
                intro = gettext(
                    "für Ihr HUBIplan-Konto {email} wurde soeben das Passwort geändert."
                )
            else:
                subject = gettext("Ihr Passwort wurde festgelegt")
                intro = gettext(
                    "für Ihr HUBIplan-Konto {email} wurde soeben das Passwort festgelegt."
                )
            body = (
                gettext("Guten Tag,")
                + "\n\n"
                + intro.format(email=user.email)
                + "\n\n"
                + gettext(
                    "Waren Sie das nicht? Dann setzen Sie es bitte sofort über „Passwort "
                    "vergessen“ auf der Anmeldeseite zurück und informieren Sie den Vorstand."
                )
                + "\n"
            )
        mail.send(
            user.email,
            subject,
            body,
            kind="konto",
            fail_silently=True,
            language=user_language(user),
        )
        return Response(account_data(user))


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)


class EmailChangeView(APIView):
    """POST: neue Anmelde-E-Mail anfordern (Bestätigungslink an die neue Adresse).
    DELETE: offene Änderung verwerfen."""

    @transaction.atomic
    def post(self, request):
        data = EmailSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = request.user
        if _too_many(user.pk, "email", limit=5):
            return Response(
                {"detail": gettext("Zu viele Versuche. Bitte später erneut.")}, status=429
            )
        if user.has_usable_password() and not user.check_password(
            data.validated_data.get("password")
        ):
            raise serializers.ValidationError({"password": gettext("Das Passwort stimmt nicht.")})
        new = User.objects.normalize_email(data.validated_data["email"]).lower()
        if new == user.email:
            raise serializers.ValidationError(
                {"email": gettext("Das ist schon Ihre Anmelde-E-Mail.")}
            )
        if User.objects.filter(email__iexact=new).exists():
            raise serializers.ValidationError(
                {"email": gettext("Diese E-Mail-Adresse gehört schon zu einem anderen Konto.")}
            )
        request_email_change(user, new)
        return Response(account_data(user), status=status.HTTP_201_CREATED)

    def delete(self, request):
        request.user.email_changes.filter(used_at__isnull=True).delete()
        return Response(account_data(request.user))


def apply_email(user: User, new: str) -> None:
    """Anmelde-E-Mail setzen; alte allauth-Adressen dürfen nicht mehr anmelden."""
    user.email = new
    user.save(update_fields=["email"])
    EmailAddress.objects.filter(user=user).delete()


def request_email_change(user: User, new: str, org_name: str = "") -> None:
    """Neue Anmelde-E-Mail anfordern: Sie gilt erst, wenn der Link an die neue
    Adresse bestätigt ist; die alte Adresse erfährt davon. ``org_name``: Die Einheit hat
    die Adresse aus einer Änderungsmeldung übernommen (Mitgliederbereich)."""
    user.email_changes.filter(used_at__isnull=True).delete()
    token = secrets.token_urlsafe(32)
    EmailChange.objects.create(
        user=user,
        new_email=new,
        token_hash=_hash(token),
        expires_at=timezone.now() + datetime.timedelta(days=EMAIL_CHANGE_DAYS),
    )
    url = f"{settings.FRONTEND_URL}/konto/email/{token}"
    language = user_language(user)
    with language_of(user):
        if org_name:
            reason = gettext(
                "{org} hat Ihre neue E-Mail-Adresse {new} übernommen. Möchten Sie sich bei "
                "HUBIplan künftig auch damit anmelden (bisher {old})?"
            ).format(org=org_name, new=new, old=user.email)
        else:
            reason = gettext(
                "Sie möchten sich bei HUBIplan künftig mit {new} anmelden (bisher {old})."
            ).format(new=new, old=user.email)
        confirm_subject = gettext("Bitte bestätigen Sie Ihre neue E-Mail-Adresse")
        confirm_body = (
            gettext("Guten Tag,")
            + "\n\n"
            + reason
            + "\n\n"
            + gettext(
                "Bitte bestätigen Sie die Adresse mit diesem Link (gültig {days} Tage):"
            ).format(days=EMAIL_CHANGE_DAYS)
            + f"\n\n{url}\n\n"
            + gettext("Haben Sie das nicht veranlasst, ignorieren Sie diese Mail einfach.")
            + "\n"
        )
        notice_subject = gettext("Änderung Ihrer Anmelde-E-Mail angefordert")
        notice_body = (
            gettext("Guten Tag,")
            + "\n\n"
            + gettext(
                "für Ihr HUBIplan-Konto wurde die neue Anmelde-E-Mail {new} angefordert. Sie "
                "wird erst wirksam, wenn sie über den Link an die neue Adresse bestätigt ist."
            ).format(new=new)
            + "\n\n"
            + gettext("Waren Sie das nicht? Dann ändern Sie bitte Ihr Passwort.")
            + "\n"
        )
    mail.send(new, confirm_subject, confirm_body, kind="konto", language=language)
    mail.send(
        user.email,
        notice_subject,
        notice_body,
        kind="konto",
        fail_silently=True,
        language=language,
    )


class EmailConfirmView(APIView):
    """Bestätigungslink einlösen (ohne Anmeldung erreichbar)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @transaction.atomic
    def post(self, request, token: str):
        change = (
            EmailChange.objects.select_for_update()
            .select_related("user")
            .filter(
                token_hash=_hash(token),
                used_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .first()
        )
        if change is None:
            return Response(
                {"detail": gettext("Der Link ist ungültig, abgelaufen oder schon benutzt.")},
                status=404,
            )
        if User.objects.filter(email__iexact=change.new_email).exclude(pk=change.user_id).exists():
            return Response(
                {
                    "detail": gettext(
                        "Diese E-Mail-Adresse gehört inzwischen zu einem anderen Konto."
                    )
                },
                status=409,
            )
        change.used_at = timezone.now()
        change.save(update_fields=["used_at"])
        apply_email(change.user, change.new_email)
        revoke_links(change.user)  # Anmeldelinks an die alte Adresse gelten nicht mehr
        return Response({"email": change.new_email})
