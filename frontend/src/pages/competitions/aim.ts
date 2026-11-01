// Live-Kamera (Schießscheiben Schritt 5): ein kleines Graubild je Kamerabild prüfen und
// sagen, ob die Scheibe gut im Bild ist. Nur grob und schnell (etwa 160 Bildpunkte breit);
// die genaue Auswertung macht danach der Server mit dem vollen Foto.

export interface Spot {
  /** Mitte des Spiegels, 0–1 je Achse */
  cx: number
  cy: number
  /** Durchmesser des Spiegels im Verhältnis zur kürzeren Bildseite */
  size: number
  /** kleine / große Achse: 1 = Kamera genau senkrecht über der Scheibe */
  round: number
}

export interface Frame {
  spot: Spot | null
  /** mittlere Helligkeit 0–255 */
  light: number
  /** Schärfe (mittlerer Betrag des Laplace-Filters); höher ist schärfer */
  sharp: number
}

/** RGBA-Bild in ein Graubild umrechnen. */
export function toGray(rgba: Uint8ClampedArray, w: number, h: number): Uint8Array {
  const out = new Uint8Array(w * h)
  for (let i = 0, j = 0; j < out.length; i += 4, j++) {
    out[j] = (rgba[i] * 77 + rgba[i + 1] * 150 + rgba[i + 2] * 29) >> 8
  }
  return out
}

function otsu(gray: Uint8Array): number {
  const hist = new Array<number>(256).fill(0)
  for (const v of gray) hist[v]++
  const total = gray.length
  let sum = 0
  for (let i = 0; i < 256; i++) sum += i * hist[i]
  let sumB = 0
  let wB = 0
  let best = 0
  let level = 127
  for (let tm = 0; tm < 256; tm++) {
    wB += hist[tm]
    if (!wB) continue
    const wF = total - wB
    if (!wF) break
    sumB += tm * hist[tm]
    const mB = sumB / wB
    const mF = (sum - sumB) / wF
    const between = wB * wF * (mB - mF) ** 2
    if (between > best) {
      best = between
      level = tm
    }
  }
  return level
}

/** Dunkelste runde Fläche, die nicht am Bildrand liegt: der Spiegel. */
export function findSpot(gray: Uint8Array, w: number, h: number): Spot | null {
  const level = otsu(gray)
  const seen = new Uint8Array(w * h)
  const stack = new Int32Array(w * h)
  let best: (Spot & { score: number }) | null = null
  for (let start = 0; start < w * h; start++) {
    if (seen[start] || gray[start] >= level) continue
    // Fläche füllen und dabei die Momente sammeln
    let n = 0
    let sx = 0
    let sy = 0
    let sxx = 0
    let syy = 0
    let sxy = 0
    let edge = false
    let top = 0
    stack[top++] = start
    seen[start] = 1
    while (top) {
      const p = stack[--top]
      const x = p % w
      const y = (p - x) / w
      n++
      sx += x
      sy += y
      sxx += x * x
      syy += y * y
      sxy += x * y
      if (x === 0 || y === 0 || x === w - 1 || y === h - 1) edge = true
      const next = [p - 1, p + 1, p - w, p + w]
      for (let k = 0; k < 4; k++) {
        const q = next[k]
        if (q < 0 || q >= w * h || seen[q] || gray[q] >= level) continue
        if (k < 2 && Math.abs((q % w) - x) !== 1) continue // nicht über den Zeilenrand
        seen[q] = 1
        stack[top++] = q
      }
    }
    if (edge || n < 0.01 * w * h) continue
    const mx = sx / n
    const my = sy / n
    const cxx = sxx / n - mx * mx
    const cyy = syy / n - my * my
    const cxy = sxy / n - mx * my
    // Achsen der Ellipse mit gleichen Momenten
    const tr = cxx + cyy
    const det = cxx * cyy - cxy * cxy
    const disc = Math.sqrt(Math.max(0, (tr * tr) / 4 - det))
    const l1 = tr / 2 + disc
    const l2 = tr / 2 - disc
    if (l2 <= 0) continue
    const a = 2 * Math.sqrt(l1)
    const b = 2 * Math.sqrt(l2)
    const fill = n / (Math.PI * a * b) // 1 für eine volle Ellipse
    const round = b / a
    if (fill < 0.75 || fill > 1.25 || round < 0.5) continue
    const score = n * round
    if (!best || score > best.score) {
      best = {
        cx: mx / w,
        cy: my / h,
        size: (2 * Math.sqrt(a * b)) / Math.min(w, h),
        round,
        score,
      }
    }
  }
  if (!best) return null
  const { score: _score, ...spot } = best
  void _score
  return spot
}

/** Schärfe: mittlerer Betrag des Laplace-Filters (Kanten scharf = groß). */
export function sharpness(gray: Uint8Array, w: number, h: number): number {
  let sum = 0
  let n = 0
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x
      sum += Math.abs(4 * gray[i] - gray[i - 1] - gray[i + 1] - gray[i - w] - gray[i + w])
      n++
    }
  }
  return n ? sum / n : 0
}

/** Weichzeichnen (zweimal 3×3-Mittel), damit helle Ringlinien im Spiegel ihn nicht zerteilen. */
export function soften(gray: Uint8Array, w: number, h: number): Uint8Array {
  let src = gray
  for (let pass = 0; pass < 2; pass++) {
    const out = new Uint8Array(w * h)
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        let sum = 0
        let n = 0
        for (let dy = -1; dy <= 1; dy++) {
          const yy = y + dy
          if (yy < 0 || yy >= h) continue
          for (let dx = -1; dx <= 1; dx++) {
            const xx = x + dx
            if (xx < 0 || xx >= w) continue
            sum += src[yy * w + xx]
            n++
          }
        }
        out[y * w + x] = sum / n
      }
    }
    src = out
  }
  return src
}

export function analyze(gray: Uint8Array, w: number, h: number): Frame {
  let light = 0
  for (const v of gray) light += v
  return {
    spot: findSpot(soften(gray, w, h), w, h),
    light: gray.length ? light / gray.length : 0,
    sharp: sharpness(gray, w, h),
  }
}

export interface Aim {
  ok: boolean
  hint: string
}

/**
 * Ist das Bild gut genug zum Auslösen? ``blackShare``: Durchmesser des Spiegels geteilt
 * durch den äußersten Ring (die ganze Scheibe soll ins Bild, aber möglichst groß).
 */
export function judge(f: Frame, blackShare: number, prev?: Frame | null): Aim {
  if (f.light < 50) return { ok: false, hint: 'Zu dunkel – bitte mehr Licht.' }
  const s = f.spot
  if (!s) return { ok: false, hint: 'Scheibe nicht gefunden – den Spiegel ins Bild halten.' }
  const whole = s.size / blackShare // äußerster Ring im Verhältnis zur kürzeren Bildseite
  if (whole > 0.95) return { ok: false, hint: 'Etwas weiter weg – die ganze Scheibe ins Bild.' }
  if (whole < 0.6) return { ok: false, hint: 'Näher heran.' }
  if (Math.hypot(s.cx - 0.5, s.cy - 0.5) > 0.12) {
    return { ok: false, hint: 'Scheibe in die Mitte des Bildes.' }
  }
  if (s.round < 0.93) return { ok: false, hint: 'Gerade von oben halten, nicht schräg.' }
  if (prev?.spot) {
    const moved = Math.hypot(s.cx - prev.spot.cx, s.cy - prev.spot.cy)
    if (moved > 0.01 || Math.abs(s.size - prev.spot.size) > 0.02) {
      return { ok: false, hint: 'Ruhig halten …' }
    }
  }
  if (f.sharp < 2) return { ok: false, hint: 'Unscharf – ruhig halten.' }
  return { ok: true, hint: 'Gut so – gleich wird ausgelöst.' }
}

/** Kann der Browser die Kamera live zeigen (nur über HTTPS bzw. localhost)? */
export function cameraAvailable(): boolean {
  return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia
}
