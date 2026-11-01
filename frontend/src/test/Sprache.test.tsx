// Sprache der Oberfläche (konzepte/englisch.md): Übersetzungsmodul und Auswahl im Profil.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { lang, locale, setCatalogForTest, t, tc, tn } from '../i18n/index.ts'
import type { Catalog } from '../i18n/index.ts'
import { MemoryRouter } from 'react-router-dom'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { LanguageCard, LanguageSwitch } from '../i18n/LanguageControls.tsx'
import en from '../i18n/en.json'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const BOTH = {
  languages: [
    { code: 'de', name: 'Deutsch' },
    { code: 'en', name: 'English' },
  ],
  default: 'de',
}

afterEach(() => {
  setCatalogForTest('de')
  vi.restoreAllMocks()
})

describe('Übersetzungsmodul', () => {
  it('zeigt auf Deutsch den Schlüssel selbst und füllt Platzhalter', () => {
    expect(lang()).toBe('de')
    expect(locale()).toBe('de-DE')
    expect(t('Hallo {name}', { name: 'Karla' })).toBe('Hallo Karla')
    expect(tn('{n} Mitglied', '{n} Mitglieder', 1)).toBe('1 Mitglied')
    expect(tn('{n} Mitglied', '{n} Mitglieder', 1200)).toBe('1.200 Mitglieder')
  })

  it('übersetzt auf Englisch, mit Mehrzahl und Zusammenhang', () => {
    setCatalogForTest('en', {
      'Hallo {name}': 'Hello {name}',
      '{n} Mitglied': { one: '{n} member', other: '{n} members' },
      'social|Beitrag': 'Post',
      Beitrag: 'Fee',
    })
    expect(locale()).toBe('en-GB')
    expect(t('Hallo {name}', { name: 'Karla' })).toBe('Hello Karla')
    expect(tn('{n} Mitglied', '{n} Mitglieder', 1)).toBe('1 member')
    expect(tn('{n} Mitglied', '{n} Mitglieder', 1200)).toBe('1,200 members')
    expect(tc('social', 'Beitrag')).toBe('Post')
    expect(t('Beitrag')).toBe('Fee')
  })

  it('fällt bei fehlender oder leerer Übersetzung auf Deutsch zurück', () => {
    setCatalogForTest('en', { Speichern: '' })
    expect(t('Speichern')).toBe('Speichern')
    expect(t('Unbekannt')).toBe('Unbekannt')
  })

  it('der Katalog enthält nur Texte oder Einzahl/Mehrzahl, nie leere Einträge', () => {
    for (const [key, value] of Object.entries(en as Record<string, unknown>)) {
      if (typeof value === 'string') expect(value, key).not.toBe('')
      else expect(value, key).toMatchObject({ one: expect.any(String), other: expect.any(String) })
    }
  })
})

describe('Sprache wählen', () => {
  it('zeigt im Profil nichts, solange nur Deutsch freigeschaltet ist', async () => {
    const calls = fakeApi({})
    const { container } = render(<LanguageCard />)
    await waitFor(() => expect(calls.some((c) => c.key === 'GET /api/me/language/')).toBe(true))
    expect(container).toBeEmptyDOMElement()
  })

  it('speichert die Sprache am Konto', async () => {
    const calls = fakeApi({
      'GET /api/me/language/': () => ({ status: 200, body: { ...BOTH, language: 'de' } }),
      'PATCH /api/me/language/': () => ({ status: 200, body: { ...BOTH, language: 'en' } }),
    })
    render(<LanguageCard />)
    const select = await screen.findByLabelText('Sprache der Oberfläche')
    expect(screen.getByRole('heading', { name: 'Sprache / Language' })).toBeInTheDocument()
    await userEvent.selectOptions(select, 'en')
    await waitFor(() =>
      expect(calls.find((c) => c.key === 'PATCH /api/me/language/')?.init?.body).toBe(
        JSON.stringify({ language: 'en' }),
      ),
    )
    expect(document.cookie).toContain('hp_lang=en')
  })

  it('bietet vor der Anmeldung die andere Sprache an', async () => {
    fakeApi({ 'GET /api/public/languages/': () => ({ status: 200, body: BOTH }) })
    render(<LanguageSwitch />)
    const button = await screen.findByRole('button', { name: 'English' })
    expect(button).toHaveAttribute('lang', 'en')
  })
})

function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

// Stichprobe gegen vergessene Texte: sichtbarer Text ohne deutsche Umlaute
function expectNoGerman(root: HTMLElement) {
  const text = (root.textContent ?? '').replace(/\s+/g, ' ')
  expect(text).not.toMatch(/[äöüßÄÖÜ]/)
}

describe('Rahmen auf Englisch', () => {
  it('zeigt die Anmeldung auf Englisch', async () => {
    setCatalogForTest('en', en as Catalog)
    fakeApi({
      'GET /_allauth/browser/v1/auth/session': () => ({
        status: 401,
        body: { status: 401, data: { flows: [] } },
      }),
    })
    const { container } = renderApp('/anmelden')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Forgot password?' })).toBeInTheDocument()
    expectNoGerman(container)
  })

  it('zeigt Navigation und Profil auf Englisch', async () => {
    setCatalogForTest('en', en as Catalog)
    fakeApi({
      'GET /_allauth/browser/v1/auth/session': () => ({
        status: 200,
        body: { status: 200, data: { user: testUser } },
      }),
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
    })
    renderApp('/mein-konto')
    expect(await screen.findByRole('heading', { name: 'Profile' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Learning aids' })).toBeInTheDocument()
  })
})
