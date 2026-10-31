"""Wappen/Logo mit weißem Hintergrund automatisch freistellen (Ralf 2026-10-30)."""

import io

from PIL import Image, ImageDraw

from core.filecheck import remove_white_background


def wappen(background="white", mode="RGB") -> Image.Image:
    """Grüner Kreis auf weißem Grund mit weißem Feld in der Mitte."""
    img = Image.new(mode, (200, 200), background)
    draw = ImageDraw.Draw(img)
    draw.ellipse((20, 20, 180, 180), fill=(40, 110, 60, 255) if mode == "RGBA" else (40, 110, 60))
    draw.rectangle((80, 80, 120, 120), fill="white")
    return img


def test_weisser_rand_wird_durchsichtig_innen_bleibt_weiss():
    out = remove_white_background(wappen())
    assert out.mode == "RGBA"
    assert out.getpixel((2, 2))[3] == 0  # Ecke außen
    assert out.getpixel((100, 100)) == (255, 255, 255, 255)  # weißes Feld innen
    assert out.getpixel((50, 100)) == (40, 110, 60, 255)  # Wappen selbst


def test_leicht_verrauschtes_weiss_zaehlt_als_hintergrund():
    out = remove_white_background(wappen(background=(246, 248, 244)))
    assert out.getpixel((2, 2))[3] == 0


def test_schon_freigestellt_bleibt_unveraendert():
    img = wappen(background=(255, 255, 255, 0), mode="RGBA")
    out = remove_white_background(img)
    assert out.getpixel((100, 100)) == (255, 255, 255, 255)
    assert out.tobytes() == img.tobytes()


def test_ohne_weissen_rand_bleibt_alles_deckend():
    img = wappen(background=(200, 30, 30))
    out = remove_white_background(img)
    assert out.getchannel("A").getextrema() == (255, 255)


def png(img: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    buf.name = "wappen.png"
    return buf


def test_hochladen_mit_freistellen(api, orgs, board_a):
    url = f"/api/orgs/{orgs['a'].pk}/logo/"
    resp = api(board_a).post(url, {"logo": png(wappen()), "remove_background": "true"})
    assert resp.status_code == 200, resp.content
    orgs["a"].refresh_from_db()
    with orgs["a"].logo.open("rb") as handle:
        saved = Image.open(io.BytesIO(handle.read()))
        saved.load()
    assert saved.getpixel((2, 2))[3] == 0
    assert saved.getpixel((100, 100))[3] == 255


def test_hochladen_ohne_freistellen_bleibt_deckend(api, orgs, board_a):
    url = f"/api/orgs/{orgs['a'].pk}/logo/"
    resp = api(board_a).post(url, {"logo": png(wappen())})
    assert resp.status_code == 200, resp.content
    orgs["a"].refresh_from_db()
    with orgs["a"].logo.open("rb") as handle:
        saved = Image.open(io.BytesIO(handle.read())).convert("RGBA")
    assert saved.getpixel((2, 2)) == (255, 255, 255, 255)
