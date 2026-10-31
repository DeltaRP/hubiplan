// UI-/UX-Audit 29.10.2026, Teil c (Oberfläche).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { loginTarget, rememberedTarget, rememberTarget } from '../auth/loginTarget.ts'
import { emptySelections } from '../api/circulars.ts'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const base = '/api/orgs/7/honors/'

const koenig = {
  id: 1,
  name: 'König',
  unit: null,
  unit_name: null,
  sort_order: 1,
  is_public: true,
  is_archived: false,
  reign_count: 1,
}
const kaiser = { ...koenig, id: 2, name: 'Kaiser', is_archived: true }

const period = {
  id: 5,
  dignity: 2,
  dignity_name: 'Kaiser',
  year: null,
  valid_from: '1950-06-01',
  valid_until: '1953-06-01',
  period_text: '1950–1953',
  person: null,
  name: 'Wilhelm Vorzeit',
  display_name: 'Wilhelm Vorzeit',
  note: '',
  companions: [],
  photo: { url: '/x', small_url: '/x?size=small' },
}

function renderApp(routes: Record<string, () => { status: number; body?: unknown }>, path: string) {
  const org = testOrg({ permissions: ['members.view', 'members.edit'] })
  const calls = fakeApi({
    [SESSION]: loggedIn,
    'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
    ...routes,
  })
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
  return calls
}

afterEach(() => {
  localStorage.clear()
})

describe('UI-Audit 29.10. Teil c', () => {
  it('NMF-02/03/10: Zeitraum, archivierte Würde und Foto bleiben beim Bearbeiten erhalten', async () => {
    const calls = renderApp(
      {
        [`GET ${base}dignities/`]: () => ({ status: 200, body: [koenig, kaiser] }),
        [`GET ${base}reigns/`]: () => ({ status: 200, body: [period] }),
        [`PUT ${base}reigns/5/`]: () => ({ status: 200, body: period }),
        [`DELETE ${base}reigns/5/photo/`]: () => ({ status: 204 }),
      },
      '/mitglieder/wuerdentraeger',
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /bearbeiten/i }))
    // Archivierte Würde bleibt sichtbar zugeordnet
    expect(screen.getByLabelText('Würde')).toHaveValue('2')
    expect(screen.getByRole('option', { name: 'Kaiser (nicht mehr verwendet)' })).toBeVisible()
    // Zeitraum statt Jahr
    expect(screen.getByLabelText(/Zeitraum der Regentschaft/)).toHaveValue('1950-06-01')
    // Beim Bearbeiten wird das Foto nach Rückfrage sofort entfernt (Autospeichern)
    await user.click(screen.getByRole('button', { name: 'Foto entfernen' }))
    expect(calls.some((c) => c.key.includes('/photo/'))).toBe(false)
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Entfernen' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === `DELETE ${base}reigns/5/photo/`)).toBe(true),
    )
    await user.type(screen.getByLabelText('Bemerkung'), 'Jubiläum')
    await user.click(screen.getByRole('button', { name: 'Schließen' }))
    await waitFor(() => expect(calls.some((c) => c.key === `PUT ${base}reigns/5/`)).toBe(true))
    const put = calls.find((c) => c.key === `PUT ${base}reigns/5/`)
    const sent = JSON.parse(String(put?.init?.body))
    expect(sent).toMatchObject({
      dignity: 2,
      year: null,
      valid_from: '1950-06-01',
      valid_until: '1953-06-01',
      note: 'Jubiläum',
    })
  })

  it('NMF-06: „nur ausgewählte“ ohne Häkchen wird erkannt', () => {
    expect(emptySelections({ departments: [], selected: ['departments'] })).toEqual(['departments'])
    expect(emptySelections({ departments: [3], selected: ['departments'] })).toEqual([])
    expect(emptySelections({ departments: [] })).toEqual([])
  })

  it('NMF-09: Ziel bleibt über Link-Anmeldung erhalten, fremde Ziele nicht', () => {
    rememberTarget({ from: '/termine?termin=4' })
    expect(rememberedTarget()).toBe('/termine?termin=4')
    expect(rememberedTarget(true)).toBe('/termine?termin=4')
    expect(rememberedTarget()).toBe('/')
    rememberTarget({ from: '//boese.example/' })
    expect(rememberedTarget()).toBe('/')
    expect(loginTarget({ from: '/anmelden/link' })).toBe('/')
  })
})
