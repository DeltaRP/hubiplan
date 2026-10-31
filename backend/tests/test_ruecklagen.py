"""Finanzamt-Prüfung C4: Rücklagen nach § 62 AO (erfundene Daten)."""
# ruff: noqa: F811  (Fixtures als Parameter)

import io
import zipfile

import pytest

from .test_m9_billing import JSON, base, c, club, setup, zug  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def fin(club):
    return f"/api/orgs/{club.pk}/finance"


@pytest.fixture
def an(c, fin, setup):
    resp = c.patch(f"{fin}/settings/", {"reserves_enabled": True}, content_type=JSON)
    assert resp.json()["reserves_enabled"]
    resp = c.post(
        f"{fin}/bookings/",
        {
            "date": "2025-02-01",
            "kind": "income",
            "amount": "5000",
            "account": setup["bank"],
            "category": setup["cat"],
            "text": "Beiträge",
        },
        content_type=JSON,
    )
    assert resp.status_code == 201, resp.json()


def neu(c, fin, **data):
    body = {"name": "Schützenfest 2027", "kind": "purpose", "purpose": "Festzelt", **data}
    return c.post(f"{fin}/reserves/", body, content_type=JSON)


def bewegen(c, fin, reserve, direction, amount, date="2025-12-31", note=""):
    return c.post(
        f"{fin}/reserves/{reserve}/movements/",
        {"direction": direction, "amount": amount, "date": date, "note": note},
        content_type=JSON,
    )


def test_ausgeschaltet_nicht_erreichbar(c, fin, setup):
    assert c.get(f"{fin}/reserves/").status_code == 404


def test_zweck_ist_pflicht_fuer_projektruecklage(c, fin, an):
    resp = neu(c, fin, purpose="")
    assert resp.status_code == 400
    assert "purpose" in resp.json()
    assert neu(c, fin, kind="free", purpose="").status_code == 201


def test_zufuehren_aufloesen_und_bestand(c, fin, an):
    r = neu(c, fin).json()["id"]
    assert bewegen(c, fin, r, "add", "2000", note="Beschluss Vorstand").status_code == 201
    assert bewegen(c, fin, r, "release", "500", date="2026-06-01").status_code == 201
    data = c.get(f"{fin}/reserves/").json()
    item = data["reserves"][0]
    assert item["balance"] == "1500.00"
    assert data["total"] == "1500.00"
    assert data["funds"] == "5000.00"
    assert data["free"] == "3500.00"
    assert [m["direction"] for m in item["movements"]] == ["release", "add"]
    # Nie unter null
    resp = bewegen(c, fin, r, "release", "2000", date="2026-07-01")
    assert resp.status_code == 400
    assert "unter null" in str(resp.json())
    # Zuführung löschen, wenn danach aufgelöst wurde: fiele unter null
    add = next(m for m in item["movements"] if m["direction"] == "add")
    resp = c.delete(f"{fin}/reserves/{r}/movements/{add['id']}/")
    assert resp.status_code == 400
    # Rücklage mit Bewegungen nicht löschbar
    assert c.delete(f"{fin}/reserves/{r}/").status_code == 400


def test_abgeschlossenes_jahr_gesperrt_und_export(c, fin, an):
    r = neu(c, fin).json()["id"]
    assert bewegen(c, fin, r, "add", "1000").status_code == 201
    assert c.post(f"{fin}/closings/", {"year": 2025}, content_type=JSON).status_code == 201
    resp = bewegen(c, fin, r, "add", "100", date="2025-12-30")
    assert resp.status_code == 400
    assert "abgeschlossen" in str(resp.json())
    item = c.get(f"{fin}/reserves/").json()["reserves"][0]
    assert item["movements"][0]["open"] is False
    resp = c.delete(f"{fin}/reserves/{r}/movements/{item['movements'][0]['id']}/")
    assert resp.status_code == 400

    resp = c.get(f"{fin}/export/?jahr=2025")
    zf = zipfile.ZipFile(io.BytesIO(b"".join(resp.streaming_content)))
    rows = zf.read("ruecklagen.csv").decode("utf-8-sig").splitlines()
    assert any("Zuführung" in row and "1000,00" in row for row in rows)
    assert any("Stand am Ende" in row and "1000,00" in row for row in rows)
