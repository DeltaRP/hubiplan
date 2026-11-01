// Wertung eines Treffers aus dem Trefferpunkt, wie im Backend (competitions/targets.py):
// Grenze g = Radius höchster Ring + Kaliber/2, Wert = höchster Ring + (g − d)/Ringbreite,
// Zehntel abgeschnitten (höchstens x,9), Ring abgeschnitten, unter dem niedrigsten Ring 0.
// Der Server rechnet beim Abgleich selbst nach; hier nur für die laufende Summe am Stand.
import type { ScoringMethod, TargetInfo } from '../../api/competitions.ts'

export interface ShotScore {
  ring: number
  /** Zehntelwert in Zehnteln (z. B. 106 für 10,6) */
  tenths: number
  inner: boolean
  /** Abstand zur Mitte in mm */
  distance: number
  /** Teiler in Zehnteln (1/100 mm mal Faktor, eine Nachkommastelle) */
  teilerTenths: number
}

export function scoreShot(tm: TargetInfo, x: number, y: number): ShotScore {
  const d = Math.hypot(x, y)
  const edge = tm.top_diameter / 2 + tm.caliber / 2
  const raw = tm.top + (edge - d) / tm.ring_width
  // auf sechs Stellen runden (Gleitkomma), dann auf Zehntel abschneiden
  const micro = Math.round(raw * 1e6)
  let tenths = Math.min(Math.trunc(micro / 1e5), tm.top * 10 + 9)
  let ring = Math.min(Math.trunc(tenths / 10), tm.top)
  if (ring < tm.lowest) {
    ring = 0
    tenths = 0
  }
  let inner = false
  if (tm.inner_diameter && ring === tm.top) {
    const rIn = tm.inner_diameter / 2
    const rCal = tm.caliber / 2
    const limit = tm.inner_mode === 'wegschiessen' ? rCal - rIn : rIn + rCal
    inner = d <= limit + 1e-9
  }
  const teilerTenths = Math.round(d * 100 * tm.teiler_factor * 10)
  return { ring, tenths, inner, distance: d, teilerTenths }
}

/** Messwert eines Schusses in Zehnteln (Ringe: Ring · 10). */
export function measure(method: ScoringMethod, s: ShotScore): number {
  if (method === 'zehntel') return s.tenths
  if (method === 'teiler') return s.teilerTenths
  return s.ring * 10
}

/** Indizes der Schüsse, die zählen: beste ``counted`` (Teiler: kleinste, Standard 1). */
export function countedIndexes(
  method: ScoringMethod,
  shots: ShotScore[],
  counted: number | null,
): Set<number> {
  const lower = method === 'teiler'
  const k = lower ? counted || 1 : counted || shots.length
  const order = shots
    .map((s, i) => ({ i, v: measure(method, s) }))
    .sort((a, b) => (lower ? a.v - b.v : b.v - a.v) || a.i - b.i)
  return new Set(order.slice(0, k).map((o) => o.i))
}

/** Wert des Starters als Text mit Punkt (wie der Server ihn speichert), leer ohne Schüsse. */
export function totalText(
  method: ScoringMethod,
  shots: ShotScore[],
  counted: number | null,
): string {
  if (!shots.length) return ''
  const keep = countedIndexes(method === 'frei' ? 'ringe' : method, shots, counted)
  let sum = 0
  shots.forEach((s, i) => {
    if (keep.has(i)) sum += measure(method === 'frei' ? 'ringe' : method, s)
  })
  return method === 'ringe' || method === 'frei' ? String(sum / 10) : (sum / 10).toFixed(1)
}

function fmt(n: number): string {
  return n.toFixed(1).replace('.', ',')
}

/** Anzeige eines Schusses: Ring, Zehntel oder Teiler. */
export function shotLabel(method: ScoringMethod, s: ShotScore): string {
  if (method === 'zehntel') return fmt(s.tenths / 10)
  if (method === 'teiler') return fmt(s.teilerTenths / 10)
  return String(s.ring)
}
