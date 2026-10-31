import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { InstanceKeysBox } from '../pages/platform/PlatformPages.tsx'
import type { InstanceKeys } from '../api/peering.ts'
import { fakeApi } from './fakeApi.ts'

const keys: InstanceKeys = {
  fingerprint: '1111 2222 3333',
  created: '2026-01-01T00:00:00Z',
  rotated_at: null,
  previous_until: null,
  emergency: false,
  next_rotation: '2027-01-01T00:00:00Z',
  peers: [{ base_url: 'https://verband.example', knows_current: false }],
}

describe('Schlüssel der Instanz (Plattform)', () => {
  it('Wechsel erst nach Eintippen des Bestätigungsworts', async () => {
    const calls = fakeApi({
      'POST /api/platform/peering/keys/': () => ({ status: 200, body: keys }),
    })
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<InstanceKeysBox keys={keys} onChange={onChange} />)
    expect(screen.getByText(/Kennen den aktuellen Schlüssel noch nicht/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Notfallwechsel …' }))
    const run = screen.getByRole('button', { name: 'Notfallwechsel ausführen' })
    expect(run).toBeDisabled()
    await user.type(screen.getByLabelText('Bestätigung'), 'notfall')
    await user.click(run)
    const call = calls.find((c) => c.key === 'POST /api/platform/peering/keys/')
    expect(JSON.parse(String(call?.init?.body))).toEqual({ mode: 'emergency', confirm: 'notfall' })
    expect(onChange).toHaveBeenCalled()
  })
})
