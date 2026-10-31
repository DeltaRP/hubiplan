"""Vorschaubild der Satzung für die Webseite (alles erfunden)."""

import io

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from reportlab.pdfgen import canvas

from statutes.models import StatutePublication
from website.models import Website

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def private_root(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"
    cache.clear()


def real_pdf() -> bytes:
    out = io.BytesIO()
    c = canvas.Canvas(out)
    c.drawString(100, 750, "Satzung des Vereins A")
    c.save()
    return out.getvalue()


@pytest.fixture
def site(orgs):
    org = orgs["a"]
    org.enabled_modules = ["members", "website"]
    org.save()
    return Website.objects.create(organization=org, public_key="schluessel-a", state="public")


def upload(api, user, org, body: bytes):
    f = SimpleUploadedFile("satzung.pdf", body, content_type="application/pdf")
    return api(user).post(f"/api/orgs/{org.pk}/statutes/", {"file": f, "valid_from": "2020-05-01"})


def publish(org):
    StatutePublication.objects.update_or_create(
        organization=org,
        department=None,
        defaults={"is_public": True, "public_key": StatutePublication.new_key()},
    )


def preview():
    return Client().get("/api/public/site/v1/schluessel-a/statute/preview/")


def test_erste_seite_als_png(api, orgs, board_a, site):
    assert upload(api, board_a, orgs["a"], real_pdf()).status_code == 201
    # Noch nicht öffentlich: keine Vorschau, kein Link
    assert preview().status_code == 404
    assert Client().get("/api/public/site/v1/schluessel-a/").json()["statute_preview_url"] is None
    publish(orgs["a"])
    info = Client().get("/api/public/site/v1/schluessel-a/").json()
    assert info["statute_preview_url"].endswith("/schluessel-a/statute/preview/")
    resp = preview()
    assert resp.status_code == 200 and resp["Content-Type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG")
    # Baustein „Dokumente“ aus: keine Vorschau
    site.blocks = {"statutes": False}
    site.save()
    assert preview().status_code == 404


def test_kaputte_pdf_ohne_vorschau(api, orgs, board_a, site):
    # Die Prüfung beim Hochladen sieht nur den Kopf an; der Rest ist hier unlesbar
    assert upload(api, board_a, orgs["a"], b"%PDF-1.4 erfundene Satzung").status_code == 201
    publish(orgs["a"])
    assert preview().status_code == 404


def test_extremes_seitenformat_bleibt_klein(api, orgs, board_a, site):
    # Gesamtaudit 30.10. (B-V02): schmal und sehr hoch → Höhe begrenzt
    from PIL import Image

    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=(50, 14000))
    c.drawString(5, 13000, "Satzung")
    c.save()
    assert upload(api, board_a, orgs["a"], out.getvalue()).status_code == 201
    publish(orgs["a"])
    resp = preview()
    assert resp.status_code == 200
    image = Image.open(
        io.BytesIO(b"".join(resp.streaming_content) if resp.streaming else resp.content)
    )
    assert image.height <= 1200 and image.width <= 480
