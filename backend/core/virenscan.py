"""Virenprüfung hochgeladener Dateien mit dem ClamAV des Servers (Fachfrage 4, 31.10.b).

Ist ``CLAMD_SOCKET`` gesetzt (Unix-Socket des clamd auf dem Rechner, in die Container
eingehängt), läuft jede hochgeladene Datei noch während des Hochladens durch clamd
(INSTREAM). Ein Fund lehnt das Hochladen ab und schickt eine Alarm-Mail. Ist clamd nicht
erreichbar, wird ebenfalls abgelehnt (lieber kein Upload als ein ungeprüfter) und gemeldet.
Dateien über ``CLAMD_MAX_BYTES`` (Grenze StreamMaxLength des clamd) bleiben ungeprüft und
werden protokolliert. Ohne ``CLAMD_SOCKET`` (Testserver, Entwicklung) gibt es keine Prüfung.
"""

from __future__ import annotations

import logging
import socket
import struct

from django.conf import settings
from django.core.cache import cache
from django.core.files.uploadhandler import FileUploadHandler
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)


class VirusFound(APIException):
    status_code = 422
    default_code = "virus_found"
    default_detail = "Die Datei enthält Schadsoftware und wurde abgelehnt."


class ScanUnavailable(APIException):
    status_code = 503
    default_code = "scan_unavailable"
    default_detail = (
        "Die Virenprüfung ist gerade nicht erreichbar. Bitte später noch einmal hochladen."
    )


class ScanError(Exception):
    pass


def enabled() -> bool:
    return bool(getattr(settings, "CLAMD_SOCKET", ""))


def max_bytes() -> int:
    return int(getattr(settings, "CLAMD_MAX_BYTES", 25 * 1024 * 1024))


class Stream:
    """Eine INSTREAM-Prüfung bei clamd (Daten in Stücken senden, am Ende Ergebnis lesen)."""

    def __init__(self):
        self.sent = 0
        self.too_big = False
        self.sock: socket.socket | None = None
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(float(getattr(settings, "CLAMD_TIMEOUT", 60)))
            sock.connect(settings.CLAMD_SOCKET)
            sock.sendall(b"zINSTREAM\0")
            self.sock = sock
        except OSError as exc:
            raise ScanError(f"clamd nicht erreichbar: {exc}") from exc

    def feed(self, data: bytes) -> None:
        if self.too_big or not data:
            return
        if self.sent + len(data) > max_bytes():
            # Über der Grenze des clamd: nicht weiter senden, Datei bleibt ungeprüft
            self.too_big = True
            self.close()
            return
        try:
            self.sock.sendall(struct.pack("!L", len(data)) + data)
        except OSError as exc:
            self.close()
            raise ScanError(f"clamd hat die Verbindung beendet: {exc}") from exc
        self.sent += len(data)

    def result(self) -> str | None:
        """None: sauber (oder zu groß); sonst Name des Funds."""
        if self.too_big:
            return None
        try:
            self.sock.sendall(struct.pack("!L", 0))
            reply = b""
            while not reply.endswith(b"\0"):
                part = self.sock.recv(4096)
                if not part:
                    break
                reply += part
        except OSError as exc:
            raise ScanError(f"clamd antwortet nicht: {exc}") from exc
        finally:
            self.close()
        text = reply.rstrip(b"\0").decode("utf-8", "replace").strip()
        if text.endswith("OK"):
            return None
        if text.endswith("FOUND"):
            return text.removeprefix("stream:").removesuffix("FOUND").strip() or "unbekannt"
        raise ScanError(f"clamd meldet: {text[:200]}")

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


def _alert(subject: str, lines: list[str], key: str) -> None:
    from core.alarm import send_alert

    # Höchstens eine Mail je Art und Stunde (z. B. clamd länger aus)
    if cache.add(f"virenscan-alarm:{key}", 1, 60 * 60):
        send_alert(subject, lines)


def _who(request) -> str:
    user = getattr(request, "user", None) if request is not None else None
    email = getattr(user, "email", "") if user is not None else ""
    path = getattr(request, "path", "") if request is not None else ""
    return f"{email or 'unbekannt'} über {path or '?'}"


def found(name: str, signature: str, request=None) -> None:
    logger.warning("Virenfund beim Hochladen: %s (%s) von %s", name, signature, _who(request))
    from core.alarm import send_alert

    send_alert(
        "Schadsoftware beim Hochladen abgelehnt",
        [f"Datei: {name}", f"Fund: {signature}", f"Von: {_who(request)}"],
    )
    raise VirusFound(f"Die Datei „{name}“ enthält Schadsoftware ({signature}) und wurde abgelehnt.")


def unavailable(exc: Exception, request=None) -> None:
    logger.error("Virenprüfung nicht möglich: %s", exc)
    _alert(
        "Virenprüfung nicht erreichbar",
        [
            f"Fehler: {exc}",
            f"Zuletzt bei: {_who(request)}",
            "Uploads werden abgelehnt, bis clamd wieder antwortet "
            "(ggf. backend und worker neu starten, siehe docs/betrieb.md).",
        ],
        "unavailable",
    )
    raise ScanUnavailable()


def scan_bytes(data: bytes, name: str, request=None) -> None:
    """Inhalt prüfen, der nicht als Upload kommt (z. B. Bild als base64 aus der App)."""
    if not enabled():
        return
    try:
        stream = Stream()
        for start in range(0, len(data), 64 * 1024):
            stream.feed(data[start : start + 64 * 1024])
        signature = stream.result()
    except ScanError as exc:
        unavailable(exc, request)
    if stream.too_big:
        logger.info("Nicht auf Viren geprüft (zu groß): %s, %s Bytes", name, len(data))
    if signature:
        found(name, signature, request)


class ClamavUploadHandler(FileUploadHandler):
    """Erster Upload-Handler: reicht alle Daten weiter und prüft sie nebenbei bei clamd."""

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.stream = None
        self.size = 0
        if enabled():
            try:
                self.stream = Stream()
            except ScanError as exc:
                unavailable(exc, self.request)

    def receive_data_chunk(self, raw_data, start):
        self.size += len(raw_data)
        if self.stream is not None:
            try:
                self.stream.feed(raw_data)
            except ScanError as exc:
                unavailable(exc, self.request)
        return raw_data

    def file_complete(self, file_size):
        stream, self.stream = self.stream, None
        if stream is None:
            return None
        try:
            signature = stream.result()
        except ScanError as exc:
            unavailable(exc, self.request)
        if stream.too_big:
            logger.info(
                "Nicht auf Viren geprüft (über %s Bytes): %s, %s Bytes",
                max_bytes(),
                self.file_name,
                self.size,
            )
        if signature:
            found(self.file_name, signature, self.request)
        return None

    def upload_interrupted(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


def inbound_ok(data: bytes, name: str, source: str) -> bool:
    """Datei aus Mail oder Verbund prüfen (Gesamtaudit 01.11., GA-I01).

    False: Schadsoftware gefunden (Alarm ist raus), die Datei wird nicht übernommen.
    Ist der Scanner nicht erreichbar, geht ``ScanUnavailable`` weiter: Die Nachricht
    wird dann später erneut zugestellt bzw. abgewiesen, nicht ungeprüft gespeichert.
    """
    try:
        scan_bytes(data, f"{name} ({source})")
    except VirusFound:
        return False
    return True
