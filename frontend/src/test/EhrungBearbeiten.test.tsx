import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { HonoraryAwards } from '../pages/members/HonoraryAwards.tsx'
import { fakeApi } from './fakeApi.ts'

const award = {
  id: 3,
  title: 1,
  title_name: 'Ehrenmitglied',
  fee_text: 'beitragsfrei',
  owner_name: 'Testverein',
  valid_from: '2026-10-29',
  valid_until: null,
  note: '',
}

describe('Ehrung nachträglich bearbeiten (Ralf 31.10.)', () => {
  it('ändert Beginn und Bemerkung einer Verleihung', async () => {
    const calls = fakeApi({
      'GET /api/orgs/7/honorary-titles/': () => ({
        status: 200,
        body: [{ id: 1, name: 'Ehrenmitglied', is_archived: false }],
      }),
      'PATCH /api/orgs/7/members/9/honorary-titles/3/': () => ({
        status: 200,
        body: { ...award, valid_from: '1998-05-01', note: 'Generalversammlung' },
      }),
    })
    const changed = vi.fn()
    render(<HonoraryAwards orgId={7} memberId={9} awards={[award]} canEdit onChanged={changed} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Ehrenmitglied bearbeiten' }))
    const form = screen.getByRole('form', { name: 'Ehrenmitglied bearbeiten' })
    const from = within(form).getByLabelText('ab')
    await user.clear(from)
    await user.type(from, '1998-05-01')
    await user.type(within(form).getByLabelText('Bemerkung'), 'Generalversammlung')
    await user.click(within(form).getByRole('button', { name: 'Speichern' }))
    await vi.waitFor(() => expect(changed).toHaveBeenCalled())
    const patch = calls.find((c) => c.key.startsWith('PATCH'))!
    expect(JSON.parse(String(patch.init?.body))).toEqual({
      title: 1,
      valid_from: '1998-05-01',
      valid_until: null,
      note: 'Generalversammlung',
    })
    expect(screen.queryByRole('form', { name: 'Ehrenmitglied bearbeiten' })).toBeNull()
  })

  it('zeigt bei „nur Jahr der Verleihung“ nur das Jahr', async () => {
    const nadel = { ...award, title_name: 'Ehrennadel', year_only: true, valid_from: '1998-01-01' }
    const calls = fakeApi({
      'GET /api/orgs/7/honorary-titles/': () => ({
        status: 200,
        body: [{ id: 1, name: 'Ehrennadel', is_archived: false, year_only: true }],
      }),
      'PATCH /api/orgs/7/members/9/honorary-titles/3/': () => ({
        status: 200,
        body: { ...nadel, valid_from: '2001-01-01' },
      }),
    })
    const changed = vi.fn()
    render(<HonoraryAwards orgId={7} memberId={9} awards={[nadel]} canEdit onChanged={changed} />)
    expect(screen.getByText(/verliehen 1998/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'beenden' })).toBeNull()
    const user = userEvent.setup()
    await screen.findByRole('option', { name: 'Ehrennadel' })
    await user.click(screen.getByRole('button', { name: 'Ehrennadel bearbeiten' }))
    const form = screen.getByRole('form', { name: 'Ehrennadel bearbeiten' })
    expect(within(form).queryByLabelText('bis (optional)')).toBeNull()
    const year = within(form).getByLabelText('Jahr der Verleihung')
    await user.clear(year)
    await user.type(year, '2001')
    await user.click(within(form).getByRole('button', { name: 'Speichern' }))
    await vi.waitFor(() => expect(changed).toHaveBeenCalled())
    const patch = calls.find((c) => c.key.startsWith('PATCH'))!
    expect(JSON.parse(String(patch.init?.body))).toMatchObject({
      valid_from: '2001-01-01',
      valid_until: null,
    })
  })
})
