"""Anmelden über eine gekoppelte Instanz (Verbund Schritt 7).

Wer Zugänge auf mehreren HUBIplan-Instanzen hat, verknüpft sie einmal und meldet
sich danach mit dem Zugang der Heimat-Instanz an. Rechte gibt das keine: Jede
Instanz vergibt ihre Rollen weiter selbst.

Ablauf (Z = Instanz mit der Einheit, H = Heimat-Instanz):

1. Z merkt sich in der Sitzung des Browsers einen Zufallswert (``state``) und
   schickt den Browser zu H.
2. H fragt die angemeldete Person (mit 2FA, falls eingerichtet), ob sie sich bei Z
   anmelden will, und stellt eine Anmeldebestätigung aus: für Z verschlüsselt
   (X25519/ChaCha20-Poly1305) und mit dem Schlüssel von H unterschrieben (Ed25519),
   gültig zwei Minuten, nur einmal nutzbar.
3. Der Browser bringt sie im Adressteil nach ``#`` (geht an keinen Server) zur
   Seite von Z, die sie an Z schickt. Z prüft Unterschrift mit dem beim Koppeln
   gespeicherten Schlüssel von H, Empfänger, Ablauf, ``state`` der eigenen Sitzung
   und meldet das verknüpfte Konto an.

Nur zwischen Instanzen mit aktiver Kopplung; Z muss die Anmeldung über gekoppelte
Instanzen eingeschaltet haben. Ist hier 2FA eingerichtet, muss auch die Anmeldung
auf H mit 2FA erfolgt sein. Plattformverwaltung meldet sich nie über eine andere
Instanz an.
"""

from __future__ import annotations

import datetime
import json
import secrets
import time

from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.utils.translation import gettext

from . import crypto, identity
from .models import Coupling, LoginLink, Peer, RemoteAccount, UsedAssertion

TOKEN_SECONDS = 120
# Anmeldebestätigung nur aus einer frischen Anmeldung (Passwort bzw. 2FA höchstens so alt)
FRESH_SECONDS = 12 * 60 * 60
# Sitzungen aus einer Anmeldung über eine andere Instanz laufen kürzer
SSO_SESSION_SECONDS = 12 * 60 * 60
STEPUP_KEY = "peering_sso_stepup"
STEPUP_SECONDS = 300
SEEN_COOKIE = "hubiplan_verbund_bekannt"
AMR_NAMES = {"password": "pwd", "mfa": "mfa", "code": "code", "link": "link", "peering": "peering"}
STATE_SECONDS = 600
SESSION_KEY = "peering_sso"
PURPOSES = ("login", "link")
# Nur aktive Kopplungen: Wer pausiert, will auch keine Anmeldungen von dort
OPEN = (Coupling.State.ACTIVE,)


def login_enabled() -> bool:
    from organizations.models import PlatformSettings

    s = PlatformSettings.load()
    return s.peering_enabled and s.peering_login


def coupled_peers():
    """Instanzen, mit denen gerade eine Kopplung besteht."""
    return (
        Peer.objects.filter(couplings__state__in=OPEN)
        .exclude(instance_id=identity.identity().instance_id)
        .distinct()
        .order_by("base_url")
    )


def peer_by_instance(instance_id: str) -> Peer:
    peer = coupled_peers().filter(instance_id=_uuid(instance_id)).first()
    if peer is None:
        raise ValidationError(gettext("Mit dieser Instanz besteht keine Kopplung."))
    return peer


def _uuid(value) -> str | None:
    import uuid

    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        return None


def _uses_mfa(user) -> bool:
    from allauth.mfa.models import Authenticator

    return Authenticator.objects.filter(user=user).exists()


def _is_platform_admin(user) -> bool:
    from access.permissions import is_platform_admin

    return user.is_superuser or user.is_staff or is_platform_admin(user)


# --- Z: Anmeldung beginnen ---


def start(request, peer: Peer, purpose: str, next_path: str = "") -> str:
    """Zufallswert in der Sitzung merken; liefert die Adresse der Bestätigungsseite bei H."""
    if purpose not in PURPOSES:
        raise ValidationError(gettext("Unbekannter Zweck."))
    if not login_enabled():
        raise ValidationError(
            gettext(
                "Die Anmeldung über gekoppelte Instanzen ist auf dieser Instanz nicht "
                "eingeschaltet."
            )
        )
    if purpose == "link":
        if not request.user.is_authenticated:
            raise PermissionDenied(gettext("Zum Verknüpfen bitte zuerst hier anmelden."))
        if _is_platform_admin(request.user):
            raise PermissionDenied(
                gettext("Zugänge der Plattformverwaltung werden nicht verknüpft.")
            )
    state = secrets.token_urlsafe(24)
    request.session[SESSION_KEY] = {
        "state": state,
        "peer": str(peer.instance_id),
        "purpose": purpose,
        "user": request.user.pk if purpose == "link" else None,
        "next": _safe_next(next_path),
        "until": int(time.time()) + STATE_SECONDS,
    }
    from urllib.parse import urlencode

    query = urlencode({"rp": identity.identity().instance_id, "state": state, "purpose": purpose})
    return f"{peer.base_url.rstrip('/')}/verbund/anmelden?{query}"


def _safe_next(path: str) -> str:
    path = str(path or "")
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path[:300]


# --- H: Anmeldebestätigung ausstellen ---


class ReauthRequired(Exception):
    """Die Anmeldung hier ist zu alt (oder ohne 2FA): erst Passwort und ggf. Code bestätigen."""

    def __init__(self, needs_code: bool):
        super().__init__(
            "Bitte zur Sicherheit Passwort" + (" und Code" if needs_code else "") + " bestätigen."
        )
        self.needs_code = needs_code


def _records(request) -> list[dict]:
    from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY

    return [
        r
        for r in request.session.get(AUTHENTICATION_METHODS_SESSION_KEY, [])
        if isinstance(r, dict)
    ]


def record(request, user, method: str, **extra) -> None:
    """Anmeldeweg in der Sitzung vermerken (wie allauth es für Passwort und 2FA tut)."""
    from allauth.account.internal.flows.login import record_authentication

    record_authentication(request, user, method, **extra)


def session_auth(request) -> dict:
    """Wie und wann sich diese Sitzung angemeldet hat: ``amr`` und ``auth_time``."""
    records = _records(request)
    amr = sorted({AMR_NAMES.get(str(r.get("method")), str(r.get("method"))) for r in records})
    times = [float(r.get("at") or 0) for r in records]
    mfa_times = [float(r.get("at") or 0) for r in records if r.get("method") == "mfa"]
    return {
        "amr": amr,
        "auth_time": int(max(times)) if times else 0,
        "mfa_time": int(max(mfa_times)) if mfa_times else 0,
    }


def check_second_factor(user, code: str) -> bool:
    """TOTP-Code oder Wiederherstellungscode des Kontos prüfen."""
    from allauth.mfa.models import Authenticator
    from allauth.mfa.recovery_codes.internal.auth import RecoveryCodes
    from allauth.mfa.totp.internal.auth import TOTP

    code = "".join(str(code or "").split())
    if not code:
        return False
    for auth in Authenticator.objects.filter(user=user):
        if auth.type == Authenticator.Type.TOTP and TOTP(auth).validate_code(code):
            return True
        if auth.type == Authenticator.Type.RECOVERY_CODES and RecoveryCodes(auth).validate_code(
            code
        ):
            return True
    return False


def _ensure_fresh(request, user, password: str, code: str) -> None:
    """Nur aus frischer Anmeldung bestätigen; sonst Passwort (und 2FA) neu abfragen."""
    now = time.time()
    info = session_auth(request)
    needs_code = _uses_mfa(user)
    fresh = info["auth_time"] >= now - FRESH_SECONDS and (
        not needs_code or info["mfa_time"] >= now - FRESH_SECONDS
    )
    if fresh:
        return
    if not password:
        raise ReauthRequired(needs_code)
    if not user.check_password(password):
        raise PermissionDenied(gettext("Das Passwort stimmt nicht."))
    if needs_code and not check_second_factor(user, code):
        raise PermissionDenied(gettext("Der Code stimmt nicht."))
    record(request, user, "password")
    if needs_code:
        record(request, user, "mfa", type="totp")


def describe(rp_instance: str, user) -> dict:
    """Für die Bestätigungsseite auf H: wer fragt, und ist das Konto dort schon verknüpft?"""
    peer = peer_by_instance(rp_instance)
    return {
        "base_url": peer.base_url,
        "fingerprint": peer.fingerprint,
        "linked": RemoteAccount.objects.filter(user=user, peer=peer).exists(),
    }


def issue(
    request, rp_instance: str, state: str, purpose: str, password: str = "", code: str = ""
) -> str:
    """Bestätigung für die angemeldete Person ausstellen; liefert die Rücksprungadresse.

    Die Bestätigung sagt, wie und wann sich die Person hier angemeldet hat (``amr``,
    ``auth_time``). Sitzungen, die selbst über eine andere Instanz entstanden sind,
    stellen keine aus (keine Ketten)."""
    from .services import enabled

    if not enabled():
        raise ValidationError(gettext("Der Verbund ist auf dieser Instanz nicht eingeschaltet."))
    user = request.user
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied(gettext("Bitte zuerst anmelden."))
    if purpose not in PURPOSES or not state or len(state) > 100:
        raise ValidationError(gettext("Die Anfrage ist unvollständig."))
    if _is_platform_admin(user):
        raise PermissionDenied(
            gettext("Zugänge der Plattformverwaltung melden sich nicht anderswo an.")
        )
    peer = peer_by_instance(rp_instance)
    if "peering" in session_auth(request)["amr"]:
        raise PermissionDenied(
            gettext(
                "Diese Anmeldung stammt selbst von einer anderen Instanz. Bitte hier "
                "direkt mit Passwort anmelden."
            )
        )
    _ensure_fresh(request, user, password, code)
    auth = session_auth(request)
    ident = identity.identity()
    now = int(time.time())
    assertion = {
        "v": 2,
        "amr": auth["amr"],
        "auth_time": auth["auth_time"],
        "iss": ident.instance_id,
        "aud": str(peer.instance_id),
        "sub": str(user.pk),
        "email": user.email,
        "name": user.get_full_name(),
        # Diese Sitzung hat einen zweiten Faktor genutzt (nicht nur: Konto hat 2FA)
        "mfa": "mfa" in auth["amr"],
        "state": state,
        "purpose": purpose,
        "iat": now,
        "exp": now + TOKEN_SECONDS,
        "jti": secrets.token_urlsafe(16),
    }
    envelope = crypto.seal(
        assertion,
        sender=ident.instance_id,
        recipient=str(peer.instance_id),
        recipient_enc_key=peer.enc_public_key,
    )
    signature = ident.sign(_canonical(envelope))
    outer = {"env": envelope, "sig": signature}
    # Während eines Schlüsselwechsels auch mit dem alten Schlüssel (Partner ohne neuen Schlüssel)
    previous = ident.sign_previous(_canonical(envelope))
    if previous:
        outer["sig2"] = previous
    token = identity.b64(_canonical(outer))
    # Für die Einheitenauswahl hier merken (nur beim Verknüpfen neu anlegen)
    if purpose == "link":
        RemoteAccount.objects.get_or_create(user=user, peer=peer)
    RemoteAccount.objects.filter(user=user, peer=peer).update(last_used_at=timezone.now())
    return f"{peer.base_url.rstrip('/')}/verbund/angemeldet#{token}"


def _canonical(data: dict) -> bytes:
    return json.dumps(data, separators=(",", ":"), sort_keys=True).encode()


# --- Z: Bestätigung prüfen ---


def verify(request, token: str) -> dict:
    """Prüft die Bestätigung gegen die Sitzung; liefert Zweck, Konto-Kennung und Ziel."""
    pending = request.session.pop(SESSION_KEY, None)
    if not pending or pending.get("until", 0) < time.time():
        raise ValidationError(gettext("Die Anmeldung ist abgelaufen. Bitte erneut beginnen."))
    if not login_enabled():
        raise ValidationError(gettext("Die Anmeldung über gekoppelte Instanzen ist ausgeschaltet."))
    try:
        outer = json.loads(identity.unb64(str(token or "")[:8000]))
        envelope, signature = outer["env"], outer["sig"]
        signature2 = str(outer.get("sig2") or "")
        sender = str(envelope["from"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValidationError(gettext("Die Anmeldebestätigung ist beschädigt.")) from exc
    if sender != pending["peer"]:
        raise ValidationError(gettext("Die Bestätigung kommt von einer anderen Instanz."))
    peer = peer_by_instance(sender)
    if not any(
        identity.verify(key, _canonical(envelope), sig)
        for key in (peer.public_key, peer.valid_previous_key)
        for sig in (str(signature), signature2)
    ):
        raise ValidationError(gettext("Die Unterschrift der Anmeldebestätigung stimmt nicht."))
    try:
        data = crypto.open_sealed(envelope, identity.identity())
    except crypto.CryptoError as exc:
        raise ValidationError(gettext("Die Anmeldebestätigung lässt sich nicht öffnen.")) from exc
    now = time.time()
    if (
        data.get("iss") != sender
        or data.get("aud") != identity.identity().instance_id
        or data.get("purpose") != pending["purpose"]
        or not secrets.compare_digest(str(data.get("state", "")), pending["state"])
        or not isinstance(data.get("exp"), int)
        or data["exp"] < now
        or data.get("iat", 0) > now + 60
        or not data.get("sub")
    ):
        raise ValidationError(gettext("Die Anmeldebestätigung passt nicht zu dieser Anmeldung."))
    amr = data.get("amr")
    if (
        not isinstance(data.get("v"), int)
        or data["v"] < 2
        or not isinstance(amr, list)
        or not isinstance(data.get("auth_time"), int)
        or data["auth_time"] < now - FRESH_SECONDS - 60
        or "peering" in amr
    ):
        raise ValidationError(
            gettext(
                "Die andere Instanz bestätigt die Anmeldung nicht ausreichend (zu alt "
                "oder veraltete Version). Bitte dort neu anmelden oder die andere "
                "Instanz aktualisieren."
            )
        )
    jti = str(data.get("jti") or "")[:64]
    if not jti or not cache.add(f"peering-sso-jti:{sender}:{jti}", 1, TOKEN_SECONDS + 60):
        raise ValidationError(gettext("Die Anmeldebestätigung wurde schon benutzt."))
    from django.db import IntegrityError, transaction
    from django.utils import timezone as tz

    try:
        with transaction.atomic():
            UsedAssertion.objects.create(
                peer=peer,
                jti=jti,
                expires_at=tz.now() + datetime.timedelta(seconds=TOKEN_SECONDS + 60),
            )
    except IntegrityError as exc:
        raise ValidationError(gettext("Die Anmeldebestätigung wurde schon benutzt.")) from exc
    UsedAssertion.objects.filter(expires_at__lt=tz.now()).delete()
    return {"peer": peer, "data": data, "pending": pending}


def complete_link(request, checked: dict) -> LoginLink:
    pending, peer, data = checked["pending"], checked["peer"], checked["data"]
    user = request.user
    if not user.is_authenticated or user.pk != pending.get("user"):
        raise PermissionDenied(gettext("Die Verknüpfung gehört zu einem anderen Konto."))
    subject = str(data["sub"])[:64]
    other = LoginLink.objects.filter(peer=peer, subject=subject).exclude(user=user).first()
    if other is not None:
        raise ValidationError(
            gettext("Dieser Zugang ist hier schon mit einem anderen Konto verknüpft.")
        )
    link, _ = LoginLink.objects.update_or_create(
        user=user,
        peer=peer,
        defaults={"subject": subject, "email": str(data.get("email") or "")[:254]},
    )
    return link


def complete_login(checked: dict):
    """Konto zur Bestätigung; nur mit Verknüpfung und nie schwächer als hier vorgesehen."""
    peer, data = checked["peer"], checked["data"]
    link = (
        LoginLink.objects.select_related("user")
        .filter(peer=peer, subject=str(data["sub"])[:64])
        .first()
    )
    if link is None:
        raise ValidationError(
            gettext(
                "Dieser Zugang ist hier mit keinem Konto verknüpft. Bitte einmal mit dem "
                "Zugang dieser Instanz anmelden und unter Mein Konto verknüpfen."
            )
        )
    user = link.user
    if not user.is_active or _is_platform_admin(user):
        raise PermissionDenied(
            gettext("Für dieses Konto ist die Anmeldung über eine andere Instanz gesperrt.")
        )
    if _uses_mfa(user) and "mfa" not in (data.get("amr") or []):
        raise PermissionDenied(
            gettext(
                "Dieses Konto nutzt hier die Zwei-Faktor-Anmeldung. Bitte auf der "
                "anderen Instanz ebenfalls die Zwei-Faktor-Anmeldung einrichten."
            )
        )
    link.last_used_at = timezone.now()
    link.email = str(data.get("email") or link.email)[:254]
    link.save(update_fields=["last_used_at", "email"])
    return user


# --- Übersicht für Mein Konto ---


def account_data(user) -> dict:
    links = LoginLink.objects.filter(user=user).select_related("peer").order_by("peer__base_url")
    accounts = RemoteAccount.objects.filter(user=user).select_related("peer")
    peers = coupled_peers() if login_enabled() else Peer.objects.none()
    linked = {link.peer_id for link in links}
    return {
        "login_enabled": login_enabled(),
        "links": [
            {
                "id": link.id,
                "base_url": link.peer.base_url,
                "email": link.email,
                "created_at": link.created_at,
                "last_used_at": link.last_used_at,
            }
            for link in links
        ],
        "linkable": [
            {"instance_id": str(p.instance_id), "base_url": p.base_url}
            for p in peers
            if p.id not in linked
        ],
        "accounts": [
            {
                "id": a.id,
                "base_url": a.peer.base_url,
                "url": switch_url(a.peer),
                "last_used_at": a.last_used_at,
            }
            for a in accounts
            if a.peer.couplings.filter(state__in=OPEN).exists()
        ],
    }


def switch_url(peer: Peer) -> str:
    """Heimat-Instanz: Wechsel zur anderen Instanz, dort gleich über diese angemeldet."""
    from urllib.parse import urlencode

    query = urlencode({"idp": identity.identity().instance_id})
    return f"{peer.base_url.rstrip('/')}/verbund/start?{query}"


def login_choices() -> list[dict]:
    """Öffentlich auf der Anmeldeseite: gekoppelte Instanzen (nur Adressen)."""
    if not login_enabled():
        return []
    return [{"instance_id": str(p.instance_id), "base_url": p.base_url} for p in coupled_peers()]


# --- Z: Schritt-hoch für Konten mit Rollen, Abschluss der Anmeldung ---


def needs_local_factor(user) -> bool:
    """Konten mit Verwaltungsrechten hier geben die eigene 2FA ein.

    Dieselbe Prüfung wie bei der Passwort-Pflicht: Rollen der Einheit, Plattform und
    auch Rollen nur in einer Untereinheit (Gesamtaudit 30.10.a, BSEC-V01).
    """
    from portal.services import has_admin_access

    return has_admin_access(user)


def begin_stepup(request, user, peer: Peer, next_path: str) -> None:
    if not _uses_mfa(user):
        raise PermissionDenied(
            gettext(
                "Für Konten mit Vorstands-, Kassen- oder Prüferrollen braucht die "
                "Anmeldung über eine andere Instanz hier eine eigene "
                "Zwei-Faktor-Anmeldung. Bitte einmal direkt mit Passwort anmelden und "
                "unter Mein Konto die Zwei-Faktor-Anmeldung einrichten."
            )
        )
    request.session[STEPUP_KEY] = {
        "user": user.pk,
        "peer": str(peer.instance_id),
        "next": next_path,
        "until": int(time.time()) + STEPUP_SECONDS,
    }


def finish_stepup(request, code: str):
    """Zweiter Schritt: eigener Code dieser Instanz. Liefert (Konto, Instanz, Ziel)."""
    from django.contrib.auth import get_user_model

    pending = request.session.pop(STEPUP_KEY, None)
    if not pending or pending.get("until", 0) < time.time():
        raise ValidationError(gettext("Die Anmeldung ist abgelaufen. Bitte erneut beginnen."))
    user = get_user_model().objects.filter(pk=pending["user"], is_active=True).first()
    peer = coupled_peers().filter(instance_id=pending["peer"]).first()
    # Zustand jetzt erneut prüfen, nicht nur beim ersten Schritt: In der Zwischenzeit können
    # Verbundanmeldung, Kopplung oder Verknüpfung beendet worden sein (AT-V02).
    if (
        user is None
        or peer is None
        or not login_enabled()
        or not LoginLink.objects.filter(peer=peer, user=user).exists()
        or _is_platform_admin(user)
    ):
        raise PermissionDenied(gettext("Die Anmeldung ist nicht mehr möglich."))
    if not check_second_factor(user, code):
        raise PermissionDenied(
            gettext("Der Code stimmt nicht. Bitte die Anmeldung erneut beginnen.")
        )
    return user, peer, pending.get("next") or "/"


def after_login(request, response, user, peer: Peer, stepped_up: bool) -> None:
    """Anmeldeweg vermerken, Sitzung kürzer, Hinweis-Mail bei neuem Browser."""
    record(request, user, "peering", instance=str(peer.instance_id))
    if stepped_up:
        record(request, user, "mfa", type="totp")
    request.session.set_expiry(SSO_SESSION_SECONDS)
    known = []
    try:
        raw = request.get_signed_cookie(SEEN_COOKIE, default="", salt="verbund")
        known = [int(x) for x in raw.split(",") if x]
    except (ValueError, TypeError):
        known = []
    if user.pk not in known:
        _notify_new_browser(user, peer)
        known = ([user.pk] + known)[:10]
    from django.conf import settings

    response.set_signed_cookie(
        SEEN_COOKIE,
        ",".join(str(x) for x in known),
        salt="verbund",
        max_age=365 * 24 * 60 * 60,
        secure=not settings.DEBUG,
        httponly=True,
        samesite="Lax",
    )


def _notify_new_browser(user, peer: Peer) -> None:
    from django.conf import settings
    from django.utils import timezone as tz

    from outbox.mail import send

    if not user.email:
        return
    when = tz.localtime()
    send(
        [user.email],
        "Anmeldung über eine andere Instanz",
        f"Hallo {user.get_full_name() or user.email},\n\n"
        f"am {when:%d.%m.%Y um %H:%M} Uhr hat sich jemand mit deinem Zugang von "
        f"{peer.base_url} bei {settings.FRONTEND_URL} angemeldet, aus einem Browser, der "
        "hier noch nicht bekannt war.\n\n"
        "Warst du das, ist nichts zu tun. Sonst bitte sofort unter Mein Konto › Anmeldung "
        "über andere Instanzen die Verknüpfung lösen und dein Passwort auf beiden Instanzen "
        "ändern.\n",
        kind="sicherheit",
        fail_silently=True,
    )
