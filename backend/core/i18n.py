"""Sprache der Oberfläche (Konzept konzepte/englisch.md).

Zwei Ebenen:

- **Nutzersprache** (``User.language``): alles, was eine Person selbst sieht, also
  Oberfläche, Fehlermeldungen, Hinweis-Mails und Push-Texte an ihr Konto.
- **Vereinssprache** (``Organization.language``, vorerst immer Deutsch): alles, was der
  Verein herausgibt, etwa Belege, Briefe, Rechnungen und die Vereinswebseite.

Deutsch ist Standard und Quellsprache: Die deutschen Texte im Code sind die Schlüssel
für den englischen Katalog (``backend/locale/en/LC_MESSAGES/django.po``).

Die Browsersprache (``Accept-Language``) wird bewusst nicht ausgewertet (Fachfrage F2):
Vor der Anmeldung gilt Deutsch, außer man hat unten auf der Seite umgeschaltet (Cookie).
"""

from __future__ import annotations

from contextlib import contextmanager

from django.conf import settings
from django.utils import translation

DEFAULT = "de"
COOKIE = "hp_lang"
# Gültig für ein Jahr; rein technisch notwendig, keine Einwilligung nötig
COOKIE_MAX_AGE = 365 * 24 * 3600


def available() -> list[str]:
    """Sprachen, die man wählen kann. Deutsch ist immer dabei und steht vorn."""
    known = {code for code, _name in settings.LANGUAGES}
    langs = [code for code in settings.HUBIPLAN_LANGUAGES if code in known]
    return [DEFAULT, *[code for code in langs if code != DEFAULT]]


def normalize(code: str | None) -> str:
    """Nur freigeschaltete Sprachen; alles andere wird Deutsch."""
    code = (code or "").strip().lower()[:5]
    return code if code in available() else DEFAULT


def user_language(user) -> str:
    """Nutzersprache eines Kontos (auch für Mails und Push an dieses Konto)."""
    return normalize(getattr(user, "language", None))


def org_language(org) -> str:
    """Vereinssprache einer Einheit; vorerst immer Deutsch (Fachfrage F10)."""
    return normalize(getattr(org, "language", None))


@contextmanager
def language_of(user):
    """Texte für dieses Konto erzeugen, z. B. in Hintergrundaufgaben oder Mails."""
    with translation.override(user_language(user)):
        yield


@contextmanager
def language_of_org(org):
    """Texte erzeugen, die die Einheit herausgibt (Belege, Briefe, Webseite)."""
    with translation.override(org_language(org)):
        yield


def german(value) -> str:
    """Text fest auf Deutsch, etwa Auswahl-Bezeichnungen in Finanzbelegen (Fachfrage F1).

    Für ``Promise``-Werte (``gettext_lazy``) oder Funktionen ohne Argumente wie
    ``obj.get_status_display``.
    """
    with translation.override(DEFAULT):
        return str(value() if callable(value) else value)


def date_text(value) -> str:
    """Datum in der aktiven Sprache: 01.11.2026 bzw. 01/11/2026 (en-GB, Fachfrage F4)."""
    return value.strftime("%d/%m/%Y" if translation.get_language() == "en" else "%d.%m.%Y")


def datetime_text(value) -> str:
    """Datum und Uhrzeit in der aktiven Sprache, ohne „Uhr“."""
    return f"{date_text(value)} {value:%H:%M}"


def activate_for(request, user=None) -> str:
    """Sprache für diese Anfrage setzen: Konto, sonst Cookie, sonst Deutsch."""
    if user is not None and getattr(user, "is_authenticated", False):
        lang = user_language(user)
    else:
        lang = normalize(request.COOKIES.get(COOKIE))
    translation.activate(lang)
    request.LANGUAGE_CODE = lang
    return lang


class LanguageMiddleware:
    """Setzt die Sprache je Anfrage (nach der Anmeldung über die Sitzung).

    Die App meldet sich erst in DRF mit dem Geräteschlüssel an; dort setzt
    ``devices.auth`` die Sprache des Kontos nach. Die Antwort trägt
    ``Content-Language`` und hält das Cookie ``hp_lang`` passend zum Konto, damit die
    Oberfläche schon beim Laden die richtige Sprache kennt.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        activate_for(request, user)
        response = self.get_response(request)
        lang = translation.get_language() or DEFAULT
        response.headers.setdefault("Content-Language", lang)
        user = getattr(request, "user", None)
        if (
            user is not None
            and getattr(user, "is_authenticated", False)
            and request.COOKIES.get(COOKIE) != user_language(user)
            and not request.path.startswith("/api/app/")
        ):
            set_cookie(response, user_language(user))
        translation.deactivate()
        return response


def set_cookie(response, lang: str) -> None:
    response.set_cookie(
        COOKIE,
        lang,
        max_age=COOKIE_MAX_AGE,
        samesite="Lax",
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=False,  # die Oberfläche liest es beim Start
    )
