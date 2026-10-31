import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { AppDevicesCard } from '../pages/settings/AppDevicesCard.tsx'
import type { AppDevice } from '../api/devices.ts'
import { fakeApi } from './fakeApi.ts'

const device = {
  id: 3,
  name: 'Pixel 8',
  platform: 'android',
  app_version: '1',
  push: 'none',
  created_at: '2026-10-30T05:00:00Z',
  last_seen_at: '2026-10-30T05:00:00Z',
  current: false,
}

describe('App auf dem Telefon (Mein Konto)', () => {
  it('ohne Mitgliederbereich keine Karte', async () => {
    const calls = fakeApi({})
    const { container } = render(<AppDevicesCard />)
    await new Promise((r) => setTimeout(r, 0))
    expect(container).toBeEmptyDOMElement()
    expect(calls.map((c) => c.key)).not.toContain('GET /api/app/v1/devices/')
  })

  it('QR-Code erzeugen und Gerät abmelden', async () => {
    let devices = [device]
    const calls = fakeApi({
      'GET /api/me/contexts/': () => ({ status: 200, body: { departments: [], portal: [{}] } }),
      'GET /api/app/v1/devices/': () => ({ status: 200, body: devices }),
      'POST /api/app/v1/pairing/': () => ({
        status: 201,
        body: {
          url: 'https://hubiplan.example/app/verbinden#code=abc',
          expires_at: '2026-10-30T05:10:00Z',
        },
      }),
      'DELETE /api/app/v1/devices/3/': () => {
        devices = []
        return { status: 204 }
      },
    })
    const user = userEvent.setup()
    render(<AppDevicesCard />)
    expect(await screen.findByText('Pixel 8')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'App verbinden' }))
    expect(await screen.findByText(/Mit QR-Code verbinden/)).toBeInTheDocument()
    expect(document.querySelector('svg')).not.toBeNull()

    await user.click(screen.getByRole('button', { name: 'Abmelden' }))
    await user.click(await screen.findByRole('button', { name: /OK|Ja|Bestätigen/ }))
    expect(await screen.findByText('Noch kein Gerät verbunden.')).toBeInTheDocument()
    expect(calls.map((c) => c.key)).toContain('DELETE /api/app/v1/devices/3/')
  })

  it('Verwaltung in der App sperren', async () => {
    let devices: AppDevice[] = [{ ...(device as AppDevice), admin_until: '2026-11-29T05:00:00Z' }]
    const calls = fakeApi({
      'GET /api/me/contexts/': () => ({ status: 200, body: { departments: [], portal: [{}] } }),
      'GET /api/app/v1/devices/': () => ({ status: 200, body: devices }),
      'DELETE /api/app/v1/devices/3/admin/': () => {
        devices = [{ ...(device as AppDevice), admin_until: null }]
        return { status: 200, body: devices[0] }
      },
    })
    const user = userEvent.setup()
    render(<AppDevicesCard />)
    expect(await screen.findByText(/Verwaltung freigeschaltet bis/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Verwaltung sperren' }))
    await screen.findByText('Pixel 8')
    expect(calls.map((c) => c.key)).toContain('DELETE /api/app/v1/devices/3/admin/')
    expect(screen.queryByText(/Verwaltung freigeschaltet bis/)).toBeNull()
  })

  it('zeigt nach dem Scannen, welches Gerät sich verbunden hat', async () => {
    let used = false
    const soon = new Date(Date.now() + 10 * 60_000).toISOString()
    fakeApi({
      'GET /api/me/contexts/': () => ({ status: 200, body: { departments: [], portal: [{}] } }),
      'GET /api/app/v1/devices/': () => ({ status: 200, body: used ? [device] : [] }),
      'POST /api/app/v1/pairing/': () => ({
        status: 201,
        body: {
          id: 9,
          url: 'https://hubiplan.example/app/verbinden#code=abc',
          expires_at: soon,
        },
      }),
      'GET /api/app/v1/pairing/9/': () => ({
        status: 200,
        body: { used, device: used ? 'Pixel 8' : null, expires_at: soon },
      }),
    })
    const user = userEvent.setup()
    render(<AppDevicesCard />)
    await user.click(await screen.findByRole('button', { name: 'App verbinden' }))
    expect(await screen.findByText(/Mit QR-Code verbinden/)).toBeInTheDocument()
    used = true
    expect(await screen.findByRole('status', {}, { timeout: 5000 })).toHaveTextContent(
      /Verbunden: Pixel 8\. Warst du das nicht\?/,
    )
    expect(screen.queryByText(/Mit QR-Code verbinden/)).toBeNull()
  }, 10000)

  it('fragt nach Ablauf des QR-Codes nicht weiter', async () => {
    const calls = fakeApi({
      'GET /api/me/contexts/': () => ({ status: 200, body: { departments: [], portal: [{}] } }),
      'GET /api/app/v1/devices/': () => ({ status: 200, body: [] }),
      'POST /api/app/v1/pairing/': () => ({
        status: 201,
        body: {
          id: 9,
          url: 'https://hubiplan.example/app/verbinden#code=abc',
          expires_at: '2020-01-01T00:00:00Z',
        },
      }),
      'GET /api/app/v1/pairing/9/': () => ({ status: 200, body: { used: false } }),
    })
    const user = userEvent.setup()
    render(<AppDevicesCard />)
    await user.click(await screen.findByRole('button', { name: 'App verbinden' }))
    expect(await screen.findByText(/abgelaufen/, {}, { timeout: 5000 })).toBeInTheDocument()
    expect(calls.map((c) => c.key)).not.toContain('GET /api/app/v1/pairing/9/')
  }, 10000)
})
