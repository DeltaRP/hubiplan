"""Gründungsurkunde je Einheit: optional, gebaut wie die Satzung (alles erfunden)."""

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from organizations.models import Department
from statutes.models import StatuteVersion
from statutes.services import safe_name
from website.models import Website

pytestmark = pytest.mark.django_db(transaction=True)

KIND = "founding_deed"


@pytest.fixture(autouse=True)
def private_root(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"
    cache.clear()


def upload(client, org, kind=KIND, department=None, valid_from="1920-05-01", body=None):
    body = body or b"%PDF-1.4 erfundene Gruendungsurkunde"
    data = {
        "file": SimpleUploadedFile("urkunde.pdf", body, content_type="application/pdf"),
        "valid_from": valid_from,
    }
    if kind:
        data["kind"] = kind
    if department:
        data["department"] = department.pk
    return client.post(f"/api/orgs/{org.pk}/statutes/", data)


def publish(client, org, kind=KIND, department=None, on=True):
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


def test_getrennt_von_satzung_und_beitragsordnung(orgs, board_a, api):
    c = api(board_a)
    base = f"/api/orgs/{orgs['a'].pk}/statutes/"
    assert upload(c, orgs["a"], kind=None, valid_from="2024-01-01").status_code == 201
    assert upload(c, orgs["a"], kind="fee_rules", valid_from="2025-01-01").status_code == 201
    resp = upload(c, orgs["a"])
    assert resp.status_code == 201
    assert resp.json()["kind"] == KIND
    assert [v["valid_from"] for v in resp.json()["versions"]] == ["1920-05-01"]
    assert [v["valid_from"] for v in c.get(base).json()["versions"]] == ["2024-01-01"]
    fee = c.get(f"{base}?kind=fee_rules").json()
    assert [v["valid_from"] for v in fee["versions"]] == ["2025-01-01"]
    assert StatuteVersion.objects.filter(kind=KIND).count() == 1
    from audit.models import AuditEntry

    assert any(
        "Gründungsurkunde" in str(e.changes)
        for e in AuditEntry.objects.filter(organization=orgs["a"], action="create")
    )
    assert safe_name("", KIND) == "gruendungsurkunde.pdf"


def test_optional_leer(orgs, board_a, api):
    data = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/statutes/?kind={KIND}").json()
    assert data["versions"] == [] and data["publication"]["is_public"] is False


def test_untereinheit_eigene_urkunde_und_link(orgs, board_a, api):
    c = api(board_a)
    zug = Department.objects.create(organization=orgs["a"], name="1. Zug", founding_year=1990)
    upload(c, orgs["a"], department=zug)
    pub = publish(c, orgs["a"], department=zug).json()
    anon = Client()
    body = b"".join(anon.get(path(pub["pdf_url"])).streaming_content)
    assert body == b"%PDF-1.4 erfundene Gruendungsurkunde"
    info = anon.get(path(pub["info_url"])).json()
    assert info["kind"] == KIND and info["title"] == "Gründungsurkunde"
    assert info["department"] == "1. Zug"
    publish(c, orgs["a"], department=zug, on=False)
    assert anon.get(path(pub["pdf_url"])).status_code == 404


def test_webseite_dokumente(orgs, board_a, api):
    org = orgs["a"]
    org.enabled_modules = ["members", "website"]
    org.save()
    Website.objects.create(organization=org, public_key="schluessel-a", state="public")
    c = api(board_a)
    info = Client().get("/api/public/site/v1/schluessel-a/").json()
    assert info["founding_deed_url"] is None and info["founding_deed_preview_url"] is None
    assert not any(item.get("key") == "statutes" for item in _flat(info["nav"]))
    upload(c, org)
    url = publish(c, org).json()["pdf_url"]
    cache.clear()
    info = Client().get("/api/public/site/v1/schluessel-a/").json()
    # Nur die Gründungsurkunde ist öffentlich: „Dokumente“ erscheint trotzdem
    assert info["founding_deed_url"] == url
    assert info["statute_url"] is None and info["fee_rules_url"] is None
    assert info["founding_deed_preview_url"].endswith("/schluessel-a/founding-deed/preview/")
    assert any(item.get("key") == "statutes" for item in _flat(info["nav"]))
    # Kaputte PDF: keine Vorschau, aber kein Fehler
    resp = Client().get("/api/public/site/v1/schluessel-a/founding-deed/preview/")
    assert resp.status_code == 404


def _flat(items):
    for item in items or []:
        yield item
        yield from _flat(item.get("children"))
