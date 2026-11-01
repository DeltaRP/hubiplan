"""Schießscheiben Schritt 3: künstliche Prüfbilder und Messlatte (nur erfundene Daten)."""

import io
import json
import random

import pytest
from django.core.management import call_command
from PIL import Image

from competitions import targets
from competitions.vision import benchmark, synth

# Keine Datenbank nötig; die Markierung hält die gemeinsame Testvorbereitung (conftest) heil,
# wenn diese Datei allein läuft.
pytestmark = pytest.mark.django_db


def test_gleicher_startwert_gleiches_bild():
    a, sa = synth.make_sample("lg10_kyf", 7, px_per_mm=6)
    b, sb = synth.make_sample("lg10_kyf", 7, px_per_mm=6)
    assert a == b and sa.truth() == sb.truth()
    c, _ = synth.make_sample("lg10_kyf", 8, px_per_mm=6)
    assert c != a


def test_loesung_passt_zur_wertung_und_zum_bild():
    image, s = synth.make_sample("lg10_dsb", 3, shots=5, kind="eng", px_per_mm=6)
    t = targets.BY_KEY["lg10_dsb"]
    assert len(s.hits) == 5 and s.kind == "eng"
    assert s.rings == [targets.score(t, x, y).ring for x, y in s.hits]
    photo = Image.open(io.BytesIO(image))
    assert photo.format == "JPEG" and photo.width == s.params.size
    cx, cy = s.center_px
    assert 0 < cx < photo.width and 0 < cy < photo.height
    # Die Mitte der Karte ist im Foto dunkel (schwarzer Spiegel)
    assert sum(photo.convert("RGB").getpixel((int(cx), int(cy)))) < 3 * 120


def test_abbildung_hin_und_zurueck():
    src = [(0, 0), (100, 0), (100, 100), (0, 100)]
    dst = [(10, 20), (130, 15), (125, 140), (5, 120)]
    h = synth.homography(src, dst)
    back = synth.homography(dst, src)
    for p in [(50, 50), (0, 100), (73.5, 12.25)]:
        x, y = synth.apply(back, *synth.apply(h, *p))
        assert abs(x - p[0]) < 1e-6 and abs(y - p[1]) < 1e-6


def test_loch_in_loch_liegt_fast_auf_einem_anderen():
    t = targets.BY_KEY["lg10_kyf"]
    hits = synth.random_hits(t, 5, random.Random(1), "loch_in_loch")  # noqa: S311
    (x0, y0), (x1, y1) = hits[0], hits[-1]
    assert ((x0 - x1) ** 2 + (y0 - y1) ** 2) ** 0.5 < t.caliber * 0.15


def test_messlatte():
    truth = [(0.0, 0.0), (3.0, 0.0), (0.0, -6.0)]
    perfect = benchmark.compare("lg10_kyf", truth, benchmark.Detection(list(truth)))
    assert not perfect.wrong and perfect.max_error_mm == 0
    missing = benchmark.compare("lg10_kyf", truth, benchmark.Detection(truth[:2]))
    assert not missing.count_ok and missing.wrong
    flagged = benchmark.compare(
        "lg10_kyf", truth, benchmark.Detection(truth[:2], needs_review=True)
    )
    res = benchmark.summarize([perfect, missing, flagged])
    assert res["anzahl"] == 3
    assert res["schusszahl_richtig"] == 33.3
    assert res["unbemerkt_falsch"] == 33.3
    assert res["pruefen_zu_recht"] == 100.0


def test_befehl_schreibt_bilder_und_loesungen(tmp_path):
    call_command("scheiben_pruefdaten", str(tmp_path), "--anzahl", "2", "--schwierigkeit", "0")
    lines = (tmp_path / "loesungen.jsonl").read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["bild"] == "0001.jpg" and (tmp_path / "0001.jpg").exists()
    assert first["target"] == "lg10_dsb" and len(first["hits"]) == 5
    # Messlatte mit einer „Erkennung“, die die Lösung kennt: alles richtig
    samples = [((tmp_path / json.loads(x)["bild"]).read_bytes(), json.loads(x)) for x in lines]
    res = benchmark.run(
        samples,
        lambda img, key, n: benchmark.Detection(
            next([tuple(h) for h in s["hits"]] for b, s in samples if b == img)
        ),
    )
    assert res["ringe_richtig"] == 100.0 and res["unbemerkt_falsch"] == 0.0
