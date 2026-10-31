import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })

const context = {
  key: 'org:7',
  organization: { id: 7, name: 'TV Beispielhausen', type: 'club' },
  units: [
    {
      id: 7,
      name: 'TV Beispielhausen',
      is_self: true,
      contact: { email: 'info@tv.example.org', phone: '0123 4' },
    },
    { id: 9, name: 'Jägerzug', is_self: false, contact: { email: '', phone: '' } },
  ],
  functions: [{ key: 'role:3', name: 'Kassierer', contact_email: 'kasse@tv.example.org' }],
  name: 'Karla Kasse',
  own: { email: 'karla.privat@example.org', phone: '0170 1', address: ['Weg 1', '12345 Ort'] },
}

const letterhead = {
  organization: { id: 7, name: 'TV Beispielhausen', type: 'club' },
  letterhead: {
    mode: 'own',
    form: 'b',
    logo_position: 'right',
    tagline: 'gegründet 1900',
    font: 'Arial',
    salutation: 'Sehr geehrte Damen und Herren,',
    closing: 'Mit freundlichen Grüßen',
    show_bank: true,
    account: null,
    show_email: true,
    show_phone: true,
    show_website: true,
    show_board: true,
    show_register: true,
    show_social: false,
    updated_at: '2026-10-28T10:00:00Z',
  },
  may_have_own: true,
  owner: { id: 7, name: 'TV Beispielhausen', is_self: true },
  accounts: [{ id: 1, name: 'Girokonto', iban: 'DE89 3704', bank: 'Musterbank' }],
  board: [{ name: 'Vera Vorsitz', role: '1. Vorsitzende' }],
  hints: [],
}

function show(path: string, routes: Parameters<typeof fakeApi>[0]) {
  const calls = fakeApi({
    [SESSION]: loggedIn,
    'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
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

beforeEach(() => {
  Object.defineProperty(URL, 'createObjectURL', { value: vi.fn(() => 'blob:x'), writable: true })
  Object.defineProperty(URL, 'revokeObjectURL', { value: vi.fn(), writable: true })
})

describe('Briefvorlage erstellen', () => {
  it('wählt private Angaben nie vor und lädt mit den gewählten Kontaktwegen', async () => {
    const calls = show('/briefvorlage', {
      'GET /api/me/letterheads/': () => ({
        status: 200,
        body: { contexts: [context], choices: [], notices: [] },
      }),
      'POST /api/me/letterheads/download/': () => ({ status: 200, body: 'PK' }),
    })
    const user = userEvent.setup()
    const unitBox = await screen.findByRole('checkbox', { name: /Kontakt der Einheit/ })
    expect(unitBox).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Funktionsadresse/ })).toBeChecked()
    const privateMail = screen.getByRole('checkbox', { name: /Meine E-Mail-Adresse/ })
    expect(privateMail).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Meine Telefonnummer/ })).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Meine Anschrift/ })).not.toBeChecked()
    await user.click(privateMail)
    expect(screen.getByText(/Deine privaten Angaben stehen dann/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Herunterladen' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === 'POST /api/me/letterheads/download/')).toBe(true),
    )
    const sent = calls.find((c) => c.key === 'POST /api/me/letterheads/download/')!
    const body = sent.init!.body as FormData
    expect(body.get('contacts')).toBe('unit,role,own_email')
    expect(body.get('unit')).toBe('7')
    expect(body.get('format')).toBe('dotx')
    expect(await screen.findByText(/Die Vorlage ist heruntergeladen/)).toBeInTheDocument()
  })

  it('sagt ohne Funktion, wer Vorlagen erstellt', async () => {
    show('/briefvorlage', {})
    expect(await screen.findByText(/Du hast gerade keine solche Funktion/)).toBeInTheDocument()
  })

  it('zeigt auf der Startseite den Hinweis „veraltet“ und blendet ihn aus', async () => {
    let notices = [
      {
        kind: 'outdated',
        unit: { id: 7, name: 'TV Beispielhausen' },
        context: 'org:7',
        changes: ['Bankverbindung'],
      },
    ]
    const calls = show('/', {
      'GET /api/me/letterheads/': () => ({
        status: 200,
        body: { contexts: [context], choices: [], notices },
      }),
      'POST /api/me/letterheads/dismiss/': () => {
        notices = []
        return { status: 204 }
      },
    })
    const user = userEvent.setup()
    expect(
      await screen.findByText(/Deine Briefvorlage für TV Beispielhausen ist veraltet/),
    ).toHaveTextContent('Bankverbindung geändert')
    await user.click(screen.getByRole('button', { name: 'Später' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === 'POST /api/me/letterheads/dismiss/')).toBe(true),
    )
    await waitFor(() => expect(screen.queryByText(/ist veraltet/)).not.toBeInTheDocument())
  })
})

describe('Einstellungen › Briefbogen', () => {
  it('speichert Änderungen automatisch und zeigt den Vorstand', async () => {
    const calls = show('/einstellungen/briefbogen', {
      'GET /api/orgs/7/letterhead/': () => ({ status: 200, body: letterhead }),
      'GET /api/orgs/7/letterhead/preview/': () => ({ status: 200, body: '%PDF' }),
      'PATCH /api/orgs/7/letterhead/': (init) => ({
        status: 200,
        body: {
          ...letterhead,
          letterhead: { ...letterhead.letterhead, ...JSON.parse(String(init?.body)) },
        },
      }),
    })
    const user = userEvent.setup()
    expect(await screen.findByText(/Heute: Vera Vorsitz \(1\. Vorsitzende\)/)).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText(/^Schriftart/), 'Georgia')
    await waitFor(
      () => {
        const patch = calls.find((c) => c.key === 'PATCH /api/orgs/7/letterhead/')
        expect(patch && JSON.parse(String(patch.init?.body))).toEqual({ font: 'Georgia' })
      },
      { timeout: 3000 },
    )
    expect(await screen.findByTitle('Vorschau der ersten Seite')).toBeInTheDocument()
    expect(screen.getByTitle('Vorschau der ersten Seite')).toHaveAttribute(
      'src',
      'blob:x#view=Fit&zoom=page-fit',
    )
  })
})
