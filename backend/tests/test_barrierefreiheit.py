"""Barrierefreiheit 30.10.2026: W-06 Alternativtexte, H-12 HTML-Mails."""

import io

import pytest
from django.core import mail as djmail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image

from outbox.mail import html_document, send
from website.models import Website, WebsiteImage

from .factories import give_role, make_user

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def private_root(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def site(orgs):
    org = orgs["a"]
    org.enabled_modules = ["members", "website"]
    org.save()
    return Website.objects.create(
        organization=org, public_key=Website.new_key(), state=Website.State.PUBLIC
    )


@pytest.fixture
def editor(orgs):
    user = make_user("schrift@example.org")
    give_role(user, orgs["a"], permissions=["website.content"], name="Schriftführer")
    return user


def png():
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "red").save(buf, "PNG")
    return SimpleUploadedFile("bild.png", buf.getvalue(), content_type="image/png")


def url(org, rest=""):
    return f"/api/orgs/{org.pk}/website/{rest}"


class TestAlternativtexte:
    def publish_gallery(self, c, org, ids):
        pk = c.get(url(org, "texts/")).json()["texts"][0]["id"]
        c.put(url(org, f"texts/{pk}/"), {"gallery": ids}, "application/json")
        c.post(url(org, f"texts/{pk}/publish/"))

    def test_ohne_alternativtext_gilt_die_bildunterschrift(self, orgs, editor, api, site):
        c = api(editor)
        org = orgs["a"]
        a = c.post(url(org, "images/"), {"file": png(), "caption": "Schützenfest 2025"}).json()
        b = c.post(url(org, "images/"), {"file": png(), "alt_text": "Fahne im Wind"}).json()
        deko = c.post(
            url(org, "images/"), {"file": png(), "caption": "Ranke", "decorative": "true"}
        ).json()
        assert a["decorative"] is False and deko["decorative"] is True
        self.publish_gallery(c, org, [a["id"], b["id"], deko["id"]])
        greeting = Client().get(f"/api/public/site/v1/{site.public_key}/").json()["greeting"]
        assert [i["alt"] for i in greeting["gallery"]] == ["Schützenfest 2025", "Fahne im Wind", ""]

    def test_nachtraeglich_ergaenzen_oder_als_schmuck_markieren(self, orgs, editor, api, site):
        c = api(editor)
        org = orgs["a"]
        image = c.post(url(org, "images/"), {"file": png()}).json()
        resp = c.put(
            url(org, f"images/{image['id']}/"), {"alt_text": "Königspaar"}, "application/json"
        )
        assert resp.status_code == 200 and resp.json()["alt_text"] == "Königspaar"
        resp = c.put(url(org, f"images/{image['id']}/"), {"decorative": True}, "application/json")
        assert resp.json()["decorative"] is True
        # Teiländerung lässt den Alternativtext stehen
        assert WebsiteImage.objects.get(pk=image["id"]).alt_text == "Königspaar"


class TestMails:
    def test_html_teil_ist_dokument_mit_sprache(self, db):
        send("x@example.org", "Rundschreiben <März>", "Hallo", html="<p>Hallo</p>")
        html = djmail.outbox[-1].alternatives[0][0]
        assert html.startswith("<!doctype html>")
        assert '<html lang="de">' in html
        assert "<title>Rundschreiben &lt;März&gt;</title>" in html
        assert "<p>Hallo</p>" in html

    def test_fertiges_dokument_bleibt(self):
        doc = '<!DOCTYPE html><html lang="de"><body>x</body></html>'
        assert html_document(doc, "Betreff") == doc
