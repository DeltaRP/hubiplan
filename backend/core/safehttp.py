"""HTTP-Anfragen an fremde Server ohne DNS-Rebinding (Härtung H4, V8).

Der Name wird **einmal** aufgelöst, alle Adressen werden geprüft (keine internen), und
verbunden wird genau mit der geprüften Adresse. Zertifikat und SNI gelten weiter für den
Namen. Weiterleitungen folgt ``http.client`` nie.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import urllib.parse
from dataclasses import dataclass


class SafeHTTPError(Exception):
    """Nicht erreichbar, nicht erlaubt oder ungültige Antwort."""


class BlockedAddress(SafeHTTPError):
    pass


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict
    body: bytes


def resolve(host: str, port: int, *, allow_internal: bool = False) -> str:
    """Name auflösen; jede Adresse muss öffentlich sein. Liefert die erste."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise SafeHTTPError(f"{host} ist nicht auflösbar.") from exc
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise SafeHTTPError(f"{host} ist nicht auflösbar.")
    if not allow_internal:
        for address in addresses:
            if not ipaddress.ip_address(address).is_global:
                raise BlockedAddress(f"{host} zeigt auf eine interne Adresse.")
    return addresses[0]


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS zu einer festen Adresse; Zertifikat und SNI für den Namen."""

    def __init__(self, host: str, port: int, address: str, timeout: float):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._address = address

    def connect(self):
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTP(http.client.HTTPConnection):
    """Nur Testaufbau (http erlaubt)."""

    def __init__(self, host: str, port: int, address: str, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._address = address

    def connect(self):
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


def request(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    body: bytes | None = None,
    timeout: float = 15,
    max_body: int = 1024 * 1024,
    allow_internal: bool = False,
    allow_http: bool = False,
) -> Response:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in (("https", "http") if allow_http else ("https",)):
        raise SafeHTTPError("Nur https-Adressen sind erlaubt.")
    if not parts.hostname or parts.username or parts.password:
        raise SafeHTTPError("Ungültige Adresse.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    address = resolve(parts.hostname, port, allow_internal=allow_internal)
    cls = _PinnedHTTPS if parts.scheme == "https" else _PinnedHTTP
    conn = cls(parts.hostname, port, address, timeout)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    try:
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read(max_body + 1)
        return Response(resp.status, dict(resp.getheaders()), data)
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise SafeHTTPError(f"nicht erreichbar ({exc.__class__.__name__})") from exc
    finally:
        conn.close()
