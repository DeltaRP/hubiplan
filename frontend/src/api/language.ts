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

let availableOnce: Promise<LanguageState> | null = null

/** Wählbare Sprachen, einmal je Seitenaufruf geholt. */
export function availableLanguages(): Promise<LanguageState> {
  availableOnce ??= languageApi.available().catch((err) => {
    availableOnce = null
    throw err
  })
  return availableOnce
}

/** Nur für Tests: Zwischenspeicher leeren. */
export function resetLanguagesForTest() {
  availableOnce = null
}
