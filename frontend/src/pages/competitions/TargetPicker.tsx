// Scheibe auswählen mit Vorschaubild (Ralf 01.11.2026: nicht jeder kennt die Kartennamen).
// Jedes Bild wird aus den Maßen des Katalogs gezeichnet; Karten mit mehreren Spiegeln
// zeigen die übliche Anordnung (vier Ecken und Mitte).
import type { TargetInfo } from '../../api/competitions.ts'
import { TargetRings } from './TargetPad.tsx'

function spotOffsets(t: TargetInfo): [number, number][] {
  const outer = (t.rings[0]?.diameter ?? t.top_diameter) / 2
  if (t.spots <= 1) return [[0, 0]]
  const gap = 2 * outer + 4
  if (t.spots === 5) {
    const p = gap / Math.SQRT2
    return [
      [-p, p],
      [p, p],
      [0, 0],
      [-p, -p],
      [p, -p],
    ]
  }
  const cols = 3
  const rows = Math.ceil(t.spots / cols)
  return Array.from({ length: t.spots }, (_, i) => [
    ((i % cols) - (cols - 1) / 2) * gap,
    ((rows - 1) / 2 - Math.floor(i / cols)) * gap,
  ])
}

/** Kleines Bild der Karte (Maße in mm). */
export function TargetPreview({ t }: { t: TargetInfo }) {
  const outer = (t.rings[0]?.diameter ?? t.top_diameter) / 2
  const offsets = spotOffsets(t)
  const extent = Math.max(...offsets.map(([x, y]) => Math.max(Math.abs(x), Math.abs(y)))) + outer
  const half = extent * 1.12
  return (
    <svg
      className="target-preview"
      viewBox={`${-half} ${-half} ${2 * half} ${2 * half}`}
      aria-hidden="true"
      focusable="false"
    >
      <rect
        x={-half * 0.98}
        y={-half * 0.98}
        width={half * 1.96}
        height={half * 1.96}
        className="pad-paper target-preview-card"
      />
      {offsets.map(([x, y], i) => (
        <g key={i} transform={`translate(${x} ${-y})`}>
          <TargetRings t={t} />
        </g>
      ))}
    </svg>
  )
}

function fmt(n: number): string {
  return String(n).replace('.', ',')
}

/** Kurzbeschreibung in Alltagssprache. */
function targetSummary(t: TargetInfo): string {
  const parts = [
    t.spots > 1 ? `${t.spots} Spiegel auf einer Karte` : 'ein Spiegel je Karte',
    t.top_diameter <= 1 ? 'Zehn als kleiner Punkt' : `Zehn ${fmt(t.top_diameter)} mm`,
    `Ringe ${t.lowest} bis ${t.top}`,
  ]
  if (t.photo) parts.push('Foto möglich')
  return parts.join(' · ')
}

export function TargetPicker({
  targets,
  value,
  customKey,
  onChange,
  error,
}: {
  targets: TargetInfo[]
  value: string
  customKey: string
  onChange: (key: string) => void
  error?: string
}) {
  const groups = [...new Set(targets.map((t) => t.group))]
  const name = 'scheibe'
  return (
    <fieldset className="target-picker">
      <legend>Scheibe</legend>
      <div className="target-tiles">
        <label className={`target-tile${value === '' ? ' target-tile-on' : ''}`}>
          <input
            type="radio"
            name={name}
            value=""
            checked={value === ''}
            onChange={() => onChange('')}
          />
          <span className="target-tile-none" aria-hidden="true">
            Σ
          </span>
          <span className="target-tile-name">keine Scheibe</span>
          <span className="target-tile-note">nur die Summe eingeben</span>
        </label>
      </div>
      {groups.map((g) => (
        <div key={g}>
          <p className="target-group">{g}</p>
          <div className="target-tiles">
            {targets
              .filter((t) => t.group === g)
              .map((t) => (
                <label
                  key={t.key}
                  className={`target-tile${value === t.key ? ' target-tile-on' : ''}`}
                >
                  <input
                    type="radio"
                    name={name}
                    value={t.key}
                    checked={value === t.key}
                    onChange={() => onChange(t.key)}
                  />
                  <TargetPreview t={t} />
                  <span className="target-tile-name">{t.name}</span>
                  <span className="target-tile-note">{targetSummary(t)}</span>
                </label>
              ))}
          </div>
        </div>
      ))}
      <div className="target-tiles">
        <label className={`target-tile${value === customKey ? ' target-tile-on' : ''}`}>
          <input
            type="radio"
            name={name}
            value={customKey}
            checked={value === customKey}
            onChange={() => onChange(customKey)}
          />
          <span className="target-tile-none" aria-hidden="true">
            ✎
          </span>
          <span className="target-tile-name">Eigene Scheibe</span>
          <span className="target-tile-note">Maße selbst eingeben</span>
        </label>
      </div>
      {error && <p className="field-error">{error}</p>}
    </fieldset>
  )
}
