// Mitgliederbereich: wofür bin ich gemeldet (alles erfunden).
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PortalEntries } from '../pages/portal/PortalEntries.tsx'
import { fakeApi } from './fakeApi.ts'

describe('Wofür bin ich gemeldet', () => {
  it('zeigt kommende Meldungen mit Mannschaft', async () => {
    fakeApi({
      'GET /api/portal/8/entries/': () => ({
        status: 200,
        body: [
          {
            id: 1,
            title: 'Vergleichsschießen 2099',
            organizer: 'Testbund e. V.',
            date: '2099-06-12',
            location: 'Musterstadt',
            event: null,
            group: 'Hubertus I',
            position: '',
            substitute: false,
            confirmed: true,
          },
        ],
      }),
    })
    render(<PortalEntries accessId={8} />)
    expect(await screen.findByText('Vergleichsschießen 2099')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Demnächst' })).toBeVisible()
    expect(screen.getByText(/Gemeldet in Hubertus I, vom Veranstalter bestätigt/)).toBeVisible()
  })

  it('sagt, wenn nichts gemeldet ist', async () => {
    fakeApi({ 'GET /api/portal/8/entries/': () => ({ status: 200, body: [] }) })
    render(<PortalEntries accessId={8} />)
    expect(await screen.findByText(/Zurzeit bist du für nichts gemeldet/)).toBeVisible()
  })
})
