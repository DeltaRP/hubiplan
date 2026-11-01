"""Hilfe: abgehakte „Erste Schritte“ am eigenen Konto (konzepte/hilfe-funktion.md, 3.4).

Gespeichert wird nur die Liste der abgehakten Schlüssel, kein Protokoll, welche Hilfe
wie oft geöffnet wurde. Die Schritte selbst stehen im Frontend (src/help/).
Während einer Ansicht als Rolle sperrt access/preview.py das Abhaken.
"""

import re

from django.db import transaction
from django.http import Http404
from django.utils.translation import gettext
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User

STEP_KEY = re.compile(r"^[a-z0-9_.]{1,80}$")
MAX_DONE = 200


def done_keys(user: User) -> list[str]:
    return sorted(k for k in (user.help_done or []) if isinstance(k, str) and STEP_KEY.match(k))


class HelpDoneSerializer(serializers.Serializer):
    help_done = serializers.ListField(child=serializers.CharField())


def _key(key: str) -> str:
    if not STEP_KEY.match(key):
        raise Http404(gettext("Unbekannter Schritt."))
    return key


class HelpDoneView(APIView):
    """GET: abgehakte erste Schritte · DELETE: alle wieder offen."""

    @extend_schema(responses=HelpDoneSerializer)
    def get(self, request):
        return Response({"help_done": done_keys(request.user)})

    @extend_schema(request=None, responses=HelpDoneSerializer)
    def delete(self, request):
        user = request.user
        if user.help_done is not None:
            user.help_done = None
            user.save(update_fields=["help_done"])
        return Response({"help_done": []})


class HelpDoneKeyView(APIView):
    """POST: einen Schritt abhaken · DELETE: Haken wieder entfernen."""

    @extend_schema(request=None, responses=HelpDoneSerializer)
    @transaction.atomic
    def post(self, request, key: str):
        _key(key)
        user = User.objects.select_for_update().get(pk=request.user.pk)
        keys = set(done_keys(user))
        if key not in keys and len(keys) < MAX_DONE:
            user.help_done = sorted(keys | {key})
            user.save(update_fields=["help_done"])
        return Response({"help_done": done_keys(user)})

    @extend_schema(request=None, responses=HelpDoneSerializer)
    @transaction.atomic
    def delete(self, request, key: str):
        _key(key)
        user = User.objects.select_for_update().get(pk=request.user.pk)
        keys = set(done_keys(user))
        if key in keys:
            user.help_done = sorted(keys - {key}) or None
            user.save(update_fields=["help_done"])
        return Response({"help_done": done_keys(user)})
