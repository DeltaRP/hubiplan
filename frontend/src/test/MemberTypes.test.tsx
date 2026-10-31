import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { buildFederationTerms, buildTerms } from '../org/terms.ts'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const base = '/api/orgs/7/member-types/'
const type = (id: number, name: string, archived = false) => ({
  id,
  name,
  reported: true,
  active: false,
  counts_for_duration: true,
  is_archived: archived,
  sort_order: id,
  in_use: true,
})

function setup(types: ReturnType<typeof type>[], extra = {}) {
  return fakeApi({
    [SESSION]: () => ({ status: 200, body: { status: 200, data: { user: testUser } } }),
    'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
    [`GET ${base}`]: () => ({ status: 200, body: types }),
    ...extra,
  })
}

function renderPage() {
  render(
    <MemoryRouter initialEntries={['/einstellungen/mitgliedsarten']}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('Mitgliedsarten löschen', () => {
  it('zeigt vor dem Archivieren den Grund und archiviert', async () => {
    const calls = setup([type(1, 'aktiv'), type(2, 'passiv')], {
      [`GET ${base}2/usage/`]: () => ({
        status: 200,
        body: {
          deletable: false,
          reasons: ['in 37 Mitgliedszeiträumen verwendet'],
          is_archived: false,
        },
      }),
      [`POST ${base}2/archive/`]: () => ({ status: 200, body: type(2, 'passiv', true) }),
    })
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'passiv löschen' }))
    expect(await screen.findByText('in 37 Mitgliedszeiträumen verwendet')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Archivieren' }))
    expect(await screen.findByText('„passiv“ wurde archiviert.')).toBeInTheDocument()
    expect(calls.some((c) => c.key === `POST ${base}2/archive/`)).toBe(true)
  })

  it('löscht eine unbenutzte Art und stellt archivierte wieder her', async () => {
    const calls = setup([type(1, 'aktiv'), type(3, 'Schnupper'), type(4, 'alt', true)], {
      [`GET ${base}3/usage/`]: () => ({
        status: 200,
        body: { deletable: true, reasons: [], is_archived: false },
      }),
      [`DELETE ${base}3/`]: () => ({ status: 204 }),
      [`POST ${base}4/restore/`]: () => ({ status: 200, body: type(4, 'alt') }),
    })
    renderPage()
    const user = userEvent.setup()
    expect(await screen.findByText('Archivierte Mitgliedsarten')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Schnupper löschen' }))
    expect(await screen.findByText(/wird nirgends verwendet/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Löschen' }))
    expect(await screen.findByText('„Schnupper“ wurde gelöscht.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Wiederherstellen' }))
    expect(await screen.findByText('„alt“ ist wieder verfügbar.')).toBeInTheDocument()
    expect(calls.some((c) => c.key === `DELETE ${base}3/`)).toBe(true)
  })
})

describe('Mitgliedsarten mit Namen des Dachverbands', () => {
  it('nennt den Dachverband beim Namen', async () => {
    const org = testOrg({
      department_terms: { ...buildTerms('Zug', 'Züge', 'm'), ...buildFederationTerms('BSV') },
    })
    fakeApi({
      [SESSION]: () => ({ status: 200, body: { status: 200, data: { user: testUser } } }),
      'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
      [`GET ${base}`]: () => ({ status: 200, body: [type(1, 'aktiv')] }),
    })
    renderPage()
    expect(await screen.findByText('an den BSV melden')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'melden' })).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/Dachverband/)
  })

  it('blendet das Melden ohne Dachverband aus', async () => {
    setup([type(1, 'aktiv')])
    renderPage()
    expect(await screen.findByText(/zwei Kennzeichen/)).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'melden' })).not.toBeInTheDocument()
  })
})
