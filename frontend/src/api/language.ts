// Sprache des eigenen Kontos (Mein Konto › Profil) und wählbare Sprachen vor der Anmeldung.
import { api } from './client.ts'

export interface LanguageOption {
  code: string
  name: string
}

export interface LanguageState {
  languages: LanguageOption[]
  default: string
  /** nur angemeldet: Sprache des Kontos */
  language?: string
}

export const languageApi = {
  mine: () => api.get<LanguageState>('/api/me/language/'),
  setMine: (language: string) => api.patch<LanguageState>('/api/me/language/', { language }),
  available: () => api.get<LanguageState>('/api/public/languages/'),
}
