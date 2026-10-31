"""Beitragsordnung je Einheit: optional, gebaut wie die Satzung (alles erfunden)."""

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from organizations.models import Department
from statutes.models import StatutePublication, StatuteVersion
from website.models import Website

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def private_root(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"
    cache.clear()


def pdf(body=b"%PDF-1.4 erfundene Beitragsordnung"):
    return SimpleUploadedFile("ordnung.pdf", body, content_type="application/pdf")


def upload(client, org, kind=None, department=None, valid_from="2024-01-01", body=None):
    data = {"file": pdf(body) if body else pdf(), "valid_from": valid_from}
    if kind:
        data["kind"] = kind
    if department:
        data["department"] = department.pk
    return client.post(f"/api/orgs/{org.pk}/statutes/", data)


def publish(client, org, kind=None, department=None, on=True):
    data = {"is_public": on}
    if kind:
        data["kind"] = kind
    if department:
        data["department"] = department.pk
    return client.put(
        f"/api/orgs/{org.pk}/statutes/publication/", data, content_type="application/json"
    )


def path(url: str) -> str:
    return url.split("testserver", 1)[1]


def test_getrennt_von_der_satzung(orgs, board_a, api):
    c = api(board_a)
    base = f"/api/orgs/{orgs['a'].pk}/statutes/"
    assert upload(c, orgs["a"], body=b"%PDF-1.4 Satzung").status_code == 201
    resp = upload(c, orgs["a"], kind="fee_rules", valid_from="2025-03-01")
    assert resp.status_code == 201
    assert resp.json()["kind"] == "fee_rules"
    assert [v["valid_from"] for v in resp.json()["versions"]] == ["2025-03-01"]
    # Ohne Angabe: Satzung wie bisher
    data = c.get(base).json()
    assert data["kind"] == "statute"
    assert [v["valid_from"] for v in data["versions"]] == ["2024-01-01"]
    fee = c.get(f"{base}?kind=fee_rules").json()
    assert [v["valid_from"] for v in fee["versions"]] == ["2025-03-01"]
    assert StatuteVersion.objects.get(kind="fee_rules").file.name.endswith("ordnung.pdf")
    # Unbekannte Art abgelehnt
    assert c.get(f"{base}?kind=geheim").status_code == 400
    # Protokoll nennt die Art
    from audit.models import AuditEntry

    assert any(
        "Beitragsordnung" in str(e.changes)
        for e in AuditEntry.objects.filter(organization=orgs["a"], action="create")
    )


def test_optional_leer(orgs, board_a, api):
    data = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/statutes/?kind=fee_rules").json()
    assert data["versions"] == [] and data["publication"]["is_public"] is False


def test_untereinheit_eigene_beitragsordnung_und_link(orgs, board_a, api):
    c = api(board_a)
    zug = Department.objects.create(organization=orgs["a"], name="1. Zug", founding_year=1990)
    upload(c, orgs["a"], department=zug, body=b"%PDF-1.4 Satzung Zug")
    upload(c, orgs["a"], kind="fee_rules", department=zug)
    statute = publish(c, orgs["a"], department=zug).json()
    fee = publish(c, orgs["a"], kind="fee_rules", department=zug).json()
    assert statute["pdf_url"] != fee["pdf_url"]
    anon = Client()
    body = b"".join(anon.get(path(fee["pdf_url"])).streaming_content)
    assert body == b"%PDF-1.4 erfundene Beitragsordnung"
    info = anon.get(path(fee["info_url"])).json()
    assert info["kind"] == "fee_rules" and info["title"] == "Beitragsordnung"
    assert info["department"] == "1. Zug"
    # Beitragsordnung aus: Satzung bleibt öffentlich
    publish(c, orgs["a"], kind="fee_rules", department=zug, on=False)
    assert anon.get(path(fee["pdf_url"])).status_code == 404
    assert anon.get(path(statute["pdf_url"])).status_code == 200
    assert StatutePublication.objects.filter(department=zug).count() == 2


def test_webseite_dokumente(orgs, board_a, api):
    org = orgs["a"]
    org.enabled_modules = ["members", "website"]
    org.save()
    Website.objects.create(organization=org, public_key="schluessel-a", state="public")
    c = api(board_a)
    info = Client().get("/api/public/site/v1/schluessel-a/").json()
    assert info["fee_rules_url"] is None and info["fee_rules_preview_url"] is None
    upload(c, org, kind="fee_rules")
    url = publish(c, org, kind="fee_rules").json()["pdf_url"]
    info = Client().get("/api/public/site/v1/schluessel-a/").json()
    # Nur die Beitragsordnung ist öffentlich: sie steht unter „Dokumente“, die Satzung nicht
    assert info["fee_rules_url"] == url
    assert info["statute_url"] is None
    assert info["fee_rules_preview_url"].endswith("/schluessel-a/fee-rules/preview/")
    assert any(item.get("key") == "statutes" for item in _flat(info["nav"]))
    # Kaputte PDF: keine Vorschau, aber kein Fehler
    assert Client().get("/api/public/site/v1/schluessel-a/fee-rules/preview/").status_code == 404
    assert Client().get("/api/public/site/v1/schluessel-a/statute/preview/").status_code == 404


def _flat(items):
    for item in items or []:
        yield item
        yield from _flat(item.get("children"))
