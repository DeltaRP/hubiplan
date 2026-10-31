// Einstellungen › Verbund: Untereinheit auf eigene Instanz ausgliedern (erfundene Daten).
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider, useOrg } from '../org/OrgContext.tsx'
import { PeeringPage } from '../pages/settings/PeeringPage.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const session = () => ({
  status: 200,
  body: { status: 200, data: { user: testUser, methods: [] }, meta: { is_authenticated: true } },
})

function WhenActive() {
  const { active } = useOrg()
  return active ? <PeeringPage /> : null
}

const checklist = {
  keep: [
    { key: 'privacy', label: 'Die Datenschutzhinweise des Vereins nennen die neue Instanz.' },
    { key: 'processing', label: 'Die Auftragsverarbeitung ist geregelt.' },
  ],
  move: [{ key: 'statute', label: 'Der Wechsel ist nach der Satzung beschlossen.' }],
}

const prepared = {
  id: 4,
  unit: { id: 6, name: 'Jägerzug' },
  way: 'keep',
  way_label: 'Mitglieder bleiben Vereinsmitglieder',
  cutoff: '2027-01-01',
  state: 'prepared',
  state_label: 'vorbereitet (Export und Code erstellt)',
  export_job: { id: 12, status: 'done', has_file: true },
  coupling: null,
  code_expires_at: '2026-11-30T08:00:00Z',
  created_at: '2026-10-31T08:00:00Z',
  done_at: null,
}

describe('Ausgliedern', () => {
  it('Weg, Stichtag und Prüfliste, dann Export herunterladen', async () => {
    let list: unknown[] = []
    const calls = fakeApi({
      'GET /_allauth/browser/v1/auth/session': session,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [testOrg({ type: 'club', permissions: ['peering.manage', 'data.export'] })],
      }),
      'GET /api/orgs/7/peering/': () => ({
        status: 200,
        body: {
          enabled: true,
          can_offer: true,
          can_join: false,
          instance: { base_url: 'https://verein.example', fingerprint: '1111 2222' },
          couplings: [],
        },
      }),
      'GET /api/orgs/7/peering/spin-offs/': () => ({
        status: 200,
        body: { checklist, spin_offs: list },
      }),
      'GET /api/orgs/7/departments/': () => ({
        status: 200,
        body: [
          { id: 6, name: 'Jägerzug', is_active: true, parent_unit: null, roles: [] },
          { id: 8, name: 'Schon fern', is_active: true, parent_unit: null, is_remote: true },
        ],
      }),
      'POST /api/orgs/7/peering/spin-offs/': () => {
        list = [prepared]
        return { status: 201, body: prepared }
      },
    })
    render(
      <MemoryRouter>
        <AuthProvider>
          <OrgProvider>
            <WhenActive />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    const select = await screen.findByLabelText(/^Untereinheit/)
    await screen.findByRole('option', { name: 'Jägerzug' })
    expect(screen.queryByRole('option', { name: 'Schon fern' })).toBeNull()
    await user.selectOptions(select, '6')
    await user.type(screen.getByLabelText('Stichtag'), '2027-01-01')
    const button = screen.getByRole('button', { name: 'Ausgliederung vorbereiten' })
    expect(button).toBeDisabled()
    await user.click(screen.getByLabelText(/Datenschutzhinweise/))
    await user.click(screen.getByLabelText(/Auftragsverarbeitung/))
    await user.click(button)
    await user.click(await screen.findByRole('button', { name: 'Vorbereiten' }))
    const post = calls.find((c) => c.key === 'POST /api/orgs/7/peering/spin-offs/')
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({
      unit: 6,
      way: 'keep',
      cutoff: '2027-01-01',
      checklist: { privacy: true, processing: true },
    })
    expect(await screen.findByRole('link', { name: 'Export herunterladen' })).toHaveAttribute(
      'href',
      '/api/orgs/7/datatransfer/exports/12/download/',
    )
  })

  it('Weg B: Sammelaustritt mit Vorschau', async () => {
    const done = {
      ...prepared,
      way: 'move',
      way_label: 'Mitglieder werden Mitglieder der Untereinheit',
      state: 'done',
      state_label: 'ausgegliedert',
      exited_at: null,
    }
    const calls = fakeApi({
      'GET /_allauth/browser/v1/auth/session': session,
      'GET /api/me/organizations/': () => ({
        status: 200,
        body: [
          testOrg({ type: 'club', permissions: ['peering.manage', 'data.export', 'members.edit'] }),
        ],
      }),
      'GET /api/orgs/7/peering/': () => ({
        status: 200,
        body: {
          enabled: true,
          can_offer: true,
          can_join: false,
          instance: { base_url: 'https://verein.example', fingerprint: '1111 2222' },
          couplings: [],
        },
      }),
      'GET /api/orgs/7/peering/spin-offs/': () => ({
        status: 200,
        body: { checklist, spin_offs: [done] },
      }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
      'GET /api/orgs/7/peering/spin-offs/4/exit/': () => ({
        status: 200,
        body: {
          members: [
            { id: 1, name: 'Muster, Erika', also_in: [] },
            { id: 2, name: 'Berg, Bernd', also_in: ['Tambourcorps'] },
          ],
        },
      }),
      'POST /api/orgs/7/peering/spin-offs/4/exit/': () => ({
        status: 200,
        body: { ...done, exited_at: '2026-10-31T09:00:00Z', exited_count: 1 },
      }),
    })
    render(
      <MemoryRouter>
        <AuthProvider>
          <OrgProvider>
            <WhenActive />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Sammelaustritt vorbereiten' }))
    expect(
      await screen.findByLabelText(/Berg, Bernd bleibt \(auch in Tambourcorps\)/),
    ).toBeChecked()
    expect(screen.getByLabelText(/Muster, Erika bleibt/)).not.toBeChecked()
    await user.click(screen.getByRole('button', { name: 'Sammelaustritt ausführen' }))
    await user.click(await screen.findByRole('button', { name: 'Austritt erfassen' }))
    const post = calls.find((c) => c.key === 'POST /api/orgs/7/peering/spin-offs/4/exit/')
    expect(JSON.parse(String(post?.init?.body))).toEqual({ exclude: [2] })
  })
})
