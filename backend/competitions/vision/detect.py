"""Treffer auf einem Scheibenfoto finden (Schießscheiben Schritt 4), klassisch mit OpenCV.

Ablauf (Recherche Abschnitt 5):
1. Spiegel (schwarze Fläche) als Ellipse finden: grobe Mitte, Maßstab und Schräge.
2. Genauer entzerren: Spiegelrand und Ringlinien entlang von Strahlen suchen und daraus
   die volle Abbildung schätzen, bis der Spiegel ein Kreis mit seinem echten Durchmesser
   ist (``PX_PER_MM`` Bildpunkte je mm, Mitte in der Bildmitte).
3. Löcher: was im Spiegel und auf dem Papier deutlich von der örtlichen Helligkeit
   abweicht. Dünne Ringlinien und Zahlen fallen durch eine Öffnung weg; vor hellem
   Hintergrund (Loch kaum dunkler als Papier) zählt der geschlossene Lochrand.
4. Je zusammenhängender Fläche aus Fläche und Kaliber schätzen, wie viele Löcher darin
   stecken; die bekannte Schusszahl hilft beim Verteilen. Bei mehreren Löchern Kreise mit
   bekanntem Durchmesser einpassen.
5. „Bitte prüfen“, wenn die Schusszahl nicht passt, eine Fläche nicht eindeutig ist, drei
   oder mehr Löcher ineinander liegen, ein Treffer nah an einer Ringlinie liegt oder der
   Spiegel unsicher erkannt wurde.

Das Ergebnis ist immer ein Vorschlag, den ein Mensch bestätigt; nie amtlich. Fotos werden
nur im Speicher verarbeitet und nicht abgelegt.
"""

from __future__ import annotations

import io
import math

import cv2
import numpy as np
from PIL import Image

from .. import targets
from .benchmark import Detection

PX_PER_MM = 12.0
MAX_SIDE = 1600
ITERATIONS = 10


class DetectError(ValueError):
    """Foto lässt sich nicht auswerten (Text für die Oberfläche)."""


MAX_PIXELS = 60_000_000  # größer ist kein Handyfoto, sondern ein Versuch, Speicher zu füllen


def _decode(image: bytes) -> np.ndarray:
    # Größe vorab aus dem Dateikopf, ohne das Bild zu entpacken
    try:
        with Image.open(io.BytesIO(image)) as probe:
            w, h = probe.size
    except (OSError, ValueError) as exc:
        raise DetectError("Das Bild lässt sich nicht lesen.") from exc
    if w * h > MAX_PIXELS:
        raise DetectError("Das Bild ist zu groß.")
    arr = np.frombuffer(image, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise DetectError("Das Bild lässt sich nicht lesen.")
    h, w = img.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


Ellipse = tuple[tuple[float, float], tuple[float, float], float, float]


def find_blacks(gray: np.ndarray, count: int = 1) -> list[Ellipse]:
    """Spiegel als Ellipsen: (Mitte, Achsen, Winkel, Güte 0–1), bis zu ``count`` Stück.

    Mehrere Schwellen, weil Tisch und Schatten auch dunkel sein können; gewählt werden die
    rundesten, gut gefüllten dunklen Flächen (Löcher am Rand stören dank konvexer Hülle
    kaum). Bei mehreren Spiegeln (Fünf-Spiegel-Karte) nur gleich große, die sich nicht
    überdecken; Reihenfolge wie beim Lesen (Zeilen von oben, darin von links)."""
    blur = cv2.GaussianBlur(gray, (0, 0), 3)
    otsu, _ = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    low = float(np.percentile(blur, 1))
    h, w = gray.shape
    found: list[tuple[float, Ellipse]] = []
    min_area = 0.002 * h * w / max(1, count)
    for share in (0.25, 0.4, 0.55, 0.7, 0.85):
        level = low + (otsu - low) * share
        dark = (blur < level).astype(np.uint8) * 255
        dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        for c in contours:
            area = cv2.contourArea(c)
            if area < min_area or len(c) < 20:
                continue
            hull = cv2.convexHull(c)
            if len(hull) < 5:
                continue
            hull_area = cv2.contourArea(hull)
            (cx, cy), (a, b), ang = cv2.fitEllipse(hull)
            ellipse_area = math.pi * a * b / 4
            if hull_area <= 0 or ellipse_area <= 0:
                continue
            fit = min(hull_area, ellipse_area) / max(hull_area, ellipse_area)
            solid = area / hull_area
            ratio = min(a, b) / max(a, b)
            if cx < 0.05 * w or cx > 0.95 * w or cy < 0.05 * h or cy > 0.95 * h:
                continue
            if max(a, b) > 0.95 * min(h, w) or ratio < 0.5:
                continue
            quality = fit * solid * ratio
            score = quality**4 * math.sqrt(area)
            found.append((score, ((cx, cy), (a, b), ang, quality)))
    found.sort(key=lambda f: f[0], reverse=True)
    if not found or found[0][1][3] < 0.5:
        raise DetectError("Kein Spiegel gefunden. Bitte die ganze Scheibe gerade fotografieren.")
    best = found[0][1]
    size = math.sqrt(best[1][0] * best[1][1])
    chosen: list[Ellipse] = [best]
    for _, e in found[1:]:
        if len(chosen) >= count:
            break
        if e[3] < 0.5 or abs(math.sqrt(e[1][0] * e[1][1]) / size - 1) > 0.3:
            continue
        if any(math.dist(e[0], o[0]) < size for o in chosen):
            continue  # derselbe Spiegel bei anderer Schwelle oder überlappend
        chosen.append(e)
    # Lesereihenfolge: Zeilen (Mitten näher als ein halber Spiegel gelten als eine Zeile)
    chosen.sort(key=lambda e: e[0][1])
    rows: list[list[Ellipse]] = []
    for e in chosen:
        if rows and abs(e[0][1] - rows[-1][0][0][1]) < size / 2:
            rows[-1].append(e)
        else:
            rows.append([e])
    return [e for row in rows for e in sorted(row, key=lambda e: e[0][0])]


def find_black(gray: np.ndarray) -> Ellipse:
    return find_blacks(gray, 1)[0]


def _normalize(img, t: targets.Target, ellipse: Ellipse | None = None):
    """Entzerrtes Graubild, Mitte in der Bildmitte, ``PX_PER_MM`` je mm.

    Zuerst grob über die Ellipse des Spiegels, dann genauer: Spiegelrand und Ringlinien
    entlang von Strahlen suchen und daraus die volle Abbildung (Schräge, Lichtverlauf
    verschiebt sonst die Mitte) schätzen. Zurück: Bild, Güte, Spiegelradius (mm), Abbildung
    Foto → entzerrt (3×3)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    center, (a, b), angle, quality = ellipse or find_black(gray)
    black_r = (t.black_diameter or t.ring_diameter(t.lowest)) / 2
    radius_mm = t.outer_diameter / 2 + 2 * t.caliber
    size = int(2 * radius_mm * PX_PER_MM)
    # Ellipse → Kreis: drehen, Achsen auf den echten Radius strecken, zurückdrehen
    th = math.radians(angle)
    rot = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
    sx = black_r * PX_PER_MM / (a / 2)
    sy = black_r * PX_PER_MM / (b / 2)
    m = rot @ np.diag([sx, sy]) @ rot.T
    offset = np.array([size / 2, size / 2]) - m @ np.array(center)
    h = np.vstack([np.hstack([m, offset.reshape(2, 1)]), [0, 0, 1]])
    for _ in range(ITERATIONS):
        norm = cv2.warpPerspective(gray, h, (size, size), flags=cv2.INTER_LINEAR, borderValue=255)
        found, model = _circle_points(norm, t, black_r)
        if len(found) < 40:
            break
        inv = np.linalg.inv(h)
        photo = cv2.perspectiveTransform(found.reshape(-1, 1, 2), inv).reshape(-1, 2)
        # Ausreißer (Löcher, Ziffern, falsche Linie) über ihre Abweichung im Foto entfernen,
        # dann kleinste Quadrate; RANSAC wählt bei vielen guten Punkten sonst leicht eine
        # Teilmenge, die nur einen Bereich gut trifft. Jeder Durchlauf misst nur quer zu den
        # Kreisen und kommt der Lösung deshalb schrittweise näher.
        keep = np.ones(len(found), dtype=bool)
        hm = None
        for _ in range(3):
            hm, _ = cv2.findHomography(model[keep], photo[keep], 0)
            if hm is None:
                break
            back = cv2.perspectiveTransform(model.reshape(-1, 1, 2), hm).reshape(-1, 2)
            err = np.linalg.norm(back - photo, axis=1)
            limit = max(3 * float(np.median(err[keep])), 0.3)
            keep = err < limit
            if keep.sum() < 30:
                hm = None
                break
        if hm is None:
            break
        h = np.linalg.inv(hm)
    norm = cv2.warpPerspective(gray, h, (size, size), flags=cv2.INTER_LINEAR, borderValue=255)
    return norm, quality, black_r, h


def _circle_points(norm: np.ndarray, t: targets.Target, black_r: float):
    """Punkte auf Spiegelrand und Ringlinien im entzerrten Bild suchen.

    Zurück: gefundene Punkte und dieselben Punkte auf dem Sollkreis (gleicher Winkel), je als
    N×2 in Bildpunkten. Ein gestörtes Profil (Loch, Ziffer) wird übergangen oder fällt beim
    Schätzen als Ausreißer heraus."""
    c = norm.shape[0] / 2
    has_black = bool(t.black_diameter)
    circles: list[tuple[float, str]] = []
    if has_black:
        circles.append((black_r, "rand"))
    for ring in range(t.lowest, t.top + 1):
        r = t.ring_diameter(ring) / 2
        if r < 1.5 or (has_black and abs(r - black_r) < 0.3):
            continue
        circles.append((r, "hell" if has_black and r < black_r else "dunkel"))
    angles = np.radians(np.arange(0, 360, 2.5))
    span = t.ring_width * 0.35
    steps = np.linspace(-span, span, int(2 * span * PX_PER_MM * 4) + 1)
    img = cv2.GaussianBlur(norm, (0, 0), 1.0).astype(np.float32)
    found, model = [], []
    for r, kind in circles:
        rr = (r + steps)[None, :] * PX_PER_MM
        xs = (c + rr * np.cos(angles)[:, None]).astype(np.float32)
        ys = (c - rr * np.sin(angles)[:, None]).astype(np.float32)
        prof = cv2.remap(img, xs, ys, cv2.INTER_LINEAR, borderValue=255)
        if kind == "rand":
            grad = np.gradient(prof, axis=1)  # innen dunkel, außen hell
            idx = grad.argmax(axis=1)
            strength = grad.max(axis=1) * 4 * PX_PER_MM / 255  # Anstieg je mm, grob
            ok = strength > 0.5
        else:
            sign = 1 if kind == "hell" else -1
            val = prof * sign
            idx = val.argmax(axis=1)
            peak = val.max(axis=1)
            base = np.median(val, axis=1)
            ok = (peak - base) > 20
        # Spitze nicht am Rand des Suchfensters (dann liegt die Linie woanders)
        ok &= (idx > 2) & (idx < len(steps) - 3)
        for k in np.nonzero(ok)[0]:
            j = int(idx[k])
            # Feinlage per Parabel durch die drei Werte um die Spitze
            y0, y1, y2 = (grad if kind == "rand" else val)[k, j - 1 : j + 2]
            den = y0 - 2 * y1 + y2
            frac = 0.5 * (y0 - y2) / den if den else 0.0
            dist = (r + steps[j] + frac * (steps[1] - steps[0])) * PX_PER_MM
            a = angles[k]
            found.append((c + dist * math.cos(a), c - dist * math.sin(a)))
            model.append((c + r * PX_PER_MM * math.cos(a), c - r * PX_PER_MM * math.sin(a)))
    return np.array(found, dtype=np.float32), np.array(model, dtype=np.float32)


def _level(img: np.ndarray, region: np.ndarray, k: int) -> np.ndarray:
    """Örtliche Helligkeit einer Fläche (gleitender Mittelwert nur über die Fläche)."""
    m = region.astype(np.float32)
    num = cv2.blur(img * m, (k, k))
    den = cv2.blur(m, (k, k))
    return num / np.maximum(den, 1e-3)


def _fill_rims(
    mask: np.ndarray, hole_px: float, ring_radii_px: list[float], black_px: float
) -> np.ndarray:
    """Geschlossene Ränder in Lochgröße füllen.

    Vor hellem Hintergrund ist ein Loch im weißen Papier kaum dunkler als das Papier; dann
    fällt nur der ausgefranste Rand auf. Umschließt ein Rand eine Fläche von etwa ein bis
    sechs Löchern, gilt die ganze Fläche als Loch. Ringlinien umschließen viel mehr, Ziffern
    viel weniger."""
    c = max(3, int(hole_px * 0.12)) | 1
    closed = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (c, c))
    )
    contours, hierarchy = cv2.findContours(closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hierarchy is None:
        return mask
    one = math.pi * (hole_px / 2) ** 2
    out = mask.copy()
    for i, h in enumerate(hierarchy[0]):
        if h[3] < 0:  # nur Innenränder (Flächen, die von einem Rand umschlossen sind)
            continue
        area = cv2.contourArea(contours[i])
        if not 0.3 * one <= area <= 6 * one:
            continue
        pts = contours[i][:, 0, :].astype(np.float32)
        rad = np.hypot(pts[:, 0] - mask.shape[1] / 2, pts[:, 1] - mask.shape[0] / 2)
        if rad.mean() < black_px:
            continue  # im Spiegel sind Löcher ohnehin flächig sichtbar
        if rad.std() < hole_px * 0.06 and any(
            abs(rad.mean() - r) < hole_px * 0.1 for r in ring_radii_px
        ):
            continue  # ein Ring der Scheibe, kein Loch
        per = cv2.arcLength(contours[i], True)
        if per and 4 * math.pi * area / (per * per) < 0.4:
            continue  # zu zerklüftet für ein Loch
        cv2.drawContours(out, contours, i, 255, thickness=cv2.FILLED)
        cv2.drawContours(out, contours, i, 255, thickness=c)
    return out


def hole_mask(norm: np.ndarray, t: targets.Target, black_r: float) -> np.ndarray:
    """Flächen, die wie Löcher aussehen (255), im entzerrten Bild.

    Vergleich mit der erwarteten Scheibe: im Spiegel dunkel, außen hell, jeweils mit der
    örtlichen Helligkeit (Lichtverlauf, Schatten). Was deutlich abweicht und dicker als
    Ringlinien und Zahlen ist, ist ein Loch."""
    img = cv2.GaussianBlur(norm, (0, 0), PX_PER_MM * 0.1).astype(np.float32)
    size = norm.shape[0]
    yy, xx = np.mgrid[0:size, 0:size]
    r_mm = np.hypot(xx - size / 2, yy - size / 2) / PX_PER_MM
    outer = t.outer_diameter / 2 + t.caliber * 1.2
    has_black = bool(t.black_diameter)
    inside = r_mm < black_r if has_black else np.zeros_like(r_mm, dtype=bool)
    outside = (r_mm >= black_r if has_black else r_mm >= 0) & (r_mm < outer)
    k = int(t.caliber * PX_PER_MM * 3) | 1
    levels = []
    score = np.zeros_like(img)
    for region in (inside, outside):
        if region.any():
            levels.append(float(np.median(img[region])))
    contrast = abs(levels[0] - levels[-1]) if len(levels) == 2 else 200.0
    for region in (inside, outside):
        if not region.any():
            continue
        # örtliche Helligkeit nur aus ruhigen Punkten: Ringlinien, Zahlen und Löcher
        # schrittweise herausnehmen, sonst ziehen sie den Mittelwert mit
        calm = region
        for _ in range(4):
            lv = _level(img, calm, k)
            dev = np.abs(img - lv)
            mad = float(np.median(dev[calm])) if calm.any() else 0.0
            calm = region & (dev < max(3 * mad, 4.0))
        # Schwelle je Bereich: deutlich über dem Rauschen, mindestens 6 % des Unterschieds
        # Spiegel/Papier (Löcher im Spiegel auf dunkler Unterlage sind oft nur dunkelgrau)
        thr = max(0.06 * contrast, 6 * mad, 10.0)
        score[region] = dev[region] / thr
    # Den Spiegelrand nicht ausblenden: ein Loch auf dem Rand zerfiele sonst in zwei schmale
    # Sicheln, die das Öffnen entfernt. Ein schmaler Streifen durch eine knapp verschobene
    # Randlage verschwindet beim Öffnen ohnehin.
    mask = (score > 1).astype(np.uint8) * 255
    hole_px = t.caliber * PX_PER_MM
    radii = [t.ring_diameter(r) / 2 * PX_PER_MM for r in range(t.lowest, t.top + 1)]
    if t.inner_diameter:
        radii.append(t.inner_diameter / 2 * PX_PER_MM)
    mask = _fill_rims(mask, hole_px, radii, black_r * PX_PER_MM if has_black else 0.0)
    o = int(hole_px * 0.35) | 1
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (o, o))
    )
    c = int(PX_PER_MM * 1.0) | 1
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (c, c))
    )
    return mask


def _fit_circles(blob: np.ndarray, centers: np.ndarray, r_px: float) -> np.ndarray:
    """Mitten von ``k`` gleich großen Kreisen so verschieben, dass ihre Vereinigung die
    Fläche ``blob`` (bool, Ausschnitt) möglichst genau deckt (zu viel + zu wenig)."""
    h, w = blob.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r2 = r_px * r_px

    def disk(c):
        return (xx - c[0]) ** 2 + (yy - c[1]) ** 2 <= r2

    disks = [disk(c) for c in centers]

    def cost(ds):
        union = np.logical_or.reduce(ds)
        return int(np.count_nonzero(union ^ blob))

    best = cost(disks)
    dirs = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
    for step in (r_px * 0.3, r_px * 0.12, r_px * 0.05, r_px * 0.02):
        for _ in range(6):
            improved = False
            for j in range(len(centers)):
                for dx, dy in dirs:
                    cand = centers[j] + np.array([dx * step, dy * step], dtype=np.float32)
                    trial = disks.copy()
                    trial[j] = disk(cand)
                    c = cost(trial)
                    if c < best:
                        best, centers[j], disks = c, cand, trial
                        improved = True
            if not improved:
                break
    return centers


def _split(points: np.ndarray, k: int, r_px: float) -> list[tuple[float, float]]:
    """``k`` Kreise in eine Fläche einpassen (Punkte als N×2, x/y)."""
    if k <= 1:
        cx, cy = points.mean(axis=0)
        return [(float(cx), float(cy))]
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.1)
    _, _, centers = cv2.kmeans(
        points.astype(np.float32), k, None, criteria, 5, cv2.KMEANS_PP_CENTERS
    )
    # Nachbessern: jeder Kreis zur Mitte der Punkte, die in seinem Radius liegen
    for _ in range(8):
        d = np.linalg.norm(points[:, None, :] - centers[None, :, :], axis=2)
        for j in range(k):
            near = points[d[:, j] <= r_px]
            if len(near):
                centers[j] = near.mean(axis=0)
    return [(float(x), float(y)) for x, y in centers]


def _counts(areas: list[float], one: float, expected: int | None) -> tuple[list[int], bool]:
    """Löcher je Fläche schätzen; ``unsure``, wenn eine Fläche zwischen zwei Zahlen liegt."""
    raw = [a / one for a in areas]
    counts = [max(1, round(r)) for r in raw]
    unsure = any(0.3 < (r % 1) < 0.7 and r > 1 for r in raw)
    if expected and 0 < len(raw) <= expected:
        # bekannte Schusszahl: auf die Flächen nach Größe verteilen (jede mindestens 1).
        # Überlappende Löcher ergeben weniger Fläche als einzelne, darum nicht nur runden.
        counts = [1] * len(raw)
        for _ in range(expected - len(raw)):
            j = max(range(len(raw)), key=lambda i: raw[i] / counts[i])
            # nur, wenn dann noch jedes Loch fast eine halbe Lochfläche hat; sonst fehlt
            # eher ein Loch woanders (dann lieber zu wenige und „bitte prüfen“)
            if raw[j] / (counts[j] + 1) < 0.45:
                break
            counts[j] += 1
    return counts, unsure


def unsupported(t: targets.Target) -> str:
    """Grund, warum die Fotoerkennung diese Scheibe (noch) nicht kann; sonst leer."""
    return targets.photo_problem(t)


def detect(image: bytes, target: targets.Target | str, expected: int | None = None) -> Detection:
    """Treffer auf dem Foto; ``expected``: Schusszahl insgesamt (bei mehreren Spiegeln über
    alle zusammen, gleich verteilt)."""
    t = targets.BY_KEY.get(target) if isinstance(target, str) else target
    if t is None:
        raise DetectError("Unbekannte Scheibe.")
    reason = unsupported(t)
    if reason:
        raise DetectError(reason)
    img = _decode(image)
    if t.spots <= 1:
        hits, notes = _detect_spot(img, t, None, expected)
        return Detection(hits=hits, needs_review=bool(notes), note="; ".join(notes))

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ellipses = find_blacks(gray, t.spots)
    per_spot = expected // t.spots if expected and expected % t.spots == 0 else None
    hits: list[tuple[float, float]] = []
    spots: list[int] = []
    notes: list[str] = []
    if len(ellipses) < t.spots:
        notes.append(f"nur {len(ellipses)} von {t.spots} Spiegeln gefunden")
    # außerhalb des äußersten Rings liegt schon der Nachbarspiegel
    reach = t.outer_diameter / 2 + t.caliber / 2
    for n, ellipse in enumerate(ellipses, start=1):
        found, spot_notes = _detect_spot(img, t, ellipse, per_spot, first=len(hits) + 1)
        found = [h for h in found if math.hypot(*h) <= reach]
        hits += found
        spots += [n] * len(found)
        notes += [f"Spiegel {n}: {x}" for x in spot_notes]
    if expected is not None and len(hits) != expected and per_spot is None:
        notes.append(f"{len(hits)} statt {expected} Treffer gefunden")
    return Detection(hits=hits, needs_review=bool(notes), note="; ".join(notes), spots=spots)


def _detect_spot(
    img: np.ndarray,
    t: targets.Target,
    ellipse: Ellipse | None,
    expected: int | None,
    first: int = 1,
) -> tuple[list[tuple[float, float]], list[str]]:
    """Ein Spiegel: Treffer (mm um seine Mitte, von innen nach außen) und Prüfhinweise;
    ``first``: Nummer des ersten Schusses in den Hinweisen."""
    norm, quality, black_r, _ = _normalize(img, t, ellipse)
    mask = hole_mask(norm, t, black_r)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    r_px = t.caliber / 2 * PX_PER_MM
    one = math.pi * r_px * r_px
    comps = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= one * 0.3]
    areas = [float(stats[i, cv2.CC_STAT_AREA]) for i in comps]
    # Fläche eines Einzellochs aus dem Bild selbst (Maske ist je nach Licht etwas größer
    # oder kleiner als das Soll), wenn es mindestens zwei klare Einzellöcher gibt
    singles = [a for a in areas if 0.6 * one <= a <= 1.4 * one]
    if len(singles) >= 2:
        one = float(np.median(singles))
    counts, unsure = _counts(areas, one, expected)
    size = norm.shape[0]
    hits: list[tuple[float, float]] = []
    for i, k in zip(comps, counts, strict=True):
        ys, xs = np.nonzero(labels == i)
        pts = np.stack([xs, ys], axis=1).astype(np.float32)
        centers = np.array(_split(pts, k, r_px), dtype=np.float32)
        if k > 1:
            # Ausschnitt mit Rand, darin die Kreise genau einpassen
            x0, y0 = int(xs.min() - r_px), int(ys.min() - r_px)
            x0, y0 = max(x0, 0), max(y0, 0)
            x1, y1 = int(xs.max() + r_px) + 1, int(ys.max() + r_px) + 1
            blob = labels[y0:y1, x0:x1] == i
            centers = _fit_circles(blob, centers - [x0, y0], r_px) + [x0, y0]
        for x, y in centers:
            hits.append(
                (
                    round(float(x - size / 2) / PX_PER_MM, 3),
                    round(float(size / 2 - y) / PX_PER_MM, 3),
                )
            )
    # Reihenfolge wie im Antipp-Bild (von innen nach außen); die Hinweise nennen diese Nummern
    hits.sort(key=lambda p: math.hypot(*p))
    notes = []
    if expected is not None and len(hits) != expected:
        notes.append(f"{len(hits)} statt {expected} Treffer gefunden")
    if unsure:
        notes.append("überlappende Löcher, Anzahl unsicher")
    elif any(k >= 3 for k in counts):
        # drei und mehr Löcher in einer Fläche: Umriss lässt die Lage offen
        notes.append("mehrere Löcher ineinander, Lage bitte prüfen")
    if quality < 0.8:
        notes.append("Spiegel unsicher erkannt")
    edge = _near_ring_line(t, hits)
    if edge:
        numbers = ", ".join(str(i + first - 1) for i in edge)
        notes.append(f"Schuss {numbers} nah an einer Ringlinie")
    return hits, notes


def _near_ring_line(t: targets.Target, hits, tolerance_mm: float = 0.1) -> list[int]:
    """Treffer, deren Lochrand fast genau eine Ringlinie berührt (Lehre nötig)."""
    edge = t.top_diameter / 2 + t.caliber / 2
    out = []
    for i, (x, y) in enumerate(hits, start=1):
        d = math.hypot(x, y)
        steps = (d - edge) / t.ring_width
        if steps < 0:
            continue
        frac = steps - math.floor(steps)
        if min(frac, 1 - frac) * t.ring_width < tolerance_mm:
            out.append(i)
    return out
