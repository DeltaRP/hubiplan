"""Lernhilfen: Schalter und ausgeblendete „Warum?“-Erklärungen am eigenen Konto."""

import importlib
import json
from pathlib import Path

import pytest
from django.db import migrations
from django.test import Client

from accounts.learning import DECISION_KEYS
from accounts.models import User

from .conftest import csrf_headers
from .factories import PASSWORD, make_user

pytestmark = pytest.mark.django_db
JSON = "application/json"
URL = "/api/me/learning/"
KEY = "member_type_active"
OTHER = "receipts"


def login(email: str) -> tuple[Client, dict[str, str]]:
    """Angemeldeter Client mit aktiver CSRF-Prüfung, wie im Browser."""
    make_user(email)
    c = Client(enforce_csrf_checks=True)
    c.force_login(User.objects.get(email=email))
    return c, csrf_headers(c)


def test_neue_konten_starten_mit_lernhilfen():
    u = make_user("neu@example.org")
    assert u.learning_aids is True
    assert u.learning_hidden is None


def test_bestehende_konten_bekommen_den_schalter_aus():
    # Die Migration legt das Feld mit AUS an (gilt für alle vorhandenen Konten) und
    # stellt erst danach den Standard für neue Konten auf EIN.
    mig = importlib.import_module("accounts.migrations.0004_lernhilfen").Migration
    add, alter = mig.operations[0], mig.operations[1]
    assert isinstance(add, migrations.AddField) and add.name == "learning_aids"
    assert add.field.default is False
    assert isinstance(alter, migrations.AlterField) and alter.field.default is True


def test_schluessel_wie_im_frontend():
    path = Path(__file__).resolve().parents[1] / "accounts" / "learning_keys.json"
    keys = json.loads(path.read_text())["decisions"]
    assert keys == sorted(keys)
    assert set(keys) == DECISION_KEYS
    assert KEY in DECISION_KEYS and OTHER in DECISION_KEYS


def test_lesen_und_schalten():
    c, h = login("karla@example.org")
    assert c.get(URL).json() == {"learning_aids": True, "learning_hidden": []}
    resp = c.patch(URL, {"learning_aids": False}, content_type=JSON, headers=h)
    assert resp.status_code == 200
    assert resp.json()["learning_aids"] is False
    assert User.objects.get(email="karla@example.org").learning_aids is False


def test_ausblenden_betrifft_genau_einen_schluessel_und_ein_konto():
    c, h = login("karla@example.org")
    other, _ = login("otto@example.org")
    resp = c.post(f"{URL}{KEY}/hide/", headers=h)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "learning_hidden": [KEY]}
    # doppelt ausblenden bleibt ein Eintrag
    assert c.post(f"{URL}{KEY}/hide/", headers=h).json()["learning_hidden"] == [KEY]
    assert c.post(f"{URL}{OTHER}/hide/", headers=h).json()["learning_hidden"] == sorted(
        [KEY, OTHER]
    )
    assert other.get(URL).json()["learning_hidden"] == []

    # Rückgängig holt nur diesen zurück
    assert c.post(f"{URL}{KEY}/show/", headers=h).json()["learning_hidden"] == [OTHER]
    # Der Schalter bleibt dabei unberührt
    assert c.get(URL).json() == {"learning_aids": True, "learning_hidden": [OTHER]}


def test_alle_wieder_zeigen():
    c, h = login("karla@example.org")
    c.post(f"{URL}{KEY}/hide/", headers=h)
    resp = c.patch(URL, {"learning_hidden": []}, content_type=JSON, headers=h)
    assert resp.json()["learning_hidden"] == []
    # einzelne Schlüssel lassen sich nicht über PATCH setzen
    resp = c.patch(URL, {"learning_hidden": [KEY]}, content_type=JSON, headers=h)
    assert resp.status_code == 400


def test_unbekannter_schluessel_404():
    c, h = login("karla@example.org")
    assert c.post(f"{URL}gibt_es_nicht/hide/", headers=h).status_code == 404
    assert c.post(f"{URL}gibt_es_nicht/show/", headers=h).status_code == 404
    # Begriffe und Rechenwege lassen sich nicht ausblenden
    assert c.post(f"{URL}balance/hide/", headers=h).status_code == 404


def test_unbekannte_schluessel_in_der_datenbank_fallen_weg():
    c, _ = login("karla@example.org")
    User.objects.filter(email="karla@example.org").update(learning_hidden=["alt", KEY])
    assert c.get(URL).json()["learning_hidden"] == [KEY]


def test_ohne_csrf_abgelehnt():
    c, _ = login("karla@example.org")
    assert c.post(f"{URL}{KEY}/hide/").status_code == 403
    assert c.post(f"{URL}{KEY}/show/").status_code == 403
    assert c.patch(URL, {"learning_aids": False}, content_type=JSON).status_code == 403
    assert User.objects.get(email="karla@example.org").learning_hidden in (None, [])


def test_ohne_anmeldung_kein_zugriff():
    c = Client()
    assert c.get(URL).status_code in (401, 403)
    assert c.post(f"{URL}{KEY}/hide/").status_code in (401, 403)


def test_anmeldung_mit_passwort_und_lernhilfen():
    make_user("karla@example.org")
    c = Client()
    resp = c.post(
        "/_allauth/browser/v1/auth/login",
        {"email": "karla@example.org", "password": PASSWORD},
        content_type=JSON,
    )
    assert resp.status_code == 200
    assert c.get(URL).json()["learning_aids"] is True


def test_datenschutzhinweise_der_plattform_nennen_die_lernhilfen():
    from organizations.imprint_generator import platform_privacy

    text = platform_privacy()
    assert "Anzeigeeinstellung für die Lernhilfen" in text
    assert "werden nicht ausgewertet" in text
