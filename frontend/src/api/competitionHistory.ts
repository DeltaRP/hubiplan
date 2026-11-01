// Wettbewerbe Schritt 4: Auszeichnungen, Reihen, Wanderpokale und vergebene Titel.
import { api } from './client.ts'

export interface Award {
  id: number
  scoring: number | null
  prize: number | null
  place_from: number
  place_to: number
  /** Titel ohne Jahr, z. B. „Vereinsmeister“ */
  title: string
  item: string
  dignity: number | null
  dignity_name: string
  trophy: number | null
  trophy_name: string
  sort_order: number
}

export type DignityState = '' | 'vorschlag' | 'bestaetigt' | 'abgelehnt'

export interface Grant {
  id: number
  year: number
  title: string
  item: string
  /** Titel mit Jahr („Vereinsmeister 2027“) bzw. Preis */
  full_title: string
  scoring_name: string
  place: number | null
  value_text: string
  name: string
  membership: number | null
  unit: number | null
  competition: number | null
  competition_title: string
  series: number | null
  trophy: number | null
  trophy_name: string
  dignity: number | null
  dignity_name: string
  dignity_state: DignityState
  reign: number | null
  manual: boolean
  note: string
}

export interface Series {
  id: number
  name: string
  description: string
  on_website: boolean
  competition_count: number
}

export interface PodiumRow {
  place: number | null
  name: string
  starter: number | null
  unit: number | null
  unit_name: string
  value_text: string
}

export interface SeriesArchive {
  id: number
  name: string
  description: string
  years: {
    competition: number
    title: string
    date: string
    year: number
    status: string
    winners: { scoring: string; kind: string; podium: PodiumRow[]; field: number | null }[]
  }[]
  titles: Grant[]
  records: {
    scoring: string
    unit_label: string
    counted_shots: number | null
    name: string
    value_text: string
    year: number
  }[]
  units: { unit: number; name: string; years: { year: number; place: number; scoring: string }[] }[]
}

export interface TrophyHolder {
  id: number
  year: number
  name: string
  membership: number | null
  unit: number | null
  competition: number | null
  streak: number
  kept: boolean
  manual: boolean
}

export interface Trophy {
  id: number
  name: string
  description: string
  keep_after: number | null
  is_archived: boolean
  on_website: boolean
  holders: TrophyHolder[]
}

export interface MemberHistory {
  starts: {
    competition: number
    title: string
    date: string
    status: string
    status_label: string
    own: boolean
    unit_name: string
    results: {
      scoring: string
      place: number | null
      value_text: string
      field: number | null
    }[]
  }[]
  grants: Grant[]
  can_open: boolean
}

const base = (org: number) => `/api/orgs/${org}/competitions/`

export const historyApi = {
  awards: {
    list: (org: number, comp: number) => api.get<Award[]>(`${base(org)}${comp}/awards/`),
    create: (org: number, comp: number, data: Partial<Award>) =>
      api.post<Award>(`${base(org)}${comp}/awards/`, data),
    update: (org: number, comp: number, id: number, data: Partial<Award>) =>
      api.patch<Award>(`${base(org)}${comp}/awards/${id}/`, data),
    remove: (org: number, comp: number, id: number) => api.del(`${base(org)}${comp}/awards/${id}/`),
    grantAgain: (org: number, comp: number) => api.post<Grant[]>(`${base(org)}${comp}/grant/`, {}),
  },
  series: {
    list: (org: number) => api.get<Series[]>(`${base(org)}series/`),
    archive: (org: number, id: number) => api.get<SeriesArchive>(`${base(org)}series/${id}/`),
    create: (org: number, data: Partial<Series>) => api.post<Series>(`${base(org)}series/`, data),
    update: (org: number, id: number, data: Partial<Series>) =>
      api.patch<Series>(`${base(org)}series/${id}/`, data),
    remove: (org: number, id: number) => api.del(`${base(org)}series/${id}/`),
  },
  trophies: {
    list: (org: number) => api.get<Trophy[]>(`${base(org)}trophies/`),
    create: (org: number, data: Partial<Trophy>) => api.post<Trophy>(`${base(org)}trophies/`, data),
    update: (org: number, id: number, data: Partial<Trophy>) =>
      api.patch<Trophy>(`${base(org)}trophies/${id}/`, data),
    remove: (org: number, id: number) => api.del(`${base(org)}trophies/${id}/`),
  },
  grants: {
    list: (org: number, query = '') => api.get<Grant[]>(`${base(org)}grants/${query}`),
    create: (org: number, data: Partial<Grant>) => api.post<Grant>(`${base(org)}grants/`, data),
    update: (org: number, id: number, data: Partial<Grant>) =>
      api.patch<Grant>(`${base(org)}grants/${id}/`, data),
    remove: (org: number, id: number) => api.del(`${base(org)}grants/${id}/`),
    decide: (org: number, id: number, decision: 'bestaetigen' | 'ablehnen') =>
      api.post<Grant>(`${base(org)}grants/${id}/dignity/`, { decision }),
  },
  /** Mitgliederbereich und App: „Meine Ergebnisse“ */
  mine: (access: number) =>
    api.get<Omit<MemberHistory, 'can_open'>>(`/api/portal/${access}/results/`),
  member: (org: number, membership: number) =>
    api.get<MemberHistory>(`${base(org)}member/${membership}/`),
}
