// Farben und Rechenhilfen der Diagramme.

/** Feste Reihenfolge für Kategorien (farbfehlsichtigkeitsgeprüft), nie zyklisch. */
// Alle Farben mit mindestens 3 : 1 gegen Weiß (WCAG 1.4.11, UX-Audit 31.10. C04)
export const PALETTE = ['#2a78d6', '#d4561f', '#0f8a5f', '#a86f00', '#c8457a', '#008300', '#6250d6']
/** Weitere Farben, wenn alle Reihen einzeln gezeigt werden (danach wiederholt). */
export const PALETTE_MORE = [
  '#8c4a1f',
  '#0e7c86',
  '#a3238f',
  '#6b8e00',
  '#b3261e',
  '#3a3f9e',
  '#c26d00',
  '#5a8f7b',
]
export const REST_COLOR = '#6f7773'
export const PINNED_COLOR = '#4b5451'
export const PRIMARY = 'var(--color-primary)'
export const INCOME = 'var(--color-success)'
export const EXPENSE = 'var(--color-error)'
/** Vorjahr: grau, zusätzlich gestrichelt (nicht nur an der Farbe erkennbar) */
export const PREVIOUS = '#7a817e'

export interface Series {
  key: string
  name: string
  color: string
  values: (number | null)[]
}

/** Mehr als sieben Reihen: die kleinsten zu „Weitere“ zusammenfassen. */
export function foldSeries(
  items: { key: string; name: string; values: number[] }[],
  max = PALETTE.length,
  /** Reihe, die nie zusammengefasst wird und neutral gefärbt ist (z. B. „ohne Abteilung“) */
  pinned?: string,
): Series[] {
  const pin = items.find((s) => s.key === pinned)
  if (pin) {
    const others = foldSeries(
      items.filter((s) => s !== pin),
      max - 1,
    )
    return [...others, { ...pin, color: PINNED_COLOR }]
  }
  const peak = (v: number[]) => Math.max(0, ...v)
  let kept = items
  let rest: typeof items = []
  if (items.length > max) {
    const ranked = [...items].sort((a, b) => peak(b.values) - peak(a.values))
    const keep = new Set(ranked.slice(0, max - 1).map((s) => s.key))
    kept = items.filter((s) => keep.has(s.key))
    rest = items.filter((s) => !keep.has(s.key))
  }
  const out: Series[] = kept.map((s, i) => ({ ...s, color: PALETTE[i] }))
  if (rest.length > 0)
    out.push({
      key: 'weitere',
      name: `Weitere (${rest.length})`,
      color: REST_COLOR,
      values: rest[0].values.map((_, i) => rest.reduce((sum, s) => sum + (s.values[i] ?? 0), 0)),
    })
  return out
}

/** Alle Reihen einzeln, jede mit eigener Farbe; „pinned“ steht zuletzt und ist neutral. */
export function allSeries(
  items: { key: string; name: string; values: number[] }[],
  pinned?: string,
): Series[] {
  const colors = [...PALETTE, ...PALETTE_MORE]
  const rest = items.filter((s) => s.key !== pinned)
  const pin = items.filter((s) => s.key === pinned)
  return [
    ...rest.map((s, i) => ({ ...s, color: colors[i % colors.length] })),
    ...pin.map((s) => ({ ...s, color: PINNED_COLOR })),
  ]
}

/** Runde Achsenschritte, die 0 einschließen. */
export function niceTicks(min: number, max: number, count = 4, zero = true): number[] {
  let lo = zero ? Math.min(0, min) : min
  let hi = zero ? Math.max(0, max) : max
  if (!zero) {
    // Ausschnitt mindestens 20 % des Werts hoch, damit kleine Schwankungen nicht dramatisch wirken
    const span = Math.max(hi - lo, Math.max(Math.abs(lo), Math.abs(hi)) * 0.2, 1)
    const mid = (lo + hi) / 2
    lo = Math.min(lo, mid - span / 2)
    hi = Math.max(hi, mid + span / 2)
    if (min >= 0 && lo < 0) lo = 0
  }
  if (lo === hi) return lo < 0 ? [lo, 0] : [0, Math.max(1, hi)]
  const raw = (hi - lo) / count
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw
  const ticks: number[] = []
  for (let tm = Math.floor(lo / step) * step; tm < hi + step * 0.999; tm += step) {
    ticks.push(Math.round(tm * 1e6) / 1e6)
    if (tm >= hi) break
  }
  return ticks
}
