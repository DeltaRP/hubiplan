"""Schießscheiben Schritt 4: Treffer auf einem Foto vorschlagen (nur künstliche Prüffotos).

Die Fotos kommen aus dem Generator (Schritt 3), die Lösung liegt also genau vor. Echte
Scheiben gibt es im Repository nicht.
"""

import datetime
import math

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from competitions import targets
from competitions.models import Competition, Hit, StandAccess
from competitions.target_views import PHOTO_RATE
from competitions.vision import benchmark, detect, synth

from .test_schiessscheiben import verein  # noqa: F401
from .test_wettbewerbe import url

pytestmark = pytest.mark.django_db


def _rings(key, hits):
    t = targets.BY_KEY[key]
    return sorted(targets.score(t, x, y).ring for x, y in hits)


class TestErkennung:
    @pytest.mark.parametrize(("key", "seed"), [("lg10_kyf", 1013), ("lg10_dsb", 1028)])
    def test_einzelne_loecher_genau(self, key, seed):
        image, sample = synth.make_sample(key, seed, difficulty=0.2)
        found = detect.detect(image, key, len(sample.hits))
        assert len(found.hits) == len(sample.hits)
        assert _rings(key, found.hits) == sorted(sample.rings)
        # Abstand zur Mitte (darauf kommt es für die Wertung an) auf 0,15 mm genau
        want = sorted(math.hypot(x, y) for x, y in sample.hits)
        got = sorted(math.hypot(x, y) for x, y in found.hits)
        assert max(abs(a - b) for a, b in zip(want, got, strict=True)) < 0.15

    def test_messlatte_leichte_fotos(self):
        """Grobe Untergrenze, damit eine Verschlechterung auffällt (Werte in docs)."""
        samples = [
            synth.make_sample(["lg10_dsb", "lg10_kyf"][i % 2], 2000 + i, difficulty=0.3)
            for i in range(12)
        ]

        def run(image, key, expected):
            try:
                return detect.detect(image, key, expected)
            except detect.DetectError as exc:
                return benchmark.Detection([], True, str(exc))

        outcomes = [
            benchmark.compare(s.target, s.hits, run(img, s.target, len(s.hits)))
            for img, s in samples
        ]
        summary = benchmark.summarize(outcomes)
        assert summary["schusszahl_richtig"] >= 75, summary
        assert summary["unbemerkt_falsch"] <= 10, summary

    def test_fuenf_spiegel_karte(self):
        image, sample = synth.make_sample("lg10_kyf5", 4002, difficulty=0.3, kind="streuung")
        found = detect.detect(image, "lg10_kyf5", len(sample.hits))
        # alle fünf Spiegel, je fünf Treffer (Nummern in Lesereihenfolge des Fotos)
        assert [found.spots.count(n) for n in range(1, 6)] == [5] * 5
        assert _rings("lg10_kyf5", found.hits) == sorted(sample.rings)

    def test_nicht_auswertbar(self):
        with pytest.raises(detect.DetectError, match="lesen"):
            detect.detect(b"kein Bild", "lg10_dsb")
        ohne = targets.get(
            targets.CUSTOM, {"name": "Weiß", "top_diameter": 3, "ring_width": 5, "caliber": 4.5}
        )
        assert "ohne schwarzen Spiegel" in detect.unsupported(ohne)
        # weißes Blatt ohne Scheibe
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (800, 600), (240, 240, 240)).save(buf, "JPEG")
        with pytest.raises(detect.DetectError, match="Kein Spiegel"):
            detect.detect(buf.getvalue(), "lg10_dsb")


def _photo(seed=1013, key="lg10_kyf"):
    image, sample = synth.make_sample(key, seed, difficulty=0.2)
    return SimpleUploadedFile("scheibe.jpg", image, content_type="image/jpeg"), sample


@pytest.mark.django_db(transaction=True)
class TestFotoSchnittstelle:
    def _wettbewerb(self, c, verein, target="lg10_kyf"):  # noqa: F811
        resp = c.post(
            url(verein),
            {"title": "Pokalschießen 2027", "date": "2027-05-01", "template": "einfach"},
            "application/json",
        )
        comp_id = resp.json()["id"]
        sc = c.get(url(verein, f"{comp_id}/")).json()["scorings"][0]["id"]
        if target:
            resp = c.patch(
                url(verein, f"{comp_id}/scorings/{sc}/"),
                {"target": target, "method": "ringe", "shots": 5},
                "application/json",
            )
            assert resp.status_code == 200, resp.content
        return comp_id, sc

    def test_vorschlag_ohne_speichern(self, verein, board_a, api):  # noqa: F811
        c = api(board_a)
        comp_id, sc = self._wettbewerb(c, verein)
        photo, sample = _photo()
        resp = c.post(url(verein, f"{comp_id}/photo/"), {"scoring": sc, "photo": photo})
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert len(data["hits"]) == 5 and {h["source"] for h in data["hits"]} == {"foto"}
        got = [(float(h["x"]), float(h["y"])) for h in data["hits"]]
        assert _rings("lg10_kyf", got) == sorted(sample.rings)
        assert isinstance(data["needs_review"], bool) and "note" in data
        assert not Hit.objects.exists()  # erst das Bestätigen speichert

    def test_fehler(self, verein, board_a, api):  # noqa: F811
        c = api(board_a)
        comp_id, sc = self._wettbewerb(c, verein, target=None)
        u = url(verein, f"{comp_id}/photo/")
        photo, _ = _photo()
        resp = c.post(u, {"scoring": sc, "photo": photo})
        assert resp.status_code == 400 and "keine Scheibe" in resp.content.decode()
        comp_id, sc = self._wettbewerb(c, verein)
        u = url(verein, f"{comp_id}/photo/")
        assert c.post(u, {"scoring": sc}).status_code == 400
        bad = SimpleUploadedFile("x.jpg", b"kein Bild", content_type="image/jpeg")
        resp = c.post(u, {"scoring": sc, "photo": bad})
        assert resp.status_code == 400 and "lesen" in resp.content.decode()

    def test_standzugang_und_grenze(self, verein, board_a, api, monkeypatch):  # noqa: F811
        from rest_framework.test import APIClient

        c = api(board_a)
        comp_id, sc = self._wettbewerb(c, verein)
        _, token = StandAccess.create(
            Competition.objects.get(pk=comp_id),
            "Tablet",
            None,
            timezone.now() + datetime.timedelta(hours=2),
        )
        pub = APIClient()
        photo, _ = _photo()
        resp = pub.post(
            f"/api/public/stand/{token}/photo/", {"scoring": sc, "photo": photo}, format="multipart"
        )
        assert resp.status_code == 200, resp.content
        assert len(resp.json()["hits"]) == 5
        assert resp["Cache-Control"] == "no-store"

        # Fotos kosten Rechenzeit: Grenze je Zugang
        monkeypatch.setattr("competitions.target_views.PHOTO_RATE", (1, PHOTO_RATE[1]))
        photo, _ = _photo()
        resp = pub.post(
            f"/api/public/stand/{token}/photo/", {"scoring": sc, "photo": photo}, format="multipart"
        )
        assert resp.status_code == 429
