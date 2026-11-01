// Schießscheiben Schritt 5: Bildprüfung der Live-Kamera an gezeichneten (erfundenen) Bildern.
import { describe, expect, it } from 'vitest'
import { analyze, judge } from '../pages/competitions/aim.ts'

const W = 160
const H = 120

/** Graubild: Tisch, weißes Papier, schwarzer Spiegel mit hellen Ringlinien und Löchern. */
function scene({
  cx = 80,
  cy = 60,
  r = 28,
  squash = 1,
  light = 1,
  holes = [] as [number, number][],
} = {}): Uint8Array {
  const g = new Uint8Array(W * H)
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const dx = x - cx
      const dy = (y - cy) / squash
      const d = Math.hypot(dx, dy)
      let v = 110 // Tisch
      if (Math.abs(x - cx) < 58 && Math.abs(y - cy) < 58 * squash) v = 235 // Papier
      if (d < r) {
        v = 25
        // helle Ringlinien im Spiegel (dünn)
        for (const rr of [r * 0.3, r * 0.5, r * 0.7, r * 0.9]) {
          if (Math.abs(d - rr) < 0.5) v = 200
        }
      }
      for (const [hx, hy] of holes) if (Math.hypot(x - hx, y - hy) < 3) v = 180
      g[y * W + x] = Math.min(255, v * light + ((x * 7 + y * 13) % 5))
    }
  }
  return g
}

describe('Live-Kamera: Lage der Scheibe prüfen', () => {
  // LG DSB: Spiegel 30,5 mm, äußerster Ring 45,5 mm
  const share = 30.5 / 45.5

  it('findet den Spiegel trotz Ringlinien und Löchern', () => {
    const f = analyze(
      scene({
        holes: [
          [85, 55],
          [70, 62],
        ],
      }),
      W,
      H,
    )
    expect(f.spot).not.toBeNull()
    expect(f.spot!.cx).toBeCloseTo(0.5, 1)
    expect(f.spot!.cy).toBeCloseTo(0.5, 1)
    expect(f.spot!.round).toBeGreaterThan(0.93)
    // 56 px Durchmesser auf 120 px Höhe
    expect(f.spot!.size).toBeGreaterThan(0.42)
    expect(f.spot!.size).toBeLessThan(0.52)
  })

  it('löst nur aus, wenn alles passt und das Bild ruhig ist', () => {
    const good = analyze(scene(), W, H)
    expect(judge(good, share, good)).toMatchObject({ ok: true })
    // gleiche Lage, kein vorheriges Bild: auch gut
    expect(judge(good, share).ok).toBe(true)
  })

  it('gibt Hinweise, was zu ändern ist', () => {
    const hint = (opts: Parameters<typeof scene>[0], prev?: Parameters<typeof scene>[0]) =>
      judge(analyze(scene(opts), W, H), share, prev ? analyze(scene(prev), W, H) : null).hint
    expect(hint({ r: 14 })).toMatch(/Näher heran/)
    expect(hint({ r: 40, cy: 60 })).toMatch(/weiter weg/)
    expect(hint({ cx: 55 })).toMatch(/Mitte/)
    expect(hint({ squash: 0.8 })).toMatch(/Gerade von oben/)
    expect(hint({ light: 0.15 })).toMatch(/Zu dunkel/)
    expect(hint({}, { cx: 84 })).toMatch(/Ruhig halten/)
    // nur Papier, kein Spiegel
    expect(hint({ r: 0 })).toMatch(/nicht gefunden/)
  })
})
