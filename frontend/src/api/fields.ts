// Zusatzfelder und Jubiläen (Meilenstein 4).
import { api } from './client.ts'
import type { DatePrecision } from '../components/forms.ts'

export type FieldType = 'text' | 'number' | 'date' | 'bool' | 'choice' | 'yearrange'

export const FIELD_TYPES: { value: FieldType; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'number', label: 'Zahl' },
  { value: 'date', label: 'Datum' },
  { value: 'bool', label: 'Ja/Nein' },
  { value: 'choice', label: 'Auswahlliste' },
  { value: 'yearrange', label: 'Startjahr/Endjahr' },
]

export interface Subfield {
  key?: string
  label: string
  type: FieldType
  choices?: string[]
}

export interface FieldDefinition {
  id: number
  label: string
  key: string
  field_type: FieldType
  choices: string[]
  repeatable: boolean
  subfields: Subfield[]
  federation_wide: boolean
  help_text: string
  sort_order: number
  is_archived: boolean
  inherited: boolean
  owner_name: string
  in_use: boolean
}

export interface FieldUsage {
  deletable: boolean
  value_count: number
  is_archived: boolean
}

export type Scalar = string | number | boolean | null
export type FieldValue = Scalar | Record<string, Scalar>[]

export interface MemberField {
  definition: FieldDefinition
  value: FieldValue
}

export interface JubileeRow {
  member_id: number
  last_name: string
  first_name: string
  birth_date: string
  member_number: number | null
  kind: 'club' | 'federation'
  organization: string
  organization_short?: string
  /** Untereinheiten (z. B. Züge) des Mitglieds, kommagetrennt; leer, wenn keine */
  units?: string
  years: number
  date: string
  precision?: DatePrecision
}

const base = (org: number) => `/api/orgs/${org}`

export const fieldApi = {
  list: (org: number) => api.get<FieldDefinition[]>(`${base(org)}/fields/`),
  create: (org: number, data: Partial<FieldDefinition>) =>
    api.post<FieldDefinition>(`${base(org)}/fields/`, data),
  update: (org: number, id: number, data: Partial<FieldDefinition>, withValues = false) =>
    api.patch<FieldDefinition>(
      `${base(org)}/fields/${id}/${withValues ? '?mit_werten=1' : ''}`,
      data,
    ),
  remove: (org: number, id: number, withValues = false) =>
    api.del(`${base(org)}/fields/${id}/${withValues ? '?mit_werten=1' : ''}`),
  usage: (org: number, id: number) => api.get<FieldUsage>(`${base(org)}/fields/${id}/usage/`),
  archive: (org: number, id: number) =>
    api.post<FieldDefinition>(`${base(org)}/fields/${id}/archive/`),
  restore: (org: number, id: number) =>
    api.post<FieldDefinition>(`${base(org)}/fields/${id}/restore/`),
  memberValues: (org: number, member: number) =>
    api.get<MemberField[]>(`${base(org)}/members/${member}/fields/`),
  saveMemberValues: (org: number, member: number, values: Record<string, FieldValue>) =>
    api.put<MemberField[]>(`${base(org)}/members/${member}/fields/`, { values }),
  jubilees: (org: number, von: string, bis: string) =>
    api.get<{ von: string; bis: string; results: JubileeRow[] }>(
      `${base(org)}/jubilees/?von=${von}&bis=${bis}`,
    ),
  unitJubilees: (org: number, von: string, bis: string) =>
    api.get<{ von: string; bis: string; results: UnitJubileeRow[] }>(
      `${base(org)}/unit-jubilees/?von=${von}&bis=${bis}`,
    ),
  birthdays: (org: number, von: string, bis: string) =>
    api.get<{ von: string; bis: string; results: BirthdayRow[] }>(
      `${base(org)}/birthdays/?von=${von}&bis=${bis}`,
    ),
}

/** Geburtstag eines aktuellen Mitglieds im Zeitraum */
export interface BirthdayRow {
  member_id: number
  first_name: string
  last_name: string
  /** Tag des Geburtstags im Zeitraum (JJJJ-MM-TT) */
  date: string
  /** Alter an diesem Tag */
  age: number
  /** Untereinheiten (z. B. Züge) des Mitglieds, kommagetrennt; leer, wenn keine */
  units?: string
}

/** Jubiläum einer Einheit aus ihrem Gründungsjahr (jahresgenau). */
export interface UnitJubileeRow {
  id: number
  /** self: die Einheit selbst; unit: Untereinheit; club: Verein im Dachverband */
  kind: 'self' | 'unit' | 'club'
  name: string
  short_name: string
  /** z. B. „Jägerzug › Gruppe 1“ */
  path: string
  label: string
  /** Mehrzahl, Genus und Genitiv der Bezeichnung (z. B. „Züge“, „m“, „Zugs“) */
  label_plural?: string
  label_gender?: string
  label_genitive?: string
  founding_year: number
  years: number
  year: number
}
