"""Schnittstelle für das Anmelden über eine gekoppelte Instanz (siehe ``sso``)."""

from __future__ import annotations

from django.contrib.auth import login
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.ratelimit import client_ip, too_many

from . import sso
from .models import LoginLink, RemoteAccount

RATE = (20, 600)


def _errors(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except DjangoValidationError as exc:
            raise ValidationError({"detail": " ".join(exc.messages)}) from exc
        except DjangoPermissionDenied as exc:
            raise PermissionDenied(str(exc)) from exc

    return wrapper


def _limited(request, kind: str) -> None:
    if too_many(f"peering-sso:{kind}:{client_ip(request)}", *RATE):
        raise ValidationError({"detail": "Zu viele Versuche. Bitte später erneut."})


class _Public(APIView):
    """Ohne Anmeldung erreichbar; CSRF immer prüfen (die Sitzung wird verändert)."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            SessionAuthentication().enforce_csrf(request)


class ChoicesView(_Public):
    def get(self, request):
        return Response(sso.login_choices())


class StartView(_Public):
    @_errors
    def post(self, request):
        _limited(request, "start")
        purpose = str(request.data.get("purpose") or "login")
        peer = sso.peer_by_instance(str(request.data.get("idp") or ""))
        url = sso.start(request._request, peer, purpose, str(request.data.get("next") or "/"))
        return Response({"url": url})


class FinishView(_Public):
    """Bestätigung einlösen; bei Konten mit Rollen danach der eigene Code (``code``)."""

    @_errors
    @transaction.atomic
    def post(self, request):
        _limited(request, "finish")
        if request.data.get("code") is not None and not request.data.get("token"):
            user, peer, next_path = sso.finish_stepup(
                request._request, str(request.data.get("code") or "")
            )
            return self._login(request, user, peer, next_path, stepped_up=True)
        checked = sso.verify(request._request, str(request.data.get("token") or ""))
        purpose = checked["pending"]["purpose"]
        if purpose == "link":
            sso.complete_link(request._request, checked)
            return Response({"purpose": "link", "next": "/mein-konto/app"})
        user = sso.complete_login(checked)
        next_path = checked["pending"]["next"]
        if sso.needs_local_factor(user):
            sso.begin_stepup(request._request, user, checked["peer"], next_path)
            return Response({"purpose": "login", "mfa_required": True})
        return self._login(request, user, checked["peer"], next_path, stepped_up=False)

    def _login(self, request, user, peer, next_path, stepped_up):
        login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")
        response = Response(
            {
                "purpose": "login",
                "next": next_path,
                "user": {"id": user.pk, "email": user.email, "display": user.get_full_name()},
            }
        )
        sso.after_login(request._request, response, user, peer, stepped_up)
        return response


class DescribeView(APIView):
    permission_classes = [IsAuthenticated]

    @_errors
    def get(self, request):
        return Response(sso.describe(str(request.query_params.get("rp") or ""), request.user))


class IssueView(APIView):
    permission_classes = [IsAuthenticated]

    @_errors
    def post(self, request):
        _limited(request, "issue")
        try:
            url = sso.issue(
                request._request,
                str(request.data.get("rp") or ""),
                str(request.data.get("state") or ""),
                str(request.data.get("purpose") or ""),
                password=str(request.data.get("password") or ""),
                code=str(request.data.get("code") or ""),
            )
        except sso.ReauthRequired as exc:
            return Response(
                {"detail": str(exc), "reauth": True, "needs_code": exc.needs_code}, status=409
            )
        return Response({"url": url})


class AccountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(sso.account_data(request.user))


class LinkDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk: int):
        deleted, _ = LoginLink.objects.filter(pk=pk, user=request.user).delete()
        if not deleted:
            raise NotFound()
        return Response(status=204)


class RemoteAccountDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk: int):
        deleted, _ = RemoteAccount.objects.filter(pk=pk, user=request.user).delete()
        if not deleted:
            raise NotFound()
        return Response(status=204)
