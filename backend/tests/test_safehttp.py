"""Härtung H4 (V8): einmal auflösen, prüfen, genau diese Adresse verbinden."""

import pytest

from core import safehttp


def _resolver(*answers):
    calls = iter(answers)

    def getaddrinfo(*args, **kwargs):
        return [(None, None, None, None, (next(calls), 443))]

    return getaddrinfo


def test_interne_adresse_abgelehnt(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", _resolver("127.0.0.1"))
    with pytest.raises(safehttp.BlockedAddress):
        safehttp.request("GET", "https://partner.example/")


def test_verbindet_genau_die_gepruefte_adresse(monkeypatch):
    # Zweite Auflösung würde intern antworten (DNS-Rebinding): darf nie stattfinden
    monkeypatch.setattr("socket.getaddrinfo", _resolver("93.184.216.34", "127.0.0.1"))
    seen = []

    def create_connection(address, timeout=None, *args, **kwargs):
        seen.append(address)
        raise OSError("Test: keine Verbindung")

    monkeypatch.setattr("socket.create_connection", create_connection)
    with pytest.raises(safehttp.SafeHTTPError, match="nicht erreichbar"):
        safehttp.request("POST", "https://partner.example/api/", body=b"x")
    assert seen == [("93.184.216.34", 443)]


def test_nur_https(monkeypatch):
    with pytest.raises(safehttp.SafeHTTPError, match="https"):
        safehttp.request("GET", "http://partner.example/")
    with pytest.raises(safehttp.SafeHTTPError):
        safehttp.request("GET", "https://nutzer:pw@partner.example/")
