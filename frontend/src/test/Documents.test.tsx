import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const base = '/api/orgs/7/documents/'

function renderApp(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

const version = (id: number, name: string) => ({
  id,
  name,
  size: 4096,
  content_type: 'application/pdf',
  uploaded_at: '2026-02-15T10:00:00Z',
  uploaded_by: 'Hanna Hubertus',
  url: `${base}versions/${id}/`,
  inline: true,
})

const doc = (id: number, title: string, note = '') => ({
  id,
  folder: 1,
  title,
  date: '2026-02-14',
  note,
  created_at: '2026-02-15T10:00:00Z',
  created_by: 'Hanna Hubertus',
  current: version(id * 10, `${title}.pdf`),
  version_count: 2,
  versions: [version(id * 10, `${title}.pdf`), version(id * 10 + 1, 'alt.pdf')],
})

const overview = (canManage = true) => ({
  folders: [
    {
      id: 1,
      name: 'Protokolle',
      visibility: 'board',
      visibility_label: 'nur Vorstand',
      shared_up: false,
      documents: [doc(1, 'Jahreshauptversammlung', 'mit Neuwahlen'), doc(2, 'Vorstandssitzung')],
      public_url: null,
    },
  ],
  can_manage: canManage,
  visibilities: [
    { value: 'board', label: 'nur Vorstand' },
    { value: 'members', label: 'alle Mitglieder' },
    { value: 'public', label: 'öffentlich per Link' },
  ],
  used_bytes: 3 * 1024 * 1024,
  trash_count: 1,
  share_up_label: 'Für den Dachverband freigeben (nur lesen)',
  org_kind: 'club',
  from_below: [
    {
      id: 12,
      name: 'Zugprotokolle',
      visibility: 'board',
      visibility_label: 'nur Vorstand',
      shared_up: true,
      documents: [{ ...doc(4, 'Zugversammlung'), folder: 12 }],
      from: 'Jägerzug',
    },
  ],
  shared: [
    {
      id: 9,
      name: 'Rundschreiben',
      visibility: 'clubs',
      visibility_label: 'Vereine des Dachverbands',
      shared_up: false,
      documents: [{ ...doc(3, 'Meldebogen'), folder: 9 }],
      from: 'Testbund',
    },
  ],
})

function setup(perms: string[], extra = {}) {
  return fakeApi({
    [SESSION]: () => ({ status: 200, body: { status: 200, data: { user: testUser } } }),
    'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg({ permissions: perms })] }),
    [`GET ${base}`]: () => ({ status: 200, body: overview(perms.includes('docs.manage')) }),
    'GET /api/orgs/7/statutes/': () => ({
      status: 200,
      body: {
        versions: [],
        publication: { is_public: false, pdf_url: null, info_url: null },
        can_manage: false,
      },
    }),
    ...extra,
  })
}

describe('Dokumente', () => {
  it('zeigt Ordner, Freigaben des Dachverbands, Platz und sucht in Titel und Bemerkung', async () => {
    setup(['docs.view', 'docs.manage'])
    renderApp('/dokumente')
    const nav = within(await screen.findByRole('navigation', { name: 'Module' }))
    expect(await nav.findByRole('link', { name: 'Dokumente' })).toBeInTheDocument()
    expect(await screen.findByText('Jahreshauptversammlung')).toBeInTheDocument()
    expect(screen.getByText(/Belegter Platz: 3,0 MB · 1 im Papierkorb/)).toBeInTheDocument()
    // „Satzung“ steht als Ordner und, sobald geladen, auch als Satzungsbereich auf der Seite
    expect(screen.getAllByText('Satzung').length).toBeGreaterThan(0)
    expect(screen.getByText('Vom Dachverband')).toBeInTheDocument()
    expect(screen.getByText('von Testbund')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Papierkorb' })).toBeInTheDocument()
    expect(screen.getByText('Von den Abteilungen')).toBeInTheDocument()
    expect(screen.getByText('von Jägerzug')).toBeInTheDocument()

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Suchen (Titel und Bemerkung, alle Ordner)'), 'neuwahl')
    expect(screen.getByText('Jahreshauptversammlung')).toBeInTheDocument()
    expect(screen.queryByText('Vorstandssitzung')).not.toBeInTheDocument()
    expect(screen.queryByText('Meldebogen')).not.toBeInTheDocument()
  })

  it('legt einen Ordner an und lädt hoch', async () => {
    const calls = setup(['docs.view', 'docs.manage'], {
      [`POST ${base}folders/`]: () => ({ status: 201, body: {} }),
      [`POST ${base}folders/1/documents/`]: () => ({ status: 201, body: {} }),
    })
    renderApp('/dokumente')
    await screen.findByText('Jahreshauptversammlung')
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Name'), 'Formulare')
    await user.selectOptions(screen.getAllByLabelText('Sichtbar für').at(-1)!, 'members')
    const shareBoxes = screen.getAllByLabelText('Für den Dachverband freigeben (nur lesen)')
    await user.click(shareBoxes.at(-1)!)
    await user.click(screen.getByRole('button', { name: 'Ordner anlegen' }))
    expect(await screen.findByText('Der Ordner wurde angelegt.')).toBeInTheDocument()
    const post = calls.find((c) => c.key === `POST ${base}folders/`)
    expect(JSON.parse(String(post?.init?.body))).toEqual({
      name: 'Formulare',
      visibility: 'members',
      shared_up: true,
    })

    const file = new File(['%PDF-1.4'], 'Einladung.pdf', { type: 'application/pdf' })
    await user.click(screen.getByText('Protokolle'))
    await user.upload(screen.getByLabelText('Datei für Protokolle'), file)
    await user.click(screen.getByRole('button', { name: 'Hochladen' }))
    expect(await screen.findByText('Das Dokument wurde hochgeladen.')).toBeInTheDocument()
    const upload = calls.find((c) => c.key === `POST ${base}folders/1/documents/`)
    const form = upload?.init?.body as FormData
    expect(form.get('title')).toBe('Einladung')
  })

  it('nur lesen: keine Verwaltung, kein Papierkorb', async () => {
    setup(['docs.view'])
    renderApp('/dokumente')
    await screen.findByText('Jahreshauptversammlung')
    expect(screen.queryByRole('button', { name: 'Ordner anlegen' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Papierkorb' })).not.toBeInTheDocument()
    expect(screen.queryByText('Neue Fassung')).not.toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Ansehen' }).length).toBeGreaterThan(0)
  })

  it('ohne Recht erscheint der Bereich nicht', async () => {
    setup(['members.view'])
    renderApp('/')
    const nav = within(await screen.findByRole('navigation', { name: 'Module' }))
    expect(await nav.findByRole('link', { name: 'Startseite' })).toBeInTheDocument()
    expect(nav.queryByRole('link', { name: 'Dokumente' })).not.toBeInTheDocument()
  })
})
