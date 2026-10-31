// Zeitraum für Auswertungen. Steht in der Adresse (?zeitraum=…), damit Zurück
// und Lesezeichen funktionieren. Standard je Seite: Mitglieder die letzten 5 Jahre,
// Finanzen die letzten 12 Monate.
import { useSearchParams } from 'react-router-dom'
import type { RangeQuery } from '../../api/statistics.ts'

export const PRESETS = [
  { key: '12m', label: 'Letzte 12 Monate' },
  { key: '24m', label: 'Letzte 24 Monate' },
  { key: 'jahr', label: 'Dieses Jahr' },
  { key: 'vorjahr', label: 'Letztes Jahr' },
  { key: '3j', label: 'Letzte 3 Jahre' },
  { key: '5j', label: 'Letzte 5 Jahre' },
  { key: '10j', label: 'Letzte 10 Jahre' },
  { key: 'alles', label: 'Gesamter Zeitraum' },
  { key: 'eigen', label: 'Eigener Zeitraum' },
] as const

export type Preset = (typeof PRESETS)[number]['key']

export const pad = (n: number) => String(n).padStart(2, '0')
export const month = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}`
export const monthsBack = (today: Date, n: number) =>
  month(new Date(today.getFullYear(), today.getMonth() - n, 1))

/** Abfrage für den Server aus Voreinstellung und eigenen Angaben. */
export function presetQuery(
  preset: string,
  custom: RangeQuery,
  today: Date = new Date(),
): RangeQuery {
  const y = today.getFullYear()
  switch (preset) {
    case '24m':
      return { von: monthsBack(today, 23) }
    case 'jahr':
      return { von: `${y}-01`, raster: 'monat' }
    case 'vorjahr':
      return { von: `${y - 1}-01`, bis: `${y - 1}-12`, raster: 'monat' }
    case '3j':
      return { von: `${y - 2}-01`, raster: 'jahr' }
    case '5j':
      return { von: `${y - 4}-01`, raster: 'jahr' }
    case '10j':
      return { von: `${y - 9}-01`, raster: 'jahr' }
    case 'alles':
      return { von: 'alles', raster: 'jahr' }
    case 'eigen':
      return custom
    default:
      return {}
  }
}

export function useRange(defaultPreset: Preset = '12m') {
  const [params, setParams] = useSearchParams()
  const preset = (params.get('zeitraum') as Preset | null) ?? defaultPreset
  const raster = params.get('raster')
  const custom: RangeQuery = {
    von: params.get('von') ?? undefined,
    bis: params.get('bis') ?? undefined,
    raster: raster === 'monat' || raster === 'jahr' ? raster : undefined,
  }
  const query = presetQuery(preset, custom)
  const set = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    setParams(next, { replace: true })
  }
  return { preset, defaultPreset, custom, query, set }
}
