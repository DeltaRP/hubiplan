"""Testaufbau mit mehreren simulierten HUBIplan-Instanzen in einer Datenbank.

Jede Instanz hat eigene Schlüssel und Adresse. Anfragen zwischen ihnen gehen
über den Django-Testclient; während eine Instanz eine Anfrage bearbeitet, gelten
ihre Schlüssel und Adresse. Alle Daten sind erfunden.

Eingehende Anfragen laufen wie im Echtbetrieb in der Rolle ``hubiplan_app``, damit die
Zeilensicherheit (RLS) dort wirklich greift.
"""

from __future__ import annotations

import contextlib
import urllib.parse

from django.db import connection
from django.test import Client, override_settings

from peering import identity, transport


class Net:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.instances: dict[str, str] = {}
        self.down: set[str] = set()
        self.calls: list[tuple[str, str]] = []
        self.current: str | None = None

    def add(self, base_url: str) -> str:
        name = urllib.parse.urlsplit(base_url).hostname.replace(".", "_")
        self.instances[base_url] = str(self.tmp_path / name / "instance.json")
        return base_url

    @contextlib.contextmanager
    def on(self, base_url: str):
        previous = self.current
        self.current = base_url
        with override_settings(
            PEERING_KEY_FILE=self.instances[base_url], PEERING_BASE_URL=base_url
        ):
            try:
                yield
            finally:
                self.current = previous

    def target(self, url: str) -> tuple[str, str]:
        for base in self.instances:
            if url.startswith(base + "/"):
                return base, url[len(base) :]
        raise transport.PeerError("unbekannte Adresse")

    def send(self, url, headers, body):
        base, path = self.target(url)
        self.calls.append((self.current or "", path))
        if base in self.down:
            raise transport.PeerError("nicht erreichbar (Test)")
        with self.on(base), app_role():
            resp = Client().post(
                path,
                data=body,
                content_type="application/json",
                headers={k: v for k, v in headers.items() if k != "Content-Type"},
            )
        return resp.status_code, dict(resp.headers), resp.content

    def get(self, url):
        base, path = self.target(url)
        if base in self.down:
            raise transport.PeerError("nicht erreichbar (Test)")
        with self.on(base):
            resp = Client().get(path)
        return resp.status_code, resp.content


@contextlib.contextmanager
def app_role():
    """Anfrage in der eingeschränkten Rolle der Anwendung bearbeiten (RLS aktiv)."""
    from core.rls import APP_ROLE

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        outer = cursor.fetchone()[0]
        cursor.execute(f"SET ROLE {APP_ROLE}")
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            if outer == APP_ROLE:
                cursor.execute(f"SET ROLE {APP_ROLE}")
            else:
                cursor.execute("RESET ROLE")


def install(monkeypatch, tmp_path) -> Net:
    net = Net(tmp_path)
    monkeypatch.setattr(transport, "_send", net.send)
    monkeypatch.setattr(transport, "_get", net.get)
    identity.reset_cache()
    return net


def release(coupling, levels: dict):
    """Freigeben wie ``services.set_packets``; die Gegenseite hat der Stufe schon zugestimmt.

    Seit Härtung H4 nimmt die Empfängerin nur an, was sie bestätigt hat."""
    from peering import services
    from peering.models import Coupling

    other = (
        Coupling.objects.exclude(pk=coupling.pk)
        .exclude(state__in=[Coupling.State.ENDED, Coupling.State.MOVED])
        .get(local_unit__uuid=coupling.remote_uuid, remote_uuid=coupling.local_unit.uuid)
    )
    services.set_accept(other, {**services.accepted(other), **levels}, None)
    return services.set_packets(coupling, levels, None)
