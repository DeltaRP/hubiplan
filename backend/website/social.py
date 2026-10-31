"""Beiträge aus Instagram und Facebook abholen (serverseitig, eigene Meta-App je Einheit).

Ablauf:
1. Die Einheit trägt App-ID und App-Geheimnis ihrer Meta-App ein.
2. „Verbinden“ schickt die Person zu Meta; Meta leitet mit einem Code zurück
   (``callback``). HUBIplan tauscht ihn gegen einen langlebigen Zugang.
3. Alle 30 Minuten holt ``sync_feed`` die neuesten Beiträge, lädt die Bilder von
   Meta herunter und schreibt sie neu (ohne Metadaten). Was bei Meta gelöscht ist,
   verschwindet auch hier.
4. Täglich verlängert ``maintain_feed`` den Instagram-Zugang (60 Tage) und prüft
   den Facebook-Seiten-Zugang.

Besucher der Webseite haben nie Kontakt zu Meta. Alle Aufrufe an Meta laufen über
``_request`` und ``_download`` (in Tests ersetzt).
"""

from __future__ import annotations

import datetime
import hashlib
import ipaddress
import json
import logging
import re
import secrets
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from accounts.mfa import decrypt, encrypt

from .social_models import SocialFeed, SocialPost, SocialPostImage

log = logging.getLogger(__name__)

TIMEOUT = 20
MAX_JSON = 2 * 1024 * 1024
MAX_IMAGE = 15 * 1024 * 1024
MAX_POSTS_LIMIT = 50
MAX_IMAGES_PER_POST = 10
OAUTH_VALID = datetime.timedelta(minutes=15)
REFRESH_EVERY = datetime.timedelta(days=7)
# Bilder nur von den Auslieferungsservern von Meta
CDN_SUFFIXES = (".cdninstagram.com", ".fbcdn.net")
IG_SCOPE = "instagram_business_basic"
FB_SCOPE = "pages_show_list,pages_read_engagement"
# Instagram über die Facebook-Anmeldung (Instagram API with Facebook Login)
IG_FB_SCOPE = "instagram_basic,pages_show_list,pages_read_engagement"
ASSIGN_ATTEMPTS = 4
ASSIGN_DELAY = 2.0  # Sekunden
TOKEN_INVALID = 190  # Fehlercode von Meta: Zugang ungültig oder abgelaufen


class MetaError(Exception):
    """Meta nicht erreichbar oder Antwort mit Fehler."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


# --- HTTP (in Tests ersetzt) ---


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _request(method: str, url: str, params: dict) -> dict:
    """Aufruf der Graph-Schnittstelle; liefert das JSON oder wirft MetaError."""
    data = None
    if method == "GET":
        url = f"{url}?{urllib.parse.urlencode(params)}"
    else:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method)  # noqa: S310
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            body = resp.read(MAX_JSON + 1)
    except urllib.error.HTTPError as exc:
        body = exc.read(MAX_JSON + 1)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise MetaError(f"Meta nicht erreichbar ({exc.__class__.__name__}).") from exc
    if len(body) > MAX_JSON:
        raise MetaError("Antwort von Meta ist zu groß.")
    try:
        payload = json.loads(body or b"{}")
    except ValueError as exc:
        raise MetaError("Antwort von Meta ist kein JSON.") from exc
    _raise_for_error(payload)
    return payload


def _raise_for_error(payload: dict) -> None:
    err = payload.get("error") if isinstance(payload, dict) else None
    if err:
        if isinstance(err, dict):
            raise MetaError(str(err.get("message") or "Fehler von Meta")[:400], err.get("code"))
        raise MetaError(str(payload.get("error_message") or err)[:400], payload.get("code"))


def cdn_allowed(url: str) -> bool:
    parts = urllib.parse.urlsplit(url or "")
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host.endswith(s) for s in CDN_SUFFIXES)


def _download(url: str) -> bytes:
    """Bild von Meta holen: nur https, nur Meta-Server, keine Weiterleitung, Größengrenze."""
    if not cdn_allowed(url):
        raise MetaError("Bildadresse gehört nicht zu Meta.")
    host = urllib.parse.urlsplit(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise MetaError("Bildserver nicht auflösbar.") from exc
    if any(not ipaddress.ip_address(i[4][0]).is_global for i in infos):
        raise MetaError("Bildserver zeigt auf eine interne Adresse.")
    req = urllib.request.Request(url)  # noqa: S310
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                raise MetaError(f"Bild nicht abrufbar (HTTP {resp.status}).")
            data = resp.read(MAX_IMAGE + 1)
    except urllib.error.HTTPError as exc:
        raise MetaError(f"Bild nicht abrufbar (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise MetaError("Bild nicht abrufbar.") from exc
    if len(data) > MAX_IMAGE:
        raise MetaError("Bild ist zu groß.")
    return data


# --- Adressen ---


def graph_version() -> str:
    return settings.META_GRAPH_VERSION


def ig_graph(path: str) -> str:
    return f"https://graph.instagram.com/{graph_version()}/{path.lstrip('/')}"


def fb_graph(path: str) -> str:
    return f"https://graph.facebook.com/{graph_version()}/{path.lstrip('/')}"


def redirect_uri() -> str:
    """Diese Adresse trägt die Einheit in ihrer Meta-App als Weiterleitung ein."""
    base = (settings.SOCIAL_CALLBACK_BASE or settings.FRONTEND_URL).rstrip("/")
    return f"{base}/api/website/social/callback/"


def frontend_return(ok: bool, message: str = "") -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    query = {"verbunden": "1"} if ok else {"fehler": message[:900] or "unbekannt"}
    # Nicht /webseite/…: Diesen Pfad gibt Caddy beim Neuladen an die Vereinswebseite weiter.
    return f"{base}/social-rueckkehr?{urllib.parse.urlencode(query)}"


# --- Geheimnisse ---


def set_secret(feed: SocialFeed, value: str) -> None:
    feed.app_secret = encrypt(value) if value else ""


def app_secret(feed: SocialFeed) -> str:
    return decrypt(feed.app_secret) if feed.app_secret else ""


def token(feed: SocialFeed) -> str:
    return decrypt(feed.access_token) if feed.access_token else ""


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


# --- Verbinden ---


def start_connect(feed: SocialFeed, user) -> str:
    """Adresse bei Meta, zu der die Person zum Zustimmen geschickt wird."""
    if not feed.app_id or not feed.app_secret:
        raise MetaError("Bitte zuerst App-ID und App-Geheimnis eintragen.")
    state = secrets.token_urlsafe(32)
    feed.oauth_state = _state_hash(state)
    feed.oauth_started_at = timezone.now()
    feed.oauth_user = user
    feed.save(update_fields=["oauth_state", "oauth_started_at", "oauth_user"])
    params = {"client_id": feed.app_id, "redirect_uri": redirect_uri(), "state": state}
    if instagram_login(feed):
        params.update(response_type="code", scope=IG_SCOPE)
        return f"https://www.instagram.com/oauth/authorize?{urllib.parse.urlencode(params)}"
    params["response_type"] = "code"
    if feed.config_id:
        # Facebook Login for Business: Berechtigungen stehen in der Konfiguration
        params["config_id"] = feed.config_id
    else:
        params["scope"] = IG_FB_SCOPE if feed.kind == SocialFeed.Kind.INSTAGRAM else FB_SCOPE
    return (
        f"https://www.facebook.com/{graph_version()}/dialog/oauth?{urllib.parse.urlencode(params)}"
    )


def instagram_login(feed: SocialFeed) -> bool:
    """Alter Weg über instagram.com (nur ältere Meta-Apps)."""
    return feed.kind == SocialFeed.Kind.INSTAGRAM and not feed.via_facebook


def feed_for_state(state: str, user) -> SocialFeed | None:
    if not state:
        return None
    feed = SocialFeed.objects.filter(oauth_state=_state_hash(state)).first()
    if feed is None or feed.oauth_user_id != getattr(user, "pk", None):
        return None
    if not feed.oauth_started_at or timezone.now() - feed.oauth_started_at > OAUTH_VALID:
        return None
    return feed


@transaction.atomic
def finish_connect(feed: SocialFeed, code: str) -> None:
    """Code von Meta gegen einen langlebigen Zugang tauschen."""
    feed.oauth_state = ""
    feed.save(update_fields=["oauth_state"])
    code = (code or "").split("#")[0].strip()
    if not code:
        raise MetaError("Meta hat keinen Code geliefert.")
    if instagram_login(feed):
        _finish_instagram(feed, code)
    else:
        _finish_facebook(feed, code)


def _finish_instagram(feed: SocialFeed, code: str) -> None:
    short = _request(
        "POST",
        "https://api.instagram.com/oauth/access_token",
        {
            "client_id": feed.app_id,
            "client_secret": app_secret(feed),
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri(),
            "code": code,
        },
    )
    if isinstance(short.get("data"), list) and short["data"]:
        short = short["data"][0]
    long = _request(
        "GET",
        "https://graph.instagram.com/access_token",
        {
            "grant_type": "ig_exchange_token",
            "client_secret": app_secret(feed),
            "access_token": short.get("access_token", ""),
        },
    )
    _store_token(feed, long)
    me = _request(
        "GET", ig_graph("me"), {"fields": "user_id,username", "access_token": token(feed)}
    )
    feed.account_id = str(me.get("user_id") or me.get("id") or "")[:40]
    feed.account_name = str(me.get("username") or "")[:200]
    _connected(feed)


def _finish_facebook(feed: SocialFeed, code: str) -> None:
    short = _request(
        "GET",
        fb_graph("oauth/access_token"),
        {
            "client_id": feed.app_id,
            "client_secret": app_secret(feed),
            "redirect_uri": redirect_uri(),
            "code": code,
        },
    )
    user_token = short.get("access_token", "")
    # Kurzer Nutzer-Zugang → langer (Seiten-Zugänge laufen dann nie ab). Ein Systemnutzer-
    # Zugang aus einer Konfiguration („Unified Login“) läuft nie ab; Meta lehnt den Tausch
    # dafür ggf. ab, dann bleibt er, wie er ist.
    try:
        long = _request(
            "GET",
            fb_graph("oauth/access_token"),
            {
                "grant_type": "fb_exchange_token",
                "client_id": feed.app_id,
                "client_secret": app_secret(feed),
                "fb_exchange_token": user_token,
            },
        )
    except MetaError:
        if not feed.config_id:
            raise
        long = {}
    user_token = long.get("access_token") or user_token
    diag: list[str] = []
    if feed.kind == SocialFeed.Kind.INSTAGRAM and feed.config_id:
        # Unified Login: Zugang aus der Konfiguration, die Konten sind ihm zugewiesen
        accounts = _assigned_instagram_accounts(feed, user_token, diag)
        if accounts:
            _choose_or_use(feed, accounts)
            return
    instagram = feed.kind == SocialFeed.Kind.INSTAGRAM
    fields = "id,name,access_token" + (
        ",instagram_business_account{id,username}" if instagram else ""
    )
    try:
        pages = _request(
            "GET", fb_graph("me/accounts"), {"fields": fields, "access_token": user_token}
        ).get("data", [])
    except MetaError as exc:
        if not diag:
            raise
        diag.append(f"Seiten: Fehler {_short(exc)}")
        pages = []
    else:
        diag.append(f"Seiten: {len(pages)}")
    pages = [
        {**p, "access_token": p.get("access_token") or user_token} for p in pages if p.get("id")
    ]
    if instagram:
        # Auswahl = Instagram-Profikonten, die an einer der Seiten hängen
        pages = [
            {
                "id": str(p["instagram_business_account"]["id"]),
                "name": f"{p['instagram_business_account'].get('username') or 'Instagram'}",
                "page": p.get("name", ""),
                "access_token": p["access_token"],
            }
            for p in pages
            if (p.get("instagram_business_account") or {}).get("id")
        ]
        if not pages:
            raise MetaError(
                "Kein Instagram-Profikonto gefunden. Das Konto muss ein Business- oder "
                "Creator-Konto sein und bei der Anmeldung freigegeben werden"
                + (
                    " (in der Konfiguration: Assets „Instagram-Konten“)"
                    if feed.config_id
                    else " bzw. mit eurer Facebook-Seite verknüpft sein"
                )
                + "."
                + _token_hint(feed, user_token, diag)
            )
    elif not pages:
        raise MetaError("Mit diesem Konto ist keine Facebook-Seite verbunden.")
    _choose_or_use(feed, pages)


def _debug_token(feed: SocialFeed, value: str) -> dict:
    return _request(
        "GET",
        fb_graph("debug_token"),
        {"input_token": value, "access_token": f"{feed.app_id}|{app_secret(feed)}"},
    ).get("data", {})


def _short(exc: Exception) -> str:
    return str(exc)[:60]


def _assigned_instagram_accounts(feed: SocialFeed, value: str, diag: list[str]) -> list[dict]:
    """Instagram-Konten, die der Zugang lesen darf.

    Nacheinander: ``me/assigned_instagram_accounts`` (Systemnutzer), die bei der Anmeldung
    freigegebenen Konten aus ``debug_token`` (``granular_scopes`` › ``target_ids``) und die
    Konten der Business-Portfolios (``me/businesses`` › ``owned_instagram_accounts``).
    Was Meta jeweils liefert, landet kurz in ``diag`` (nur Anzahlen, IDs, Fehlertexte).
    """
    found: dict[str, str] = {}

    def add(items, key="username"):
        for a in items or []:
            if isinstance(a, dict) and a.get("id"):
                found.setdefault(str(a["id"]), a.get(key) or "")

    # Meta weist das Konto dem Systemnutzer erst kurz nach der Anmeldung zu: kurz nachfragen
    for attempt in range(ASSIGN_ATTEMPTS):
        if attempt:
            time.sleep(ASSIGN_DELAY)
        try:
            data = _request(
                "GET",
                fb_graph("me/assigned_instagram_accounts"),
                {"fields": "id,username", "access_token": value},
            ).get("data", [])
        except MetaError as exc:
            diag.append(f"zugewiesen: Fehler {_short(exc)}")
            break
        add(data)
        if found:
            break
    else:
        diag.append(f"zugewiesen: 0 ({ASSIGN_ATTEMPTS}× gefragt)")
    if not found:
        try:
            info = _debug_token(feed, value)
        except MetaError as exc:
            diag.append(f"Freigabe: Fehler {_short(exc)}")
            info = {}
        granted = []
        for scope in info.get("granular_scopes") or []:
            name = str(scope.get("scope", ""))
            targets = [str(t) for t in scope.get("target_ids") or []]
            granted.append(f"{name}={'/'.join(targets) or 'alle'}")
            if name.startswith("instagram_"):
                for target in targets:
                    found.setdefault(target, "")
        diag.append("Freigabe: " + (", ".join(granted) or "keine Angaben"))
    if not found:
        try:
            businesses = _request(
                "GET", fb_graph("me/businesses"), {"fields": "id", "access_token": value}
            ).get("data", [])
            diag.append(f"Portfolios: {len(businesses)}")
        except MetaError as exc:
            diag.append(f"Portfolios: Fehler {_short(exc)}")
            businesses = []
        for business in businesses[:5]:
            for edge in ("owned_instagram_accounts", "instagram_accounts"):
                try:
                    data = _request(
                        "GET",
                        fb_graph(f"{business['id']}/{edge}"),
                        {"fields": "id,username", "access_token": value},
                    ).get("data", [])
                    add(data)
                    diag.append(f"{edge}: {len(data)}")
                except MetaError as exc:
                    diag.append(f"{edge}: Fehler {_short(exc)}")
    accounts = []
    for ig_id, name in list(found.items())[:20]:
        if not name:
            try:
                name = _request(
                    "GET", fb_graph(ig_id), {"fields": "username", "access_token": value}
                ).get("username", "")
            except MetaError as exc:
                diag.append(f"{ig_id}: Fehler {_short(exc)}")
                name = ""
        accounts.append({"id": ig_id, "name": name or "Instagram", "access_token": value})
    if accounts:
        log.info("Instagram-Konten gefunden: %s", "; ".join(diag))
    return accounts


def _token_hint(feed: SocialFeed, value: str, diag: list[str] | None = None) -> str:
    """Hinweis für die Fehlersuche: Art und Rechte des Zugangs, Antworten von Meta.

    Enthält nie den Zugang selbst.
    """
    try:
        info = _debug_token(feed, value)
    except MetaError:
        info = {}
    kind = info.get("type") or "?"
    scopes = ", ".join(sorted(info.get("scopes") or [])) or "keine"
    extra = f"; Meta: {'; '.join(diag)}" if diag else ""
    text = f" (Meta-Zugang: Art {kind}, Rechte: {scopes}{extra})"
    log.warning("Instagram-Konto nicht gefunden für Kanal %s:%s", feed.pk, text)
    return text[:600]


def _choose_or_use(feed: SocialFeed, pages: list[dict]) -> None:
    if len(pages) == 1:
        _use_page(feed, pages[0])
        return
    feed.pending_pages = encrypt(json.dumps(pages))
    feed.status = SocialFeed.Status.CHOOSE
    feed.save()


def pending_pages(feed: SocialFeed) -> list[dict]:
    if not feed.pending_pages:
        return []
    return [
        {"id": p["id"], "name": p.get("name", "") + (f" ({p['page']})" if p.get("page") else "")}
        for p in json.loads(decrypt(feed.pending_pages))
    ]


@transaction.atomic
def choose_page(feed: SocialFeed, page_id: str) -> None:
    pages = json.loads(decrypt(feed.pending_pages)) if feed.pending_pages else []
    page = next((p for p in pages if str(p.get("id")) == str(page_id)), None)
    if page is None:
        raise MetaError("Diese Seite steht nicht zur Auswahl.")
    _use_page(feed, page)


def _use_page(feed: SocialFeed, page: dict) -> None:
    feed.access_token = encrypt(page["access_token"])
    feed.token_expires_at = None  # Seiten-Zugänge laufen nicht zeitlich ab
    feed.token_refreshed_at = timezone.now()
    feed.pending_pages = ""
    feed.account_id = str(page["id"])[:40]
    feed.account_name = str(page.get("name") or "")[:200]
    _connected(feed)


def _store_token(feed: SocialFeed, data: dict) -> None:
    value = data.get("access_token")
    if not value:
        raise MetaError("Meta hat keinen Zugang geliefert.")
    feed.access_token = encrypt(value)
    expires = int(data.get("expires_in") or 0)
    now = timezone.now()
    feed.token_expires_at = now + datetime.timedelta(seconds=expires) if expires else None
    feed.token_refreshed_at = now


def _connected(feed: SocialFeed) -> None:
    feed.status = SocialFeed.Status.OK
    feed.last_error = ""
    feed.warned_at = None
    feed.connected_at = timezone.now()
    feed.save()


def disconnect(feed: SocialFeed) -> None:
    """Zugang und alle abgerufenen Beiträge mit Bildern löschen (Meta-Bedingungen 3.d)."""
    for post in feed.posts.all():
        delete_post(post)
    feed.access_token = ""
    feed.pending_pages = ""
    feed.token_expires_at = None
    feed.token_refreshed_at = None
    feed.account_id = ""
    feed.account_name = ""
    feed.status = SocialFeed.Status.NEW
    feed.last_error = ""
    feed.last_sync_at = None
    feed.save()


def delete_post(post: SocialPost) -> None:
    for image in post.images.all():
        for f in (image.file, image.small):
            if f:
                f.delete(save=False)
    post.delete()


def delete_feed(feed: SocialFeed) -> None:
    for post in feed.posts.all():
        delete_post(post)
    feed.delete()


# --- Zugang pflegen ---


def maintain_feed(feed: SocialFeed) -> None:
    """Täglich: Instagram-Login-Zugang verlängern, sonst Zugang bei Meta prüfen."""
    if not feed.access_token or feed.status not in (SocialFeed.Status.OK, SocialFeed.Status.ERROR):
        return
    now = timezone.now()
    try:
        if instagram_login(feed):
            if feed.token_expires_at and feed.token_expires_at <= now:
                _expired(feed, "Der Instagram-Zugang ist abgelaufen.")
                return
            if not feed.token_refreshed_at or now - feed.token_refreshed_at >= REFRESH_EVERY:
                data = _request(
                    "GET",
                    "https://graph.instagram.com/refresh_access_token",
                    {"grant_type": "ig_refresh_token", "access_token": token(feed)},
                )
                _store_token(feed, data)
                feed.save()
        else:
            data = _request(
                "GET",
                fb_graph("debug_token"),
                {
                    "input_token": token(feed),
                    "access_token": f"{feed.app_id}|{app_secret(feed)}",
                },
            ).get("data", {})
            if not data.get("is_valid"):
                _expired(feed, "Der Zugang bei Meta gilt nicht mehr.")
    except MetaError as exc:
        _failed(feed, exc)


def _expired(feed: SocialFeed, message: str) -> None:
    feed.status = SocialFeed.Status.EXPIRED
    feed.last_error = message
    feed.save(update_fields=["status", "last_error"])
    _warn(feed)


def _failed(feed: SocialFeed, exc: MetaError) -> None:
    if exc.code == TOKEN_INVALID:
        _expired(feed, f"Meta lehnt den Zugang ab: {exc}")
        return
    feed.status = SocialFeed.Status.ERROR
    feed.last_error = str(exc)[:500]
    feed.save(update_fields=["status", "last_error"])
    # Erst nach einem Tag Störung Bescheid geben (einzelne Aussetzer sind normal)
    if feed.last_sync_at and timezone.now() - feed.last_sync_at > datetime.timedelta(days=1):
        _warn(feed)


def _warn(feed: SocialFeed) -> None:
    """Einmal je Störung eine Mail an die Person, die den Kanal verbunden hat."""
    if feed.warned_at or not feed.oauth_user or not feed.oauth_user.email:
        return
    from outbox.mail import send

    org = feed.organization
    send(
        [feed.oauth_user.email],
        f"Webseite: {feed.get_kind_display()} neu verbinden",
        (
            f"Hallo,\n\nHUBIplan kann die Beiträge von {feed} für die Webseite von "
            f"{org.name} nicht mehr abrufen:\n\n{feed.last_error}\n\n"
            "Bitte in HUBIplan unter Webseite › Social Media neu verbinden. "
            "Bis dahin zeigt die Webseite die zuletzt abgerufenen Beiträge.\n"
        ),
        organization=org,
        kind="website-social",
        fail_silently=True,
    )
    feed.warned_at = timezone.now()
    feed.save(update_fields=["warned_at"])


# --- Beiträge abrufen ---


def _parse_time(value: str) -> datetime.datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
    raise MetaError(f"Unbekanntes Zeitformat: {value!r}")


HASHTAG_TAIL = re.compile(r"(?:\s*[#@][\w.äöüÄÖÜß]+)+\s*$")


def clean_text(text: str, strip_hashtags: bool) -> str:
    text = (text or "").replace("\r\n", "\n").strip()
    if strip_hashtags:
        lines = text.split("\n")
        while lines and (not lines[-1].strip() or HASHTAG_TAIL.fullmatch(lines[-1])):
            lines.pop()
        text = "\n".join(lines)
        text = HASHTAG_TAIL.sub("", text).rstrip()
    return text[:5000]


def _instagram_items(feed: SocialFeed, limit: int) -> list[dict]:
    fields = (
        "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,"
        "children{id,media_type,media_url,thumbnail_url}"
    )
    url = ig_graph("me/media") if instagram_login(feed) else fb_graph(f"{feed.account_id}/media")
    data = _request(
        "GET", url, {"fields": fields, "limit": limit, "access_token": token(feed)}
    ).get("data", [])
    items = []
    for m in data:
        kind = m.get("media_type")
        media: list[tuple[str, str, bool]] = []
        if kind == "CAROUSEL_ALBUM":
            for c in (m.get("children") or {}).get("data", []):
                video = c.get("media_type") == "VIDEO"
                url = c.get("thumbnail_url") if video else c.get("media_url")
                if url:
                    media.append((str(c.get("id", "")), url, video))
            media_type = SocialPost.MediaType.ALBUM
        elif kind == "VIDEO":
            if m.get("thumbnail_url"):
                media.append((str(m["id"]), m["thumbnail_url"], True))
            media_type = SocialPost.MediaType.VIDEO
        else:
            if m.get("media_url"):
                media.append((str(m["id"]), m["media_url"], False))
            media_type = SocialPost.MediaType.IMAGE
        items.append(
            {
                "id": str(m["id"]),
                "text": m.get("caption") or "",
                "permalink": m.get("permalink") or "",
                "published_at": _parse_time(m.get("timestamp")),
                "media_type": media_type,
                "media": media,
            }
        )
    return items


def _facebook_items(feed: SocialFeed, limit: int) -> list[dict]:
    fields = (
        "id,message,created_time,permalink_url,full_picture,parent_id,"
        "attachments{type,media,target,subattachments.limit(10){type,media,target}}"
    )
    data = _request(
        "GET",
        fb_graph(f"{feed.account_id}/posts"),
        {"fields": fields, "limit": limit, "access_token": token(feed)},
    ).get("data", [])
    items = []
    for p in data:
        if p.get("parent_id"):
            continue  # geteilter Beitrag eines anderen
        attachments = (p.get("attachments") or {}).get("data", [])
        first = attachments[0] if attachments else {}
        if first.get("type") == "share":
            continue  # geteilter Link: Bild und Text gehören Dritten
        media: list[tuple[str, str, bool]] = []
        subs = (first.get("subattachments") or {}).get("data", [])
        for i, a in enumerate(subs or ([first] if first else [])):
            src = ((a.get("media") or {}).get("image") or {}).get("src")
            if src:
                target = str((a.get("target") or {}).get("id") or f"{p['id']}-{i}")
                media.append((target, src, "video" in (a.get("type") or "")))
        if not media and p.get("full_picture"):
            media.append((f"{p['id']}-0", p["full_picture"], False))
        if subs:
            media_type = SocialPost.MediaType.ALBUM
        elif media and media[0][2]:
            media_type = SocialPost.MediaType.VIDEO
        elif media:
            media_type = SocialPost.MediaType.IMAGE
        else:
            media_type = SocialPost.MediaType.TEXT
        if not media and not p.get("message"):
            continue
        items.append(
            {
                "id": str(p["id"]),
                "text": p.get("message") or "",
                "permalink": p.get("permalink_url") or "",
                "published_at": _parse_time(p.get("created_time")),
                "media_type": media_type,
                "media": media,
            }
        )
    return items


def _store_images(post: SocialPost, media: list[tuple[str, str, bool]]) -> None:
    from . import content

    for position, (external_id, url, is_video) in enumerate(media[:MAX_IMAGES_PER_POST]):
        try:
            raw = _download(url)
            upload = ContentFile(raw, name="bild")
            full, ext, width, height, small, ext_small = content.process_image(upload)
        except Exception as exc:  # noqa: BLE001 – ein kaputtes Bild hält den Abruf nicht auf
            log.warning("Bild zu Beitrag %s übersprungen: %s", post.external_id, exc)
            continue
        image = SocialPostImage(
            organization_id=post.organization_id,
            post=post,
            position=position,
            key=SocialPostImage.new_key(),
            external_id=external_id[:80],
            width=width,
            height=height,
            is_video=is_video,
        )
        image.file.save(f"bild.{ext}", ContentFile(full), save=False)
        image.small.save(f"bild-klein.{ext_small}", ContentFile(small), save=False)
        image.save()


def sync_feed(feed: SocialFeed) -> int:
    """Neueste Beiträge holen und abgleichen. Liefert die Zahl neuer Beiträge."""
    if (
        not feed.is_active
        or not feed.access_token
        or feed.status
        not in (
            SocialFeed.Status.OK,
            SocialFeed.Status.ERROR,
        )
    ):
        return 0
    limit = max(1, min(feed.max_posts, MAX_POSTS_LIMIT))
    try:
        if feed.kind == SocialFeed.Kind.INSTAGRAM:
            items = _instagram_items(feed, limit)
        else:
            items = _facebook_items(feed, limit)
    except MetaError as exc:
        _failed(feed, exc)
        return 0
    items.sort(key=lambda i: i["published_at"], reverse=True)
    items = items[:limit]
    existing = {p.external_id: p for p in feed.posts.all()}
    seen = set()
    created = 0
    for item in items:
        seen.add(item["id"])
        text = clean_text(item["text"], feed.strip_hashtags)
        post = existing.get(item["id"])
        if post is None:
            with transaction.atomic():
                post = SocialPost.objects.create(
                    organization_id=feed.organization_id,
                    feed=feed,
                    external_id=item["id"],
                    media_type=item["media_type"],
                    text=text,
                    permalink=item["permalink"][:500],
                    published_at=item["published_at"],
                    state=SocialPost.State.PENDING
                    if feed.mode == SocialFeed.Mode.APPROVAL
                    else SocialPost.State.VISIBLE,
                )
                _store_images(post, item["media"])
            created += 1
            continue
        changed = []
        if post.text != text:
            post.text = text
            changed.append("text")
        if item["permalink"] and post.permalink != item["permalink"][:500]:
            post.permalink = item["permalink"][:500]
            changed.append("permalink")
        if changed:
            post.save(update_fields=changed)
        if item["media"] and not post.images.exists():
            _store_images(post, item["media"])
    # Abgleich: bei Meta gelöscht oder aus den neuesten N gerutscht → auch hier weg.
    # Eine leere Antwort gilt als Aussetzer und löscht nichts.
    if items:
        for external_id, post in existing.items():
            if external_id not in seen:
                delete_post(post)
    feed.status = SocialFeed.Status.OK
    feed.last_error = ""
    feed.warned_at = None
    feed.last_sync_at = timezone.now()
    feed.save(update_fields=["status", "last_error", "warned_at", "last_sync_at"])
    return created


def sync_all() -> int:
    total = 0
    for feed in SocialFeed.objects.filter(is_active=True).exclude(access_token=""):
        try:
            total += sync_feed(feed)
        except Exception:  # noqa: BLE001 – ein Kanal darf die anderen nicht aufhalten
            log.exception("Abruf %s fehlgeschlagen", feed.pk)
    return total


def maintain_all() -> None:
    for feed in SocialFeed.objects.exclude(access_token=""):
        try:
            maintain_feed(feed)
        except Exception:  # noqa: BLE001
            log.exception("Zugangspflege %s fehlgeschlagen", feed.pk)


def text_preview(text: str, length: int = 280) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= length else text[: length - 1].rsplit(" ", 1)[0] + " …"
