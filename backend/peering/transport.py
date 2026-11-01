"""Anfragen an andere Instanzen: nur HTTPS, verschlüsselt und unterschrieben.

Jede Anfrage ist ein POST mit einem verschlüsselten Paket (``crypto.seal``) als
Inhalt und vier Kopfzeilen (Instanz, Zeit, Einmalwert, Unterschrift). Die
Antwort ist ebenso verschlüsselt und unterschrieben; der Einmalwert der Anfrage
steckt in der Unterschrift der Antwort, damit keine alte Antwort untergeschoben
werden kann.
"""

from __future__ import annotations

import json
import urllib.parse
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext

from . import crypto, identity

TIMEOUT = 15
MAX_BODY = 20 * 1024 * 1024
H_INSTANCE = "X-Hubiplan-Instance"
H_DATE = "X-Hubiplan-Date"
H_NONCE = "X-Hubiplan-Nonce"
H_SIGNATURE = "X-Hubiplan-Signature"
# Zweite Unterschrift mit dem alten Schlüssel während eines Schlüsselwechsels
H_SIGNATURE_PREV = "X-Hubiplan-Signature-2"


class PeerError(Exception):
    """Andere Instanz nicht erreichbar oder Antwort ungültig."""


@dataclass(frozen=True)
class PeerKeys:
    instance_id: str
    base_url: str
    public_key: str
    enc_public_key: str
    # Alter Schlüssel der Gegenstelle in ihrer Übergangszeit (sonst leer)
    previous_public_key: str = ""

    @property
    def accepted(self) -> tuple[str, ...]:
        return tuple(k for k in (self.public_key, self.previous_public_key) if k)


def signed_headers(ident, method: str, path: str, date: str, nonce: str, body: bytes) -> dict:
    """Unterschrift(en) dieser Instanz; im Wechsel zusätzlich mit dem alten Schlüssel."""
    headers = {H_SIGNATURE: crypto.sign_request(ident, method, path, date, nonce, body)}
    previous = crypto.sign_request_previous(ident, method, path, date, nonce, body)
    if previous:
        headers[H_SIGNATURE_PREV] = previous
    return headers


def signatures_of(headers) -> list[str]:
    lower = {k.lower(): v for k, v in dict(headers).items()}
    return [lower.get(H_SIGNATURE.lower(), ""), lower.get(H_SIGNATURE_PREV.lower(), "")]


def normalize_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise PeerError(gettext("Ungültige Adresse."))
    if parts.username or parts.password or parts.query or parts.fragment:
        raise PeerError(gettext("Ungültige Adresse."))
    if parts.scheme != "https" and not settings.PEERING_ALLOW_INSECURE:
        raise PeerError(gettext("Andere Instanzen sind nur über https erreichbar."))
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, "", ""))


def check_host(url: str) -> None:
    """Nur Instanzen aus der Liste erlaubter Instanzen (leer: alle)."""
    if settings.PEERING_ALLOW_INSECURE:
        return
    host = urllib.parse.urlsplit(url).hostname or ""
    from organizations.models import PlatformSettings

    allowed = [h.strip().lower() for h in PlatformSettings.load().peering_allowed_hosts.split()]
    if allowed and host.lower() not in allowed:
        raise PeerError(
            gettext("{host} steht nicht in der Liste erlaubter Instanzen.").format(host=host)
        )


def _http(method: str, url: str, headers: dict, body: bytes | None, limit: int):
    """Einmal auflösen, prüfen, genau diese Adresse verbinden (kein DNS-Rebinding)."""
    from core import safehttp

    check_host(url)
    insecure = settings.PEERING_ALLOW_INSECURE
    try:
        return safehttp.request(
            method,
            url,
            headers=headers,
            body=body,
            timeout=TIMEOUT,
            max_body=limit,
            allow_internal=insecure,
            allow_http=insecure,
        )
    except safehttp.SafeHTTPError as exc:
        raise PeerError(str(exc)) from exc


def _send(url: str, headers: dict, body: bytes) -> tuple[int, dict, bytes]:
    """Eigentlicher HTTP-Aufruf (in Tests ersetzt)."""
    resp = _http("POST", url, headers, body, MAX_BODY)
    return resp.status, resp.headers, resp.body


def _get(url: str) -> tuple[int, bytes]:
    resp = _http("GET", url, {"Accept": "application/json"}, None, 64 * 1024)
    return resp.status, resp.body[: 64 * 1024]


def fetch_info(base_url: str) -> dict:
    """Selbstauskunft einer anderen Instanz holen und prüfen."""
    base_url = normalize_url(base_url)
    status, body = _get(f"{base_url}/api/peering/v1/instance/")
    if status != 200:
        raise PeerError(
            gettext("Selbstauskunft nicht abrufbar (HTTP {status}).").format(status=status)
        )
    try:
        info = json.loads(body)
    except ValueError as exc:
        raise PeerError(gettext("Selbstauskunft ist kein JSON.")) from exc
    if info.get("format") != identity.FORMAT or not info.get("instance_id"):
        raise PeerError(gettext("Dort läuft keine HUBIplan-Instanz."))
    for key in ("public_key", "enc_public_key"):
        if not isinstance(info.get(key), str) or len(identity.unb64(info[key])) != 32:
            raise PeerError(gettext("Selbstauskunft ohne gültigen Schlüssel."))
    info["fingerprint"] = identity.fingerprint(info["public_key"], info["enc_public_key"])
    info["base_url"] = base_url
    return info


def call(
    peer: PeerKeys,
    path: str,
    payload: dict | None,
    *,
    announce: bool = False,
    sealed: dict | None = None,
) -> dict:
    """Verschlüsselte, unterschriebene Anfrage an ``peer``; gibt die Antwort zurück.

    ``announce``: Schlüsselwechsel ankündigen, zweite Unterschrift mit dem alten Schlüssel
    auch nach einem Notfallwechsel. ``sealed``: schon verschlüsselter Inhalt."""
    ident = identity.identity()
    # ``sealed``: beim Einreihen schon für die Empfängerin verschlüsselt (Postausgang)
    envelope = sealed or crypto.seal(
        payload,
        sender=ident.instance_id,
        recipient=peer.instance_id,
        recipient_enc_key=peer.enc_public_key,
    )
    body = json.dumps(envelope).encode()
    date = timezone.now().isoformat()
    nonce = uuid.uuid4().hex
    headers = {
        "Content-Type": "application/json",
        H_INSTANCE: ident.instance_id,
        H_DATE: date,
        H_NONCE: nonce,
        **signed_headers(ident, "POST", path, date, nonce, body),
    }
    if announce:
        old = ident.sign_announcement(crypto.signing_input("POST", path, date, nonce, body))
        if old:
            headers[H_SIGNATURE_PREV] = old
    status, resp_headers, resp_body = _send(f"{peer.base_url}{path}", headers, body)
    if len(resp_body) > MAX_BODY:
        raise PeerError(gettext("Antwort zu groß."))
    lower = {k.lower(): v for k, v in resp_headers.items()}
    resp_date = lower.get(H_DATE.lower(), "")
    ok = crypto.verify_request_any(
        peer.accepted,
        f"RESPONSE {status}",
        path,
        resp_date,
        nonce,
        resp_body,
        signatures_of(resp_headers),
    )
    if not ok:
        raise PeerError(
            gettext("Antwort ohne gültige Unterschrift (HTTP {status}).").format(status=status)
        )
    try:
        data = crypto.open_sealed(json.loads(resp_body), ident)
    except (ValueError, crypto.CryptoError) as exc:
        raise PeerError(gettext("Antwort lässt sich nicht entschlüsseln.")) from exc
    if status >= 400:
        raise RemoteRefused(status, data.get("error") or f"HTTP {status}", data)
    return data


class RemoteRefused(PeerError):
    def __init__(self, status: int, message: str, data: dict):
        super().__init__(message)
        self.status = status
        self.data = data
