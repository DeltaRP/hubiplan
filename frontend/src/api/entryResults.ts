// Wettbewerbe Schritt 3: Ergebnisse zurück an die meldende Untereinheit (gleiche Instanz).
import { api } from './client.ts'
import type { Scope } from './entries.ts'

export interface EntryResultRow {
  place: number | null
  name: string
  value_text: string
  /** eigener Starter, eigene Mannschaft bzw. eigene Untereinheit */
  own: boolean
  unit_name?: string
  club?: string
  members?: string[]
}

export interface EntryResults {
  title: string
  date: string
  status: string
  status_label: string
  final: boolean
  share_ranking: boolean
  scorings: {
    name: string
    kind: 'einzel' | 'einheit' | 'mannschaft'
    field: number | null
    complete: boolean
    rows: EntryResultRow[]
  }[]
  prizes: { name: string; own: boolean; unit_name?: string; winner?: string }[]
}

const base = (org: Scope) => (typeof org === 'string' ? org : `/api/orgs/${org}/entries/`)

export const entryResultsApi = {
  get: (org: Scope, call: number) =>
    api.get<EntryResults>(`${base(org)}calls/${call}/entry/results/`),
}
