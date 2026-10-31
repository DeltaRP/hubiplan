// Würden und Chronik („Wer war wann König?“).
import { api } from './client.ts'

export interface Dignity {
  id: number
  name: string
  unit: number | null
  unit_name: string | null
  sort_order: number
  is_public: boolean
  is_archived: boolean
  /** Ordnungszahl je Vorname („Michael II.“) */
  numbered: boolean
  /** mehrfacher Würdenträger: jede Regentschaft zählt neu */
  count_each_reign: boolean
  /** Einheiten darunter sehen ihre eigenen Träger und können sie auf der Webseite zeigen */
  share_down: boolean
  /** Mehrzahl von Hand, leer = abgeleitet (plural) */
  name_plural: string
  plural: string
  reign_count: number
}

export interface Companion {
  id?: number
  label: string
  person: number | null
  name: string
  display_name?: string
}

export interface Reign {
  id: number
  dignity: number
  dignity_name: string
  year: number | null
  /** Endjahr bei „Startjahr/Endjahr“ (year ist dann das Startjahr) */
  end_year: number | null
  valid_from: string | null
  valid_until: string | null
  period_text: string
  person: number | null
  name: string
  display_name: string
  /** von Hand gesetzte Ordnungszahl, leer = automatisch */
  ordinal: number | null
  /** wirksame Ordnungszahl als römische Zahl, leer ohne Zählung */
  ordinal_text: string
  /** „Vorname Zahl. Nachname“ bzw. der Name ohne Zählung */
  numbered_name: string
  note: string
  /** Woher der Würdenträger kam: Einheit darunter oder frei als Text */
  origin: number | null
  origin_name: string
  origin_text: string
  companions: Companion[]
  photo: { url: string; small_url: string } | null
}

export type ReignInput = Pick<
  Reign,
  'dignity' | 'year' | 'valid_from' | 'valid_until' | 'person' | 'name' | 'note'
> & {
  end_year?: number | null
  ordinal?: number | null
  origin?: number | null
  origin_name?: string
  companions: Companion[]
}

/** Einheit zur Auswahl „aus“ */
export interface Origin {
  id: number
  name: string
}

/** Würde der Einheit darüber, die an diese Einheit weitergegeben ist (nur eigene Träger) */
export interface SharedDignity {
  id: number
  name: string
  owner: string
  reigns: {
    id: number
    period_text: string
    year: number
    numbered_name: string
    note: string
    companions: { label: string; name: string }[]
  }[]
}

export interface HonorsPerson {
  id: number
  first_name: string
  last_name: string
  birth_year: number | null
}

export interface Candidate {
  id: number
  name: string
  birth_year: number | null
}

export interface ImportCompanion {
  label: string
  name: string
  person_id: number | null
  candidates?: Candidate[]
}

export interface ImportRow {
  line: number
  year: number | null
  end_year: number | null
  dignity: string
  dignity_id: number | null
  name: string
  person_id: number | null
  candidates: Candidate[]
  companions: ImportCompanion[]
  note: string
  ordinal: number | null
  ordinal_text: string
  origin: number | null
  origin_name: string
  origin_text: string
  duplicate: boolean
  errors: string[]
}

const base = (org: number) => `/api/orgs/${org}/honors/`

export const honorsApi = {
  dignities: (org: number) => api.get<Dignity[]>(`${base(org)}dignities/`),
  createDignity: (org: number, data: Partial<Dignity>) =>
    api.post<Dignity>(`${base(org)}dignities/`, data),
  updateDignity: (org: number, id: number, data: Partial<Dignity>) =>
    api.patch<Dignity>(`${base(org)}dignities/${id}/`, data),
  /** Reihenfolge der Würden einer Einheit (unit null: die Einheit selbst) */
  reorderDignities: (org: number, unit: number | null, ids: number[]) =>
    api.post(`${base(org)}dignities/reorder/`, { unit, ids }),
  deleteDignity: (org: number, id: number, withReigns = false) =>
    api.del(`${base(org)}dignities/${id}/${withReigns ? '?mit_regentschaften=1' : ''}`),
  reigns: (org: number, params: { wuerde?: number; person?: number } = {}) => {
    const q = new URLSearchParams()
    if (params.wuerde) q.set('wuerde', String(params.wuerde))
    if (params.person) q.set('person', String(params.person))
    const qs = q.toString()
    return api.get<Reign[]>(`${base(org)}reigns/${qs ? `?${qs}` : ''}`)
  },
  createReign: (org: number, data: ReignInput) => api.post<Reign>(`${base(org)}reigns/`, data),
  updateReign: (org: number, id: number, data: ReignInput) =>
    api.put<Reign>(`${base(org)}reigns/${id}/`, data),
  deleteReign: (org: number, id: number) => api.del(`${base(org)}reigns/${id}/`),
  uploadPhoto: (org: number, id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<Reign['photo']>(`${base(org)}reigns/${id}/photo/`, form)
  },
  deletePhoto: (org: number, id: number) => api.del(`${base(org)}reigns/${id}/photo/`),
  origins: (org: number) => api.get<Origin[]>(`${base(org)}origins/`),
  shared: (org: number) => api.get<SharedDignity[]>(`${base(org)}shared/`),
  people: (org: number, term: string) =>
    api.get<HonorsPerson[]>(`${base(org)}people/?suche=${encodeURIComponent(term)}`),
  importPreview: (org: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<{ rows: ImportRow[]; new_dignities: string[] }>(
      `${base(org)}import/preview/`,
      form,
    )
  },
  importRows: (
    org: number,
    rows: {
      year: number
      end_year: number | null
      dignity: string
      name: string
      person_id: number | null
      note: string
      ordinal: number | null
      origin: number | null
      origin_name: string
      companions: { label: string; name: string; person_id: number | null }[]
    }[],
    requestKey?: string,
  ) =>
    api.post<{ created: number; dignities_created: string[] }>(
      `${base(org)}import/`,
      { rows },
      requestKey,
    ),
}
