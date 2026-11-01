"""Wettbewerbe Schritt 6: Urkunden und Startkarten (alles erfunden)."""

import io

import pytest
from PIL import Image
from pypdf import PdfReader

from accounts.models import StoredSignature
from competitions import certificates
from competitions.models import CertificateTemplate

from .test_wettbewerbe import _punkte, _starter, club, schuetzen, url, zuege  # noqa: F401
from .test_wettbewerbe_auszeichnungen import _final, _schiessen


def _text(resp) -> str:
    assert resp.status_code == 200, resp.content
    assert resp["Content-Type"] == "application/pdf"
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(resp.content)).pages)


def _pages(resp) -> int:
    return len(PdfReader(io.BytesIO(resp.content)).pages)


def test_zeilen_mit_platzhaltern():
    values = {"name": "Max Muster", "einheit": "", "platz": "1", "titel": ""}
    lines = certificates.render_lines("# {name}\n{einheit}\nden\n# {platz}. Platz\n{titel}", values)
    assert lines == [("Max Muster", True), ("den", False), ("1. Platz", True)]
    # Unbekannte Platzhalter bleiben stehen
    assert certificates.render_lines("{unbekannt}", values) == [("{unbekannt}", False)]


@pytest.mark.django_db(transaction=True)
class TestUrkunden:
    def _wettbewerb(self, c, club, schuetzen):  # noqa: F811
        comp_id, einzel, zug = _schiessen(c, club)
        for first, value in (("Max", 30), ("Erika", 28), ("Jürgen", 27), ("Anna", 20)):
            s = _starter(c, club, comp_id, membership=schuetzen[first].pk)
            assert _punkte(c, club, comp_id, einzel, s["id"], value).status_code == 200
        return comp_id, einzel, zug

    def test_seriendruck_mit_vorlage_und_unterschrift(self, club, schuetzen, board_a, api):  # noqa: F811
        c = api(board_a)
        comp_id, einzel, zug = self._wettbewerb(c, club, schuetzen)
        r = c.post(
            url(club, f"{comp_id}/awards/"),
            {"scoring": einzel, "place_from": 1, "place_to": 1, "title": "Vereinsmeister"},
            "application/json",
        )
        assert r.status_code == 201
        _final(c, club, comp_id)
        tpl = c.post(
            url(club, "certificate-templates/"),
            {
                "name": "Vereinsmeisterschaft",
                "signers": [
                    {"name": "Max Muster", "function": "1. Vorsitzender"},
                    {"name": "Otto Normal", "function": "Schießmeister"},
                    {"name": "zu viel", "function": ""},
                ],
            },
            "application/json",
        )
        assert tpl.status_code == 400  # höchstens zwei Unterschriften
        tpl = c.post(
            url(club, "certificate-templates/"),
            {
                "name": "Vereinsmeisterschaft",
                "signers": [{"name": "Max Muster", "function": "1. Vorsitzender"}],
            },
            "application/json",
        )
        assert tpl.status_code == 201, tpl.content
        tid = tpl.json()["id"]
        # Hintergrundbild: geprüft und als JPEG neu geschrieben
        buf = io.BytesIO()
        Image.new("RGB", (60, 85), (250, 240, 200)).save(buf, "PNG")
        buf.seek(0)
        buf.name = "rahmen.png"
        r = c.post(url(club, f"certificate-templates/{tid}/background/"), {"file": buf})
        assert r.status_code == 201, r.content
        assert r.json()["has_background"] is True
        bad = io.BytesIO(b"kein Bild")
        bad.name = "x.png"
        r = c.post(url(club, f"certificate-templates/{tid}/background/"), {"file": bad})
        assert r.status_code == 400

        resp = c.get(url(club, f"{comp_id}/certificates/?vorlage={tid}&bis=3"))
        text = _text(resp)
        # Einzel 1.–3. und Zugwertung 1.–2. (zwei Züge)
        assert _pages(resp) == 5
        assert "Max Muster" in text and "Vereinsmeister 2027" in text
        assert "1. Platz" in text and "3. Platz" in text
        assert "Anna Schmidt" not in text
        assert "1. Vorsitzender" in text
        # Nur eine Wertung, nur ein Starter
        resp = c.get(url(club, f"{comp_id}/certificates/?vorlage={tid}&bis=1&wertung={einzel}"))
        assert _pages(resp) == 1
        # Unterschrift: nur die eigene, hinterlegte
        r = c.get(url(club, f"{comp_id}/certificates/?unterschrift=1"))
        assert r.status_code == 400
        StoredSignature.objects.create(user=board_a, strokes={"s": [[0, 0, 10, 10, 20, 5]]})
        r = c.get(url(club, f"{comp_id}/certificates/?unterschrift=1&bis=1"))
        assert r.status_code == 200
        # Probeurkunde
        assert "Max Muster" in _text(c.get(url(club, f"certificate-templates/{tid}/preview/")))
        # Vorlage am Wettbewerb und beim Kopieren
        r = c.patch(url(club, f"{comp_id}/"), {"certificate_template": tid}, "application/json")
        assert r.status_code == 200 and r.json()["certificate_template"] == tid
        # Löschen der Vorlage lässt den Wettbewerb stehen
        assert c.delete(url(club, f"certificate-templates/{tid}/")).status_code == 204
        assert not CertificateTemplate.objects.exists()
        assert c.get(url(club, f"{comp_id}/")).json()["certificate_template"] is None

    def test_fremde_vorlage_und_rechte(self, club, schuetzen, orgs, board_a, board_b, api):  # noqa: F811
        c = api(board_a)
        comp_id, _e, _z = self._wettbewerb(c, club, schuetzen)
        fremd = CertificateTemplate.objects.create(organization=orgs["b"], name="Fremd")
        assert c.get(url(club, f"{comp_id}/certificates/?vorlage={fremd.pk}")).status_code == 404
        r = c.patch(
            url(club, f"{comp_id}/"), {"certificate_template": fremd.pk}, "application/json"
        )
        assert r.status_code == 400

    def test_startkarten(self, club, schuetzen, board_a, api):  # noqa: F811
        c = api(board_a)
        comp_id, _e, _z = self._wettbewerb(c, club, schuetzen)
        resp = c.get(url(club, f"{comp_id}/start-cards/?sortierung=einheit"))
        text = _text(resp)
        assert "Max Muster" in text and "Startnummer" in text and "Summe" in text
        assert _pages(resp) == 1  # vier Starter, vier Karten je Seite
        resp = c.get(url(club, f"{comp_id}/start-cards/?art=aufkleber"))
        assert "Anna Schmidt" in _text(resp)
