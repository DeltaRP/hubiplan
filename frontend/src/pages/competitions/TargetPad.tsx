// Treffer auf einem Scheibenbild antippen (Schießscheiben Schritt 2). Die Scheibe wird aus
// ihren Maßen gezeichnet (mm, Mitte 0/0, y nach oben). Antippen setzt einen Treffer,
// Ziehen verschiebt ihn; beim Ziehen zeigt eine Lupe die Umgebung vergrößert. Tastatur:
// Treffer wählen, Pfeiltasten verschieben (0,1 mm, mit Umschalt 1 mm), Entf löscht.
import { useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent } from 'react'
import type { ScoringMethod, TargetInfo } from '../../api/competitions.ts'
import { countedIndexes, scoreShot, shotLabel, totalText } from './targetMath.ts'

export interface PadHit {
  x: number
  y: number
  spot?: number | null
}

const ZOOMS = [
  { key: 'ganz', label: 'Ganze Scheibe' },
  { key: 'spiegel', label: 'Spiegel' },
  { key: 'mitte', label: 'Mitte' },
] as const

type Zoom = (typeof ZOOMS)[number]['key']

function viewRadius(t: TargetInfo, zoom: Zoom): number {
  const outer = (t.rings[0]?.diameter ?? t.top_diameter) / 2
  if (zoom === 'ganz') return outer * 1.08
  if (zoom === 'spiegel') return Math.min(outer, (t.black_diameter ?? outer) / 2) * 1.15
  // Mitte: die drei höchsten Ringe
  const ring = t.rings.find((r) => r.ring === Math.max(t.lowest, t.top - 2))
  return Math.min(outer, (ring?.diameter ?? outer) / 2) * 1.2
}

/** Scheibe als SVG-Inhalt (ohne äußeres svg), Maße in mm. */
function TargetRings({ t }: { t: TargetInfo }) {
  const black = t.black_diameter ? t.black_diameter / 2 : 0
  const rings = [...t.rings].sort((a, b) => b.diameter - a.diameter)
  return (
    <g className="pad-target">
      <circle r={(rings[0]?.diameter ?? 1) / 2} className="pad-paper" />
      {black > 0 && <circle r={black} className="pad-black" />}
      {rings.map((r) => (
        <circle
          key={r.ring}
          r={r.diameter / 2}
          className={r.diameter / 2 <= black + 1e-6 ? 'pad-line pad-line-dark' : 'pad-line'}
          strokeWidth={Math.max(t.ring_width / 25, 0.06)}
        />
      ))}
      {t.inner_diameter ? (
        <circle
          r={t.inner_diameter / 2}
          className={t.inner_diameter / 2 <= black ? 'pad-line pad-line-dark' : 'pad-line'}
          strokeWidth={Math.max(t.ring_width / 40, 0.04)}
        />
      ) : null}
      {rings
        .filter((r) => r.ring < t.top)
        .map((r) => {
          const pos = r.diameter / 2 - t.ring_width / 2
          const dark = pos < black
          return (
            <text
              key={r.ring}
              x={pos}
              y={0}
              className={dark ? 'pad-number pad-number-dark' : 'pad-number'}
              fontSize={t.ring_width * 0.55}
              textAnchor="middle"
              dominantBaseline="central"
            >
              {r.ring}
            </text>
          )
        })}
    </g>
  )
}

export function TargetPad({
  target: t,
  method,
  counted,
  maxShots,
  hits,
  onChange,
}: {
  target: TargetInfo
  method: ScoringMethod
  counted: number | null
  maxShots: number | null
  hits: PadHit[]
  onChange: (hits: PadHit[]) => void
}) {
  const [zoom, setZoom] = useState<Zoom>(t.spots > 1 ? 'spiegel' : 'ganz')
  const [spot, setSpot] = useState(1)
  const [selected, setSelected] = useState<number | null>(null)
  const [lens, setLens] = useState<{ x: number; y: number } | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const drag = useRef<{ index: number; moved: boolean } | null>(null)
  const R = viewRadius(t, zoom)
  const multi = t.spots > 1
  const onSpot = (h: PadHit) => !multi || (h.spot ?? 1) === spot
  const scores = hits.map((h) => scoreShot(t, h.x, h.y))
  const keep = countedIndexes(method === 'frei' ? 'ringe' : method, scores, counted)
  const total = totalText(method, scores, counted)
  const full = maxShots !== null && hits.length >= maxShots

  function toMm(e: PointerEvent): { x: number; y: number } | null {
    const svg = svgRef.current
    if (!svg) return null
    const rect = svg.getBoundingClientRect()
    if (!rect.width || !rect.height) return null
    const size = Math.min(rect.width, rect.height)
    const x = ((e.clientX - rect.left - (rect.width - size) / 2) / size) * 2 * R - R
    const y = R - ((e.clientY - rect.top - (rect.height - size) / 2) / size) * 2 * R
    return { x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000 }
  }

  function update(index: number, p: { x: number; y: number }) {
    onChange(hits.map((h, i) => (i === index ? { ...h, x: p.x, y: p.y } : h)))
  }

  function onPointerDown(e: PointerEvent<SVGSVGElement>) {
    const p = toMm(e)
    if (!p) return
    // Treffer in der Nähe greifen (Fingerbreite ≈ 3 % der Ansicht), sonst neuen setzen
    const grab = Math.max(t.caliber / 2, R * 0.06)
    let index = -1
    let best = Infinity
    hits.forEach((h, i) => {
      if (!onSpot(h)) return
      const dist = Math.hypot(h.x - p.x, h.y - p.y)
      if (dist <= grab && dist < best) {
        best = dist
        index = i
      }
    })
    if (index < 0) {
      if (full) return
      onChange([...hits, { x: p.x, y: p.y, spot: multi ? spot : null }])
      index = hits.length
    }
    setSelected(index)
    drag.current = { index, moved: false }
    setLens(p)
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }

  function onPointerMove(e: PointerEvent<SVGSVGElement>) {
    if (!drag.current) return
    const p = toMm(e)
    if (!p) return
    drag.current.moved = true
    update(drag.current.index, p)
    setLens(p)
  }

  function onPointerUp() {
    drag.current = null
    setLens(null)
  }

  function remove(index: number) {
    onChange(hits.filter((_, i) => i !== index))
    setSelected(null)
  }

  function onKey(e: KeyboardEvent, index: number) {
    const step = e.shiftKey ? 1 : 0.1
    const h = hits[index]
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [-step, 0],
      ArrowRight: [step, 0],
      ArrowUp: [0, step],
      ArrowDown: [0, -step],
    }
    if (moves[e.key]) {
      e.preventDefault()
      const [dx, dy] = moves[e.key]
      update(index, {
        x: Math.round((h.x + dx) * 1000) / 1000,
        y: Math.round((h.y + dy) * 1000) / 1000,
      })
    } else if (e.key === 'Delete' || e.key === 'Backspace') {
      e.preventDefault()
      remove(index)
    }
  }

  const lensR = Math.max(t.caliber * 1.6, R / 6)
  const holeR = t.caliber / 2

  return (
    <div className="pad">
      <div className="pad-toolbar" role="group" aria-label="Ansicht">
        {ZOOMS.filter((z) => z.key !== 'spiegel' || t.black_diameter).map((z) => (
          <button
            key={z.key}
            type="button"
            className={`button button-ghost${zoom === z.key ? ' active' : ''}`}
            aria-pressed={zoom === z.key}
            onClick={() => setZoom(z.key)}
          >
            {z.label}
          </button>
        ))}
      </div>
      {multi && (
        <div className="pad-toolbar" role="group" aria-label="Scheibenbild">
          {Array.from({ length: t.spots }, (_, i) => i + 1).map((n) => (
            <button
              key={n}
              type="button"
              className={`button button-ghost${spot === n ? ' active' : ''}`}
              aria-pressed={spot === n}
              onClick={() => setSpot(n)}
            >
              Spiegel {n} ({hits.filter((h) => (h.spot ?? 1) === n).length})
            </button>
          ))}
        </div>
      )}
      <div className="pad-stage">
        <svg
          ref={svgRef}
          className="pad-svg"
          viewBox={`${-R} ${-R} ${2 * R} ${2 * R}`}
          role="img"
          aria-label={`${t.name}: ${hits.length} Treffer, antippen zum Setzen`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          <TargetRings t={t} />
          {hits.map((h, i) =>
            onSpot(h) ? (
              <g key={i} className={`pad-hit${i === selected ? ' pad-hit-selected' : ''}`}>
                <circle cx={h.x} cy={-h.y} r={holeR} />
                <text
                  x={h.x}
                  y={-h.y}
                  fontSize={holeR * 0.9}
                  textAnchor="middle"
                  dominantBaseline="central"
                >
                  {i + 1}
                </text>
              </g>
            ) : null,
          )}
        </svg>
        {lens && (
          <svg
            className={`pad-lens${lens.x < 0 && lens.y > 0 ? ' pad-lens-right' : ''}`}
            viewBox={`${lens.x - lensR} ${-lens.y - lensR} ${2 * lensR} ${2 * lensR}`}
            aria-hidden="true"
          >
            <TargetRings t={t} />
            {hits.map((h, i) =>
              onSpot(h) ? (
                <circle key={i} className="pad-hit-lens" cx={h.x} cy={-h.y} r={holeR} />
              ) : null,
            )}
            <line
              x1={lens.x - lensR}
              x2={lens.x + lensR}
              y1={-lens.y}
              y2={-lens.y}
              className="pad-cross"
            />
            <line
              x1={lens.x}
              x2={lens.x}
              y1={-lens.y - lensR}
              y2={-lens.y + lensR}
              className="pad-cross"
            />
          </svg>
        )}
      </div>
      <p className="pad-total" role="status">
        {hits.length}
        {maxShots ? ` von ${maxShots}` : ''} Treffer
        {total ? ` · ${method === 'teiler' ? 'Teiler' : 'Summe'} ${total.replace('.', ',')}` : ''}
        {full ? ' · alle Schüsse gesetzt' : ''}
      </p>
      {hits.length > 0 && (
        <ol className="pad-list">
          {hits.map((h, i) => {
            const s = scores[i]
            return (
              <li key={i}>
                <button
                  type="button"
                  className={`link-button${i === selected ? ' active' : ''}`}
                  aria-label={`Schuss ${i + 1}: ${shotLabel(method, s)}${s.inner ? ', Innenzehner' : ''}. Mit Pfeiltasten verschieben, Entf löscht.`}
                  onClick={() => {
                    setSelected(i)
                    if (multi && h.spot) setSpot(h.spot)
                  }}
                  onKeyDown={(e) => onKey(e, i)}
                >
                  {i + 1}. {shotLabel(method, s)}
                  {s.inner ? ' (Innenzehner)' : ''}
                </button>
                {!keep.has(i) && <span className="muted small"> zählt nicht</span>}
                {multi && <span className="muted small"> · Spiegel {h.spot ?? 1}</span>}{' '}
                <button
                  type="button"
                  className="link-button"
                  aria-label={`Schuss ${i + 1} entfernen`}
                  onClick={() => remove(i)}
                >
                  entfernen
                </button>
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
