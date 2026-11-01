// Einfache, barrierearme Diagramme als SVG (ohne externe Bibliothek).
// Jedes Diagramm hat eine Legende (ab zwei Reihen), einen Hinweis beim Zeigen
// oder per Pfeiltasten und eine Tabelle mit allen Werten.
import { useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import './charts.css'
import { PREVIOUS, niceTicks } from './chartData.ts'
import type { Series } from './chartData.ts'
import { t } from '../../i18n/index.ts'

function useWidth(fallback = 640) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const obs = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width)
      if (w > 0) setWidth(w)
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])
  return { ref, width }
}

/** Vergleichszeitraum zusätzlich schraffiert bzw. gestrichelt, nicht nur grau (C04) */
function fillFor(color: string): string {
  return color === PREVIOUS
    ? `repeating-linear-gradient(135deg, ${color} 0 4px, #fff 4px 6px)`
    : color
}

export function Legend({ series }: { series: { key: string; name: string; color: string }[] }) {
  if (series.length < 2) return null
  return (
    <ul className="chart-legend">
      {series.map((s) => (
        <li key={s.key}>
          <span
            className="chart-swatch"
            style={{ background: fillFor(s.color), borderColor: s.color }}
            aria-hidden="true"
          />
          {s.name}
        </li>
      ))}
    </ul>
  )
}

/** Legende mit Schaltern: jede Reihe lässt sich ein- und ausblenden. */
function ToggleLegend({
  series,
  hidden,
  onChange,
}: {
  series: { key: string; name: string; color: string }[]
  hidden: ReadonlySet<string>
  onChange: (next: ReadonlySet<string>) => void
}) {
  const flip = (key: string) => {
    const next = new Set(hidden)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    onChange(next)
  }
  return (
    <div className="chart-legend-toggle">
      <ul className="chart-legend" aria-label={t('Reihen ein- und ausblenden')}>
        {series.map((s) => {
          const on = !hidden.has(s.key)
          return (
            <li key={s.key}>
              <button
                type="button"
                className="chart-legend-button"
                aria-pressed={on}
                onClick={() => flip(s.key)}
              >
                <span
                  className="chart-swatch"
                  style={{ background: on ? s.color : 'transparent', borderColor: s.color }}
                  aria-hidden="true"
                />
                {s.name}
              </button>
            </li>
          )
        })}
      </ul>
      <p className="chart-legend-all small">
        <button
          type="button"
          className="link-button"
          disabled={hidden.size === 0}
          onClick={() => onChange(new Set())}
        >
          {t('Alle zeigen')}
        </button>
        <button
          type="button"
          className="link-button"
          disabled={hidden.size === series.length}
          onClick={() => onChange(new Set(series.map((s) => s.key)))}
        >
          {t('Alle ausblenden')}
        </button>
      </p>
    </div>
  )
}

function ValueTable({
  labels,
  series,
  format,
  head,
}: {
  labels: string[]
  series: { key: string; name: string; values: (number | null)[] }[]
  format: (n: number) => string
  head: string
}) {
  return (
    <details className="chart-table">
      <summary>{t('Werte als Tabelle')}</summary>
      <div className="table-scroll" tabIndex={0} role="region" aria-label={t('Werte als Tabelle')}>
        <table className="table table-keep">
          <thead>
            <tr>
              <th scope="col">{head}</th>
              {series.map((s) => (
                <th key={s.key} scope="col" className="num">
                  {s.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {labels.map((label, i) => (
              <tr key={label}>
                <th scope="row">{label}</th>
                {series.map((s) => (
                  <td key={s.key} className="num">
                    {s.values[i] === null ? '–' : format(s.values[i] ?? 0)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}

export function ChartCard({
  title,
  note,
  children,
}: {
  title: string
  note?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="card card-wide chart-card">
      <h2>{title}</h2>
      {typeof note === 'string' ? <p className="muted small">{note}</p> : note}
      {children}
    </div>
  )
}

/** Verlauf über die Zeit: Linien oder gruppierte Säulen (auch negativ). */
export function TimeChart({
  title,
  labels,
  series,
  kind,
  format,
  axisFormat = format,
  height = 220,
  tableHead = t('Zeitraum'),
  toggleable = false,
}: {
  title: string
  labels: string[]
  series: Series[]
  kind: 'line' | 'bar'
  /** Werte im Hinweis und in der Tabelle */
  format: (n: number) => string
  /** Beschriftung der Achse (z. B. ohne Cent) */
  axisFormat?: (n: number) => string
  height?: number
  tableHead?: string
  /** Reihen über die Legende ein- und ausblenden */
  toggleable?: boolean
}) {
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set())
  const shown = toggleable ? series.filter((s) => !hidden.has(s.key)) : series
  const { ref, width } = useWidth()
  const [active, setActive] = useState<number | null>(null)
  const tipId = useId()
  const prevPattern = `prev-${tipId.replace(/[^a-zA-Z0-9_-]/g, '')}`
  const n = labels.length
  const all = shown.flatMap((s) => s.values.filter((v): v is number => v !== null))
  // Säulen stehen auf der Nulllinie; Linien zeigen den Ausschnitt mit den Werten
  const ticks =
    all.length === 0 ? [0, 1] : niceTicks(Math.min(...all), Math.max(...all), 4, kind === 'bar')
  const lo = ticks[0]
  const hi = ticks[ticks.length - 1]
  const tickText = ticks.map((tm) => axisFormat(tm))
  const left = Math.min(110, 10 + Math.max(...tickText.map((tm) => tm.length)) * 7)
  const top = 10
  const bottom = 26
  const right = 10
  const plotW = Math.max(40, width - left - right)
  const plotH = height - top - bottom
  const band = plotW / Math.max(1, n)
  const y = (v: number) => top + plotH - ((v - lo) / (hi - lo || 1)) * plotH
  const xCenter = (i: number) => left + band * i + band / 2
  const every = Math.max(1, Math.ceil((n * 64) / plotW))

  const move = (e: KeyboardEvent) => {
    if (n === 0) return
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      const d = e.key === 'ArrowRight' ? 1 : -1
      setActive((a) => (a === null ? (d > 0 ? 0 : n - 1) : Math.min(n - 1, Math.max(0, a + d))))
    } else if (e.key === 'Home') setActive(0)
    else if (e.key === 'End') setActive(n - 1)
    else if (e.key === 'Escape') setActive(null)
  }

  const barGroup = band * 0.72
  const barW = Math.max(2, (barGroup - (shown.length - 1) * 2) / Math.max(1, shown.length))
  const bar = (v: number, i: number, k: number) => {
    const x = left + band * i + (band - barGroup) / 2 + k * (barW + 2)
    const y0 = y(0)
    const y1 = y(v)
    const h = Math.abs(y1 - y0)
    if (h < 0.5) return null
    const r = Math.min(4, barW / 2, h)
    // Abgerundet nur am Datenende, gerade an der Nulllinie
    const d =
      v >= 0
        ? `M${x},${y0}V${y1 + r}Q${x},${y1} ${x + r},${y1}H${x + barW - r}Q${x + barW},${y1} ${x + barW},${y1 + r}V${y0}Z`
        : `M${x},${y0}V${y1 - r}Q${x},${y1} ${x + r},${y1}H${x + barW - r}Q${x + barW},${y1} ${x + barW},${y1 - r}V${y0}Z`
    return d
  }

  const linePath = (values: (number | null)[]) => {
    let d = ''
    let pen = false
    values.forEach((v, i) => {
      if (v === null) {
        pen = false
        return
      }
      d += `${pen ? 'L' : 'M'}${xCenter(i)},${y(v)}`
      pen = true
    })
    return d
  }

  const tipLeft = active === null ? 0 : (xCenter(active) / width) * 100
  return (
    <figure className="chart">
      <div
        ref={ref}
        className="chart-plot"
        tabIndex={0}
        role="group"
        aria-label={t('{title}. Mit den Pfeiltasten durch die Werte gehen.', { title })}
        aria-describedby={active === null ? undefined : tipId}
        onKeyDown={move}
        onMouseLeave={() => setActive(null)}
        onBlur={() => setActive(null)}
      >
        <svg width={width} height={height} aria-hidden="true">
          <defs>
            <pattern
              id={prevPattern}
              width="6"
              height="6"
              patternUnits="userSpaceOnUse"
              patternTransform="rotate(45)"
            >
              <rect width="6" height="6" fill="#fff" />
              <rect width="4" height="6" fill={PREVIOUS} />
            </pattern>
          </defs>
          {ticks.map((tm, i) => (
            <g key={tm}>
              <line
                x1={left}
                x2={left + plotW}
                y1={y(tm)}
                y2={y(tm)}
                className={tm === 0 ? 'chart-zero' : 'chart-grid'}
              />
              <text x={left - 6} y={y(tm)} dy="0.32em" textAnchor="end" className="chart-axis">
                {tickText[i]}
              </text>
            </g>
          ))}
          {labels.map((label, i) =>
            i % every === 0 ? (
              <text
                key={label}
                x={xCenter(i)}
                y={height - 8}
                textAnchor="middle"
                className="chart-axis"
              >
                {label}
              </text>
            ) : null,
          )}
          {active !== null && kind === 'bar' && (
            <rect
              x={left + band * active}
              y={top}
              width={band}
              height={plotH}
              className="chart-hover-band"
            />
          )}
          {kind === 'bar' &&
            shown.map((s, k) =>
              s.values.map((v, i) => {
                const d = v === null ? null : bar(v, i, k)
                return d ? (
                  <path
                    key={`${s.key}-${i}`}
                    d={d}
                    fill={s.color === PREVIOUS ? `url(#${prevPattern})` : s.color}
                    stroke={s.color === PREVIOUS ? PREVIOUS : undefined}
                  />
                ) : null
              }),
            )}
          {kind === 'line' && (
            <>
              {active !== null && (
                <line
                  x1={xCenter(active)}
                  x2={xCenter(active)}
                  y1={top}
                  y2={top + plotH}
                  className="chart-crosshair"
                />
              )}
              {shown.map((s) => (
                <path
                  key={s.key}
                  d={linePath(s.values)}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={2}
                  strokeDasharray={s.color === PREVIOUS ? '6 4' : undefined}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              ))}
              {shown.map((s) =>
                s.values.map((v, i) =>
                  v !== null && (n <= 24 || i === active) ? (
                    <circle
                      key={`${s.key}-${i}`}
                      cx={xCenter(i)}
                      cy={y(v)}
                      r={i === active ? 5 : 3.5}
                      fill={s.color}
                      className="chart-dot"
                    />
                  ) : null,
                ),
              )}
            </>
          )}
          {labels.map((label, i) => (
            <rect
              key={`hit-${label}`}
              x={left + band * i}
              y={top}
              width={band}
              height={plotH}
              fill="transparent"
              onMouseEnter={() => setActive(i)}
            />
          ))}
        </svg>
        {active !== null && (
          <div
            id={tipId}
            className="chart-tip"
            role="status"
            style={{
              left: `${tipLeft}%`,
              transform: `translateX(${tipLeft > 60 ? '-105%' : '5%'})`,
            }}
          >
            <strong>{labels[active]}</strong>
            {shown.map((s) => (
              <span key={s.key}>
                <span
                  className="chart-swatch"
                  style={{ background: fillFor(s.color), borderColor: s.color }}
                  aria-hidden="true"
                />
                {s.name}: {s.values[active] === null ? '–' : format(s.values[active] ?? 0)}
              </span>
            ))}
          </div>
        )}
      </div>
      {toggleable ? (
        <ToggleLegend series={series} hidden={hidden} onChange={setHidden} />
      ) : (
        <Legend series={series} />
      )}
      <ValueTable labels={labels} series={series} format={format} head={tableHead} />
    </figure>
  )
}

/** Waagerechte Balken je Zeile, z. B. Altersgruppen oder Kategorien im Vergleich. */
export function BarList({
  rows,
  series,
  format,
  head,
}: {
  rows: { key: string; label: string; values: number[] }[]
  series: { key: string; name: string; color: string }[]
  format: (n: number) => string
  head: string
}) {
  const max = Math.max(1, ...rows.flatMap((r) => r.values.map(Math.abs)))
  return (
    <figure className="chart">
      <Legend series={series} />
      <dl className="bar-list">
        {rows.map((r) => (
          <div key={r.key} className="bar-row">
            <dt>{r.label}</dt>
            <dd>
              {r.values.map((v, k) => (
                <div key={series[k].key} className="bar-line">
                  <span
                    className="bar-fill"
                    style={{
                      width: `${(Math.abs(v) / max) * 100}%`,
                      background: fillFor(series[k].color),
                      outline: series[k].color === PREVIOUS ? `1px solid ${PREVIOUS}` : undefined,
                    }}
                  />
                  <span className="bar-value">
                    {series.length > 1 && <span className="sr-only">{series[k].name}: </span>}
                    {format(v)}
                  </span>
                </div>
              ))}
            </dd>
          </div>
        ))}
      </dl>
      <ValueTable
        labels={rows.map((r) => r.label)}
        series={series.map((s, k) => ({ ...s, values: rows.map((r) => r.values[k]) }))}
        format={format}
        head={head}
      />
    </figure>
  )
}
