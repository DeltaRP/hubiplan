// Impressum und Datenschutzhinweise der Plattform und der Einheiten.
import { api } from './client.ts'

export type ImprintMode = 'inherit' | 'own' | 'link'

export interface ImprintFields {
  mode: ImprintMode
  external_url: string
  name: string
  legal_form: string
  street: string
  postal_code: string
  city: string
  representatives: string
  email: string
  phone: string
  registered: boolean
  register_court: string
  register_number: string
  vat_id: string
  responsible: string
  data_protection_officer: string
  extra_text: string
  privacy_mode: 'text' | 'link'
  privacy_text: string
  privacy_url: string
}

export interface Imprint extends ImprintFields {
  public_key: string
  privacy_published_text: string
  privacy_published_at: string | null
  updated_at: string
}

export interface Representative {
  name: string
  role: string
}

export interface ImprintDetails {
  name: string
  legal_form: string
  address: { street: string; postal_code: string; city: string; country: string }
  representatives: Representative[]
  representatives_text: string
  email: string
  phone: string
  website: string
  registered: boolean
  register_court: string
  register_number: string
  vat_id: string
  responsible: string
  data_protection_officer: string
  extra_text: string
}

/** Pflegeansicht: gepflegte Werte, Vorschau und fehlende Angaben. */
export interface ImprintState {
  organization: { id: number; name: string; type: string }
  imprint: Imprint
  owner: { id: number; name: string; is_self: boolean }
  preview: ImprintDetails
  representatives: Representative[]
  missing: string[]
  urls: { imprint: string; privacy: string }
  template: string
}

/** Öffentliche Seite. */
export interface PublicImprint {
  unit: string
  owner: string
  owner_label: string
  is_platform: boolean
  inherited: boolean
  mode: ImprintMode
  external_url: string
  details: ImprintDetails | null
  privacy: { mode: 'text' | 'link'; text: string; url: string }
  updated_at: string
  platform?: { imprint: string; privacy: string }
}

const org = (id: number) => `/api/orgs/${id}/imprint/`

export const imprintApi = {
  get: (orgId: number) => api.get<ImprintState>(org(orgId)),
  update: (orgId: number, data: Partial<ImprintFields>) =>
    api.patch<ImprintState>(org(orgId), data),
  unit: (orgId: number, unitId: number) => api.get<ImprintState>(`${org(orgId)}units/${unitId}/`),
  updateUnit: (orgId: number, unitId: number, data: Partial<ImprintFields>) =>
    api.patch<ImprintState>(`${org(orgId)}units/${unitId}/`, data),
  platform: () => api.get<ImprintState>('/api/platform/imprint/'),
  updatePlatform: (data: Partial<ImprintFields>) =>
    api.patch<ImprintState>('/api/platform/imprint/', data),
  /** Entwurf der Datenschutzhinweise veröffentlichen (Einheit, Untereinheit oder Plattform) */
  publishPrivacy: (orgId: number | null, unitId?: number | null) =>
    api.post<ImprintState>(
      orgId === null
        ? '/api/platform/imprint/'
        : unitId
          ? `${org(orgId)}units/${unitId}/`
          : org(orgId),
      { action: 'publish_privacy' },
    ),
  public: (key?: string) =>
    api.get<PublicImprint>(key ? `/api/public/imprint/${key}/` : '/api/public/imprint/'),
}

/** Adressen der öffentlichen Seiten (ohne Schlüssel: Plattform). */
export function imprintPath(key?: string | null): string {
  return key ? `/impressum/${key}` : '/impressum'
}

export function privacyPath(key?: string | null): string {
  return key ? `/datenschutz/${key}` : '/datenschutz'
}
