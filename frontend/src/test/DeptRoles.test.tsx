import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })

type HolderInfo = { id: number; membership: number; name: string; valid_from: string }
const role = (id: number, name: string, holders: HolderInfo[]) => ({
  id,
  department: 5,
  name,
  position: id,
  permissions: [],
  holders,
})

function setup(deleteStatus = 204, permissions?: string[], selfManaged = true) {
  let roles = [
    role(8, 'Oberleutnant', [
      { id: 40, membership: 3, name: 'Christian Modellmann', valid_from: '2024-05-01' },
    ]),
    role(9, 'Fahnenträger', []),
  ]
  const calls = fakeApi({
    [SESSION]: loggedIn,
    'GET /api/me/organizations/': () => ({
      status: 200,
      body: [testOrg(permissions ? { permissions } : {})],
    }),
    'GET /api/orgs/7/departments/': () => ({
      status: 200,
      body: [
        {
          id: 5,
          name: 'Herolde',
          founding_year: 1920,
          sort_order: 0,
          is_active: true,
          fiscal_start_month: 1,
          fiscal_start_day: 1,
          logo_url: null,
          self_managed: selfManaged,
          roles,
        },
      ],
    }),
    'GET /api/permissions/?org_type=department&org=7': () => ({
      status: 200,
      body: [
        {
          id: 'dept_members',
          label: 'Mitglieder des Zugs',
          permissions: [{ code: 'dept.members.view', label: 'Mitglieder sehen' }],
        },
      ],
    }),
    'POST /api/orgs/7/department-roles/': (init) => {
      const body = JSON.parse(String(init?.body))
      roles = [...roles, { ...role(10, body.name, []), ...body }]
      return { status: 201, body: roles[roles.length - 1] }
    },
    'GET /api/orgs/7/statutes/?department=5': () => ({
      status: 200,
      body: { versions: [], publication: { is_public: false }, can_manage: true },
    }),
    'GET /api/orgs/7/members/?suche=An&status=aktiv&page_size=8': () => ({
      status: 200,
      body: {
        count: 1,
        next: null,
        previous: null,
        results: [{ id: 31, first_name: 'Anna', last_name: 'Zugmitglied', email: '' }],
      },
    }),
    'POST /api/orgs/7/members/31/department-roles/': (init) => {
      const body = JSON.parse(String(init?.body))
      roles = roles.map((r) =>
        r.id === body.role
          ? {
              ...r,
              holders: [
                ...r.holders,
                { id: 41, membership: 31, name: 'Anna Zugmitglied', valid_from: body.valid_from },
              ],
            }
          : r,
      )
      return { status: 201, body: { id: 41, ...body } }
    },
    'PATCH /api/orgs/7/members/3/department-roles/40/': () => {
      roles = roles.map((r) => (r.id === 8 ? { ...r, holders: [] } : r))
      return { status: 200, body: { id: 40 } }
    },
    'DELETE /api/orgs/7/department-roles/8/': () => {
      roles = roles.filter((r) => r.id !== 8)
      return { status: 204 }
    },
    'DELETE /api/orgs/7/department-roles/9/': () => {
      if (deleteStatus !== 204)
        return { status: deleteStatus, body: ['Die Rolle konnte nicht entfernt werden.'] }
      roles = roles.filter((r) => r.id !== 9)
      return { status: 204 }
    },
  })
  render(
    <MemoryRouter initialEntries={['/einstellungen/untereinheiten']}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
  return calls
}

describe('Abteilungsrollen entfernen', () => {
  it('hat statt „Fertig“ nur „Schließen“ oben in der Karte', async () => {
    setup()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Herolde bearbeiten' }))
    expect(await screen.findByRole('heading', { name: 'Herolde', level: 2 })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Fertig' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Schließen' }))
    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: 'Herolde', level: 2 })).not.toBeInTheDocument(),
    )
  })

  it('entfernt eine freie Rolle nach Bestätigung', async () => {
    const calls = setup()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Herolde bearbeiten' }))
    const row = (await screen.findByText('Fahnenträger')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Bearbeiten' }))
    await user.click(screen.getByRole('button', { name: 'Löschen' }))
    const dialog = await screen.findByRole('alertdialog', {
      name: 'Rolle „Fahnenträger“ entfernen?',
    })
    await user.click(within(dialog).getByRole('button', { name: 'Entfernen' }))
    expect(calls.some((c) => c.key === 'DELETE /api/orgs/7/department-roles/9/')).toBe(true)
    await waitFor(() => expect(screen.queryByText('Fahnenträger')).not.toBeInTheDocument())
  })

  it('entfernt eine vergebene Rolle auch beim Mitglied', async () => {
    const calls = setup()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Herolde bearbeiten' }))
    const row = (await screen.findAllByText('Oberleutnant'))[0].closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Bearbeiten' }))
    await user.click(screen.getByRole('button', { name: 'Löschen' }))
    const dialog = await screen.findByRole('alertdialog', {
      name: 'Rolle „Oberleutnant“ entfernen?',
    })
    expect(dialog).toHaveAccessibleDescription(/Christian Modellmann hat diese Rolle\./)
    expect(dialog).toHaveTextContent('auch bei den Mitgliedern entfernt')
    await user.click(within(dialog).getByRole('button', { name: 'Entfernen' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === 'DELETE /api/orgs/7/department-roles/8/')).toBe(true),
    )
  })

  it('zeigt einen Fehler des Servers im Dialog', async () => {
    setup(400)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Herolde bearbeiten' }))
    const row = (await screen.findByText('Fahnenträger')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Bearbeiten' }))
    await user.click(screen.getByRole('button', { name: 'Löschen' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Entfernen' }),
    )
    expect(await screen.findByText('Die Rolle konnte nicht entfernt werden.')).toBeInTheDocument()
  })

  it('legt eine Rolle mit derselben Maske wie bei Einheiten mit Mitgliedern an', async () => {
    const calls = setup()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Herolde bearbeiten' }))
    await user.click(screen.getByRole('button', { name: 'Neue Rolle' }))
    await user.type(screen.getByLabelText('Name'), 'Kassierer')
    await user.click(screen.getByText('Rechte für Zugänge (optional)'))
    await user.click(screen.getByRole('checkbox', { name: 'Mitglieder sehen' }))
    await user.click(screen.getByRole('checkbox', { name: /auf dem Briefbogen nennen/ }))
    await user.click(screen.getByRole('button', { name: 'Speichern' }))
    await screen.findByText('Kassierer')
    const post = calls.find((c) => c.key === 'POST /api/orgs/7/department-roles/')!
    expect(JSON.parse(String(post.init?.body))).toMatchObject({
      department: 5,
      name: 'Kassierer',
      permissions: ['dept.members.view'],
      on_letterhead: true,
    })
  })

  it('vergibt ein Amt ohne Konto direkt bei der Untereinheit', async () => {
    const calls = setup(204, ['members.view', 'members.edit', 'roles.manage', 'org.edit'])
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Herolde bearbeiten' }))
    const box = await screen.findByTestId('unit-holders')
    expect(within(box).getByText('Christian Modellmann')).toBeInTheDocument()
    expect(within(box).getByText(/kein Konto angelegt und keine E-Mail/)).toBeInTheDocument()
    await user.type(within(box).getByLabelText('Mitglied'), 'An')
    await user.click(await within(box).findByRole('button', { name: /Zugmitglied, Anna/ }))
    await user.selectOptions(within(box).getByLabelText('Rolle'), 'Fahnenträger')
    await user.click(within(box).getByRole('button', { name: 'Rolle zuordnen' }))
    expect(await within(box).findByText(/Anna Zugmitglied hat jetzt die Rolle/)).toBeInTheDocument()
    const post = calls.find((c) => c.key === 'POST /api/orgs/7/members/31/department-roles/')!
    expect(JSON.parse(String(post.init?.body))).toMatchObject({ role: 9 })
    // kein Zugang, keine Einladung
    expect(calls.some((c) => c.key.includes('unit-manager') || c.key.includes('access'))).toBe(
      false,
    )
  })

  it('beendet ein Amt bei der Untereinheit', async () => {
    const calls = setup(204, ['members.view', 'members.edit', 'roles.manage', 'org.edit'])
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Herolde bearbeiten' }))
    const box = await screen.findByTestId('unit-holders')
    await user.click(within(box).getByRole('button', { name: 'Beenden' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Beenden' }),
    )
    await waitFor(() =>
      expect(calls.some((c) => c.key === 'PATCH /api/orgs/7/members/3/department-roles/40/')).toBe(
        true,
      ),
    )
  })

  it('zeigt Rollen ohne Rechte als reines Amt', async () => {
    setup()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Herolde bearbeiten' }))
    expect((await screen.findAllByText('keine (nur Amt)')).length).toBe(2)
  })

  it('blendet bei von oben verwalteten Einheiten Rechte und Verwalter aus', async () => {
    setup(204, ['members.view', 'members.edit', 'roles.manage', 'org.edit'], false)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Herolde bearbeiten' }))
    expect(await screen.findByRole('checkbox', { name: /verwaltet sich selbst/ })).not.toBeChecked()
    expect(screen.queryByRole('columnheader', { name: 'Berechtigungen' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('unit-manager')).not.toBeInTheDocument()
    expect(screen.queryByText('Eigener Arbeitsbereich')).not.toBeInTheDocument()
    expect(screen.getByTestId('unit-holders')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Neue Rolle' }))
    expect(screen.queryByText('Rechte für Zugänge (optional)')).not.toBeInTheDocument()
  })
})
