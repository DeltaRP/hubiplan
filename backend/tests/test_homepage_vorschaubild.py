"""Vorschaubild der Homepage einer Untereinheit: einmal von der Homepage geholt
(og:image), ersatzweise selbst hochgeladen, öffentlich für die Webseite."""

import io

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from core import safehttp
from organizations import homepage_preview
from organizations.models import Department
from organizations.tasks import fetch_homepage_preview
from website.models import Website

pytestmark = pytest.mark.django_db
JSON = "application/json"


def png(size=(40, 30), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def unit(orgs):
    org = orgs["a"]
    org.enabled_modules = [*(org.enabled_modules or []), "website"]
    org.save()
    Website.objects.create(organization=org, public_key="schluessel-a", state="public")
    return Department.objects.create(
        organization=org, parent=org, name="Jägerzug", website="https://jaeger.example/"
    )


def fake_web(monkeypatch, pages: dict):
    calls = []

    def request(method, url, **kw):
        calls.append(url)
        if url not in pages:
            raise safehttp.SafeHTTPError("nicht erreichbar")
        status, headers, body = pages[url]
        return safehttp.Response(status, headers, body)

    monkeypatch.setattr(safehttp, "request", request)
    return calls


def test_og_image_finden():
    html = """<html><head>
      <meta name="twitter:image" content="/tw.png">
      <meta property="og:image" content="bilder/titel.jpg">
    </head></html>"""
    assert (
        homepage_preview.find_image_url(html, "https://zug.example/start/")
        == "https://zug.example/start/bilder/titel.jpg"
    )
    # http wird zu https, andere Schemata nie
    html2 = '<meta property="og:image" content="http://cdn.example/a.png">'
    assert homepage_preview.find_image_url(html2, "https://x.example/") == (
        "https://cdn.example/a.png"
    )
    html3 = '<meta property="og:image" content="javascript:alert(1)">'
    assert homepage_preview.find_image_url(html3, "https://x.example/") is None
    assert homepage_preview.find_image_url("<p>ohne</p>", "https://x.example/") is None


def test_bild_einmal_holen_mit_weiterleitung(monkeypatch, unit):
    calls = fake_web(
        monkeypatch,
        {
            "https://jaeger.example/": (301, {"Location": "https://www.jaeger.example/"}, b""),
            "https://www.jaeger.example/": (
                200,
                {"Content-Type": "text/html; charset=utf-8"},
                b'<meta property="og:image" content="/titel.png">',
            ),
            "https://www.jaeger.example/titel.png": (200, {"Content-Type": "image/png"}, png()),
        },
    )
    assert fetch_homepage_preview(unit.pk) is True
    unit.refresh_from_db()
    assert unit.website_image.name.endswith(".jpg")
    assert unit.website_image_for == "https://jaeger.example/"
    assert unit.website_image_custom is False
    # Neu als JPEG geschrieben
    assert Image.open(unit.website_image.open()).format == "JPEG"

    # Gleiche Adresse: kein zweiter Abruf
    calls.clear()
    assert fetch_homepage_preview(unit.pk) is False
    assert calls == []


def test_ohne_bild_oder_unerreichbar(monkeypatch, unit):
    fake_web(
        monkeypatch,
        {"https://jaeger.example/": (200, {"Content-Type": "text/html"}, b"<p>kein Bild</p>")},
    )
    assert fetch_homepage_preview(unit.pk) is False
    unit.refresh_from_db()
    assert not unit.website_image
    # Versucht ist versucht: nicht bei jedem Speichern wieder
    assert unit.website_image_for == "https://jaeger.example/"

    unit.website = "https://weg.example/"
    unit.save()
    fake_web(monkeypatch, {})
    assert fetch_homepage_preview(unit.pk) is False


def test_keine_internen_adressen(monkeypatch, unit):
    # Echte Prüfung von safehttp: localhost ist intern und wird nie abgerufen
    unit.website = "https://localhost/"
    unit.save()
    with pytest.raises(homepage_preview.NoPreview, match="nicht erreichbar"):
        homepage_preview.fetch_preview(unit.website)


def test_eigenes_bild_hat_vorrang(monkeypatch, api, orgs, board_a, unit):
    c = api(board_a)
    url = f"/api/orgs/{orgs['a'].pk}/departments/{unit.pk}/homepage-image/"
    upload = SimpleUploadedFile("eigen.png", png((80, 40)), content_type="image/png")
    resp = c.post(url, {"image": upload})
    assert resp.status_code == 200, resp.json()
    unit.refresh_from_db()
    assert unit.website_image_custom is True
    assert unit.website_image.name.endswith(".jpg")

    detail = c.get(f"/api/orgs/{orgs['a'].pk}/departments/{unit.pk}/").json()
    assert detail["website_image_url"].endswith(".jpg")
    assert detail["website_image_custom"] is True

    # Eigenes Bild wird beim Holen nie ersetzt
    calls = fake_web(monkeypatch, {})
    unit.website = "https://neu.example/"
    unit.save()
    assert not homepage_preview.needs_refresh(unit)
    assert fetch_homepage_preview(unit.pk) is False
    assert calls == []

    # Kein Bild, sondern Text: abgelehnt
    bad = SimpleUploadedFile("x.png", b"kein bild", content_type="image/png")
    assert c.post(url, {"image": bad}).status_code == 400

    # Entfernen: sofort neu von der Homepage holen, mit Grund, wenn nichts kam
    resp = c.delete(url)
    assert resp.status_code == 200
    assert resp.json()["website_image_url"] is None
    assert "nicht erreichbar" in resp.json()["message"]
    unit.refresh_from_db()
    assert not unit.website_image
    assert unit.website_image_custom is False
    assert unit.website_image_for == "https://neu.example/"

    # Homepage ohne og:image: klare Meldung
    fake_web(
        monkeypatch,
        {"https://neu.example/": (200, {"Content-Type": "text/html"}, b"<p>nichts</p>")},
    )
    assert "kein Vorschaubild" in c.delete(url).json()["message"]

    # Mit Bild: sofort da
    fake_web(
        monkeypatch,
        {
            "https://neu.example/": (
                200,
                {"Content-Type": "text/html"},
                b'<meta property="og:image" content="https://neu.example/b.png">',
            ),
            "https://neu.example/b.png": (200, {"Content-Type": "image/png"}, png()),
        },
    )
    data = c.delete(url).json()
    assert data["message"] == ""
    assert data["website_image_url"].endswith(".jpg")


def test_fremde_einheit_kein_hochladen(api, orgs, board_b, unit):
    url = f"/api/orgs/{orgs['a'].pk}/departments/{unit.pk}/homepage-image/"
    upload = SimpleUploadedFile("eigen.png", png(), content_type="image/png")
    assert api(board_b).post(url, {"image": upload}).status_code in (403, 404)


def test_speichern_plant_abruf(
    monkeypatch, api, orgs, board_a, unit, django_capture_on_commit_callbacks
):
    from organizations import tasks

    planned = []
    monkeypatch.setattr(tasks.fetch_homepage_preview, "delay", planned.append)
    c = api(board_a)
    url = f"/api/orgs/{orgs['a'].pk}/departments/{unit.pk}/"
    with django_capture_on_commit_callbacks(execute=True):
        c.patch(url, {"website": "https://anders.example/"}, content_type=JSON)
    assert planned == [unit.pk]


def test_webseite_bekommt_bild_nur_mit_link(unit):
    detail = "/api/public/site/v1/schluessel-a/units/jaegerzug/"
    unit.website_image.save("vorschau.jpg", ContentFile(png()), save=False)
    unit.save()
    assert Client().get(detail).json()["homepage_image"] is None

    unit.website_on_site = True
    unit.save()
    data = Client().get(detail).json()
    assert data["homepage"] == "https://jaeger.example/"
    assert data["homepage_image"].startswith("http")
    assert data["homepage_image"].endswith(".jpg")


def test_eigenes_bild_waehrend_des_abrufs_bleibt(monkeypatch, unit):
    """Gesamtaudit 01.11., GA-F10: Ein langsamer Abruf überschreibt kein neues eigenes Bild."""
    from django.core.files.base import ContentFile

    from organizations import homepage_preview
    from organizations.models import Department

    saved = {}

    def langsam(url):
        # Während des Abrufs lädt jemand ein eigenes Bild hoch
        other = Department.objects.get(pk=unit.pk)
        other.website_image.save("eigen.png", ContentFile(png()), save=False)
        other.website_image_custom = True
        other.save()
        saved["name"] = other.website_image.name
        return png()

    monkeypatch.setattr(homepage_preview, "fetch_preview", langsam)
    homepage_preview.refresh(Department.objects.get(pk=unit.pk))
    unit.refresh_from_db()
    assert unit.website_image_custom is True
    assert unit.website_image.name == saved["name"]
