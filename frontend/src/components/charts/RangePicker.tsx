// Auswahl des Zeitraums für Auswertungen (siehe range.ts).
import { useState } from 'react'
import { PRESETS, month, monthsBack } from './range.ts'
import type { useRange } from './range.ts'

export function RangePicker({
  range,
  info,
}: {
  range: ReturnType<typeof useRange>
  info?: string
}) {
  const { preset, defaultPreset, custom, set } = range
  const [today] = useState(() => month(new Date()))
  return (
    <div className="card card-wide filters range-picker">
      <select
        aria-label="Zeitraum"
        value={preset}
        onChange={(e) => {
          const key = e.target.value
          if (key === 'eigen')
            set({ zeitraum: key, von: custom.von ?? monthsBack(new Date(), 11), bis: today })
          else
            set({
              zeitraum: key === defaultPreset ? null : key,
              von: null,
              bis: null,
              raster: null,
            })
        }}
      >
        {PRESETS.map((p) => (
          <option key={p.key} value={p.key}>
            {p.label}
          </option>
        ))}
      </select>
      {preset === 'eigen' && (
        <>
          <label className="inline-label">
            von
            <input
              type="month"
              value={custom.von ?? ''}
              max={custom.bis ?? today}
              onChange={(e) => set({ von: e.target.value })}
            />
          </label>
          <label className="inline-label">
            bis
            <input
              type="month"
              value={custom.bis ?? ''}
              min={custom.von}
              max={today}
              onChange={(e) => set({ bis: e.target.value })}
            />
          </label>
          <select
            aria-label="Einteilung"
            value={custom.raster ?? ''}
            onChange={(e) => set({ raster: e.target.value })}
          >
            <option value="">automatisch</option>
            <option value="monat">nach Monaten</option>
            <option value="jahr">nach Jahren</option>
          </select>
        </>
      )}
      {info && <span className="muted small">{info}</span>}
    </div>
  )
}
