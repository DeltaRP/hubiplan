"""Künstliche Scheibenfotos mit bekannter Wertung (Schießscheiben Schritt 3).

Es gibt keine ausgewerteten echten Scheiben (Ralf, 01.11.2026). Klassische Bildverarbeitung
braucht aber nur Prüfdaten, keine Trainingsdaten. Dieses Modul zeichnet deshalb Scheiben aus
den Maßen des Katalogs, setzt Löcher an bekannte Stellen (auch mehrere je Spiegel,
überlappend, Loch in Loch) und ahmt ein Handyfoto nach: Schräge, Drehung, Unschärfe,
ungleichmäßiges Licht, Schatten, Rauschen, JPEG. Die richtige Wertung ist damit exakt
bekannt. Nur Pillow, keine weiteren Abhängigkeiten; alles mit festem Zufallsstartwert
wiederholbar. Konzept: konzepte/schiessscheiben-recherche.md, Abschnitt 5a.

Koordinaten: Treffer in mm von der Scheibenmitte, y nach oben (wie ``Hit``). Im Bild der
Karte liegt die Mitte in der Bildmitte, ``px_per_mm`` Bildpunkte je mm, y nach unten.
"""

from __future__ import annotations

import io
import math
import random
from dataclasses import asdict, dataclass, field

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .. import targets

PAPER = (247, 244, 233)
BLACK = (24, 24, 24)


@dataclass
class PhotoParams:
    """Wie das Foto entstanden ist (alles zufällig in ``random_params``)."""

    size: int = 1600  # Kantenlänge des Fotos in Bildpunkten
    card_share: float = 0.7  # Anteil der Karte an der Bildbreite
    rotation: float = 0.0  # Grad
    tilt_x: float = 0.0  # Schräge als Anteil (0,1 = deutlich schräg)
    tilt_y: float = 0.0
    shift_x: float = 0.0  # Versatz der Karte als Anteil der Bildgröße
    shift_y: float = 0.0
    blur: float = 0.0  # Gauß-Radius in Bildpunkten
    light: float = 0.0  # Stärke des Lichtverlaufs (0 bis 0,5)
    light_angle: float = 0.0
    shadow: float = 0.0  # Stärke eines Schattens (0 bis 0,6)
    noise: float = 0.0  # Rauschen (0 bis 30)
    jpeg: int = 90
    backdrop: tuple[int, int, int] = (90, 75, 60)  # was durch die Löcher scheint (Tisch)


@dataclass
class Sample:
    """Ein Prüfbild mit Lösung."""

    target: str
    hits: list[tuple[float, float]]  # mm
    rings: list[int]
    decimals: list[str]
    params: PhotoParams
    # Lage im Foto: Mitte und Treffer in Bildpunkten, Abbildung Karte → Foto
    center_px: tuple[float, float] = (0.0, 0.0)
    hits_px: list[tuple[float, float]] = field(default_factory=list)
    homography: list[float] = field(default_factory=list)
    kind: str = ""  # wie die Treffer liegen (streuung, eng, loch_in_loch …)
    # Karten mit mehreren Spiegeln: Spiegel je Treffer (ab 1, Lesereihenfolge auf der Karte);
    # ``hits`` sind dann je Spiegel um dessen Mitte gemessen
    spots: list[int] = field(default_factory=list)

    def truth(self) -> dict:
        data = asdict(self)
        data["params"] = asdict(self.params)
        return data


# --- Scheibe zeichnen ---


def spot_offsets(t: targets.Target) -> list[tuple[float, float]]:
    """Mitten der Spiegel auf der Karte (mm, y nach oben), in Lesereihenfolge.

    Fünf Spiegel in den vier Ecken und der Mitte (üblich laut Ralf, 01.11.2026; genaue Maße
    der echten Karte nicht geprüft), sonst Reihen zu drei. Die Erkennung setzt keine
    Anordnung voraus."""
    if t.spots <= 1:
        return [(0.0, 0.0)]
    gap = t.outer_diameter + 4.0  # Abstand zweier Spiegelmitten mindestens
    if t.spots == 5:
        p = gap / math.sqrt(2)
        return [(-p, p), (p, p), (0.0, 0.0), (-p, -p), (p, -p)]
    cols = 3
    rows = math.ceil(t.spots / cols)
    out = []
    for i in range(t.spots):
        r, k = divmod(i, cols)
        out.append(((k - (cols - 1) / 2) * gap, ((rows - 1) / 2 - r) * gap))
    return out


def card_size_mm(t: targets.Target) -> float:
    extent = max(max(abs(x), abs(y)) for x, y in spot_offsets(t))
    return 2 * extent + t.outer_diameter + max(12.0, t.outer_diameter * 0.15)


def _ragged(cx, cy, r, rng: random.Random, amount: float, steps: int = 48):
    """Umriss eines Lochs: Kreis mit leicht ausgefranstem Rand."""
    phase = [rng.uniform(0, 2 * math.pi) for _ in range(3)]
    out = []
    for i in range(steps):
        a = 2 * math.pi * i / steps
        wobble = sum(math.sin((k + 2) * a + phase[k]) / (k + 2) for k in range(3))
        rr = r * (1 + amount * wobble + amount * 0.5 * rng.uniform(-1, 1))
        out.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return out


def render_card(
    t: targets.Target,
    hits: list[tuple[float, float]],
    *,
    px_per_mm: float = 16.0,
    rng: random.Random | None = None,
    backdrop: tuple[int, int, int] = (90, 75, 60),
) -> Image.Image:
    """Karte mit Ringen, Spiegel, Zahlen und Löchern (RGB)."""
    rng = rng or random.Random(0)  # noqa: S311 (Prüfbilder, kein Geheimnis)
    side = card_size_mm(t)
    n = int(round(side * px_per_mm))
    img = Image.new("RGB", (n, n), PAPER)
    d = ImageDraw.Draw(img)
    c = n / 2

    def circle(r_mm, **kw):
        r = r_mm * px_per_mm
        d.ellipse((c - r, c - r, c + r, c + r), **kw)

    for ox, oy in spot_offsets(t):
        _draw_spot(d, t, c + ox * px_per_mm, c - oy * px_per_mm, px_per_mm)
    _draw_holes(d, hits, c, px_per_mm, t, rng, backdrop)
    return img


def _draw_spot(d: ImageDraw.ImageDraw, t: targets.Target, cx: float, cy: float, px_per_mm):
    """Ein Scheibenbild (Spiegel, Ringe, Zahlen) mit Mitte ``cx``/``cy`` (Bildpunkte)."""

    def circle(r_mm, **kw):
        r = r_mm * px_per_mm
        d.ellipse((cx - r, cy - r, cx + r, cy + r), **kw)

    black_r = (t.black_diameter or 0) / 2
    if black_r:
        circle(black_r, fill=BLACK)
    line = max(1, int(round(0.15 * px_per_mm)))
    for ring in range(t.lowest, t.top + 1):
        r = t.ring_diameter(ring) / 2
        color = PAPER if r < black_r - 1e-6 else BLACK
        circle(r, outline=color, width=line)
    if t.inner_diameter:
        r = t.inner_diameter / 2
        circle(r, outline=PAPER if r < black_r else BLACK, width=line)
        if t.inner_mode == targets.INNER_COVER:
            circle(r, fill=PAPER)  # weißer Punkt (LG)
    font = ImageFont.load_default(size=max(8, int(t.ring_width * px_per_mm * 0.55)))
    for ring in range(t.lowest, t.top):
        pos = (t.ring_diameter(ring) / 2 - t.ring_width / 2) * px_per_mm
        color = PAPER if pos / px_per_mm < black_r else BLACK
        for dx, dy in ((pos, 0), (-pos, 0), (0, pos), (0, -pos)):
            d.text((cx + dx, cy + dy), str(ring), fill=color, font=font, anchor="mm")


def _draw_holes(d, hits, c, px_per_mm, t, rng, backdrop):
    """Löcher (Kartenmaße in mm um die Kartenmitte): erst Bleirand (Abrieb, nur auf Weiß
    sichtbar), dann das Loch selbst."""
    hole_r = t.caliber / 2 * px_per_mm
    for x, y in hits:
        hx, hy = c + x * px_per_mm, c - y * px_per_mm
        rim = _ragged(hx, hy, hole_r * 1.08, rng, 0.05)
        d.polygon(rim, fill=(70, 70, 72))
    for x, y in hits:
        hx, hy = c + x * px_per_mm, c - y * px_per_mm
        hole = _ragged(hx, hy, hole_r * rng.uniform(0.95, 1.0), rng, 0.04)
        d.polygon(hole, fill=backdrop)
        # Papierfasern am Rand: einige helle Spitzen ins Loch
        for _ in range(rng.randint(3, 8)):
            a = rng.uniform(0, 2 * math.pi)
            r0, r1 = hole_r, hole_r * rng.uniform(0.75, 0.92)
            d.line(
                (
                    hx + r0 * math.cos(a),
                    hy + r0 * math.sin(a),
                    hx + r1 * math.cos(a),
                    hy + r1 * math.sin(a),
                ),
                fill=(205, 200, 188),
                width=max(1, int(px_per_mm * 0.08)),
            )


# --- Treffer erzeugen ---


def random_hits(
    t: targets.Target, count: int, rng: random.Random, kind: str = "streuung"
) -> list[tuple[float, float]]:
    """Treffer wie von Schützen: normalverteilt um einen Mittelpunkt.

    ``streuung``: übliche Streuung (Ringe 6–10), ``eng``: gute Serie, Löcher überlappen,
    ``loch_in_loch``: ein Schuss fast genau durch ein vorhandenes Loch, ``weit``: auch
    Ringe am Rand und Fehlschüsse."""
    w = t.ring_width
    spread = {"eng": 0.35 * w, "loch_in_loch": 0.5 * w, "weit": 3.0 * w}.get(kind, 1.2 * w)
    mx, my = rng.gauss(0, 0.3 * w), rng.gauss(0, 0.3 * w)
    limit = t.outer_diameter / 2 + w
    out: list[tuple[float, float]] = []
    while len(out) < count:
        x, y = rng.gauss(mx, spread), rng.gauss(my, spread)
        if math.hypot(x, y) > limit:
            continue
        out.append((round(x, 3), round(y, 3)))
    if kind == "loch_in_loch" and count >= 2:
        bx, by = out[0]
        off = t.caliber * rng.uniform(0.02, 0.12)
        a = rng.uniform(0, 2 * math.pi)
        out[-1] = (round(bx + off * math.cos(a), 3), round(by + off * math.sin(a), 3))
    return out


# --- Handyfoto nachahmen ---


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Lineares Gleichungssystem (Gauß mit Spaltenpivot), klein und ohne numpy."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        p = m[col][col]
        if abs(p) < 1e-12:
            raise ValueError("Abbildung nicht bestimmbar")
        for r in range(n):
            if r != col:
                f = m[r][col] / p
                for k in range(col, n + 1):
                    m[r][k] -= f * m[col][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def homography(src: list[tuple[float, float]], dst: list[tuple[float, float]]) -> list[float]:
    """3×3-Abbildung (als 8 Werte, h33 = 1), die vier Punkte ``src`` auf ``dst`` legt."""
    a, b = [], []
    for (x, y), (u, v) in zip(src, dst, strict=True):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    return _solve(a, b)


def apply(h: list[float], x: float, y: float) -> tuple[float, float]:
    w = h[6] * x + h[7] * y + 1
    return ((h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w)


def random_params(rng: random.Random, difficulty: float = 0.5) -> PhotoParams:
    """Zufällige Aufnahmebedingungen; ``difficulty`` 0 (Scanner) bis 1 (schwieriges Foto)."""
    k = max(0.0, min(1.0, difficulty))
    return PhotoParams(
        size=rng.choice([1200, 1600, 2000]),
        card_share=rng.uniform(0.55, 0.85),
        rotation=rng.uniform(-180, 180) * k,
        tilt_x=rng.uniform(-0.12, 0.12) * k,
        tilt_y=rng.uniform(-0.12, 0.12) * k,
        shift_x=rng.uniform(-0.06, 0.06) * k,
        shift_y=rng.uniform(-0.06, 0.06) * k,
        blur=rng.uniform(0, 2.2) * k,
        light=rng.uniform(0, 0.45) * k,
        light_angle=rng.uniform(0, 360),
        shadow=rng.uniform(0, 0.5) * k if rng.random() < 0.6 else 0.0,
        noise=rng.uniform(0, 18) * k,
        jpeg=int(95 - 35 * k * rng.random()),
        backdrop=rng.choice([(90, 75, 60), (40, 40, 45), (150, 150, 150), (235, 235, 235)]),
    )


def photograph(card: Image.Image, p: PhotoParams, rng: random.Random):
    """Karte wie mit dem Handy fotografiert. Zurück: Bild und Abbildung Karte → Foto."""
    n = card.width
    size = p.size
    half = p.card_share * size / 2
    cx, cy = size / 2 + p.shift_x * size, size / 2 + p.shift_y * size
    rot = math.radians(p.rotation)
    corners = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        # Schräge: eine Seite näher an der Kamera (größer)
        scale = 1 + p.tilt_x * sx + p.tilt_y * sy
        x, y = sx * half * scale, sy * half * scale
        corners.append(
            (cx + x * math.cos(rot) - y * math.sin(rot), cy + x * math.sin(rot) + y * math.cos(rot))
        )
    src = [(0, 0), (n, 0), (n, n), (0, n)]
    h = homography(src, corners)  # Karte → Foto
    inv = homography(corners, src)  # Foto → Karte (für Pillow)
    background = Image.new("RGB", (size, size), (120 + rng.randint(-30, 30),) * 3)
    background = Image.blend(background, _noise(size, rng), 0.15)
    warped = card.transform(
        (size, size), Image.Transform.PERSPECTIVE, inv, Image.Resampling.BICUBIC
    )
    mask = Image.new("L", (n, n), 255).transform(
        (size, size), Image.Transform.PERSPECTIVE, inv, Image.Resampling.BILINEAR
    )
    photo = Image.composite(warped, background, mask)
    if p.light:
        photo = ImageChops.multiply(photo, _gradient(size, p.light, p.light_angle))
    if p.shadow:
        photo = ImageChops.multiply(photo, _shadow(size, p.shadow, rng))
    if p.blur:
        photo = photo.filter(ImageFilter.GaussianBlur(p.blur))
    if p.noise:
        # gleichverteiltes Rauschen hat Streuung ≈ 74; auf die gewünschte Stärke dämpfen
        gray = Image.new("RGB", (size, size), (128, 128, 128))
        noise = Image.blend(gray, _noise(size, rng), min(1.0, p.noise / 74))
        photo = ImageChops.add(photo, noise, scale=1.0, offset=-128)
    return photo, h


def _noise(size: int, rng: random.Random) -> Image.Image:
    """Rauschen aus dem eigenen Zufallsgenerator (wiederholbar, anders als effect_noise)."""
    g = Image.frombytes("L", (size, size), rng.randbytes(size * size))
    return Image.merge("RGB", (g, g, g))


def _gradient(size: int, strength: float, angle: float) -> Image.Image:
    """Lichtverlauf: eine Seite heller, die andere dunkler (Faktor 1 − strength bis 1)."""
    g = Image.linear_gradient("L").resize((size, size)).rotate(angle, expand=False, fillcolor=128)
    low = int(255 * (1 - strength))
    g = g.point(lambda v: low + (255 - low) * v // 255)
    return Image.merge("RGB", (g, g, g))


def _shadow(size: int, strength: float, rng: random.Random) -> Image.Image:
    """Weicher Schatten (Hand, Handy) über einem Teil des Bildes."""
    m = Image.new("L", (size, size), 255)
    d = ImageDraw.Draw(m)
    x0, y0 = rng.uniform(-0.3, 0.6) * size, rng.uniform(-0.3, 0.6) * size
    w, hgt = rng.uniform(0.3, 0.7) * size, rng.uniform(0.3, 0.7) * size
    d.ellipse((x0, y0, x0 + w, y0 + hgt), fill=int(255 * (1 - strength)))
    m = m.filter(ImageFilter.GaussianBlur(size * 0.05))
    return Image.merge("RGB", (m, m, m))


def jpeg_bytes(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


# --- Prüfbild aus einem Guss ---

KINDS = ("streuung", "eng", "loch_in_loch", "weit")


def make_sample(
    target_key: str,
    seed: int,
    *,
    shots: int = 5,
    kind: str | None = None,
    difficulty: float = 0.5,
    px_per_mm: float = 16.0,
) -> tuple[bytes, Sample]:
    """Ein Prüfbild (JPEG) und seine Lösung. Gleicher Startwert, gleiches Bild."""
    rng = random.Random(seed)  # noqa: S311 (wiederholbare Prüfbilder)
    t = targets.BY_KEY[target_key]
    kind = kind or rng.choice(KINDS)
    offsets = spot_offsets(t)
    # je Spiegel ``shots`` Treffer (Karten mit mehreren Spiegeln: je Spiegel eine Serie)
    hits: list[tuple[float, float]] = []
    spots: list[int] = []
    for n in range(len(offsets)):
        hits += random_hits(t, shots, rng, kind)
        spots += [n + 1] * shots
    card_hits = [
        (x + offsets[sp - 1][0], y + offsets[sp - 1][1])
        for (x, y), sp in zip(hits, spots, strict=True)
    ]
    params = random_params(rng, difficulty)
    card = render_card(t, card_hits, px_per_mm=px_per_mm, rng=rng, backdrop=params.backdrop)
    photo, h = photograph(card, params, rng)
    c = card.width / 2

    def to_photo(x_mm, y_mm):
        return apply(h, c + x_mm * px_per_mm, c - y_mm * px_per_mm)

    values = [targets.score(t, x, y) for x, y in hits]
    sample = Sample(
        target=target_key,
        hits=hits,
        rings=[v.ring for v in values],
        decimals=[str(v.decimal) for v in values],
        params=params,
        center_px=tuple(round(v, 2) for v in to_photo(0, 0)),
        hits_px=[tuple(round(v, 2) for v in to_photo(x, y)) for x, y in card_hits],
        homography=[round(v, 9) for v in h],
        kind=kind,
        spots=spots if len(offsets) > 1 else [],
    )
    return jpeg_bytes(photo, params.jpeg), sample
