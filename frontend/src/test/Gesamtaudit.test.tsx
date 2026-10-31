// Gesamtaudit 25.10.2026, Paket 2 (Frontend): gewünschtes Verhalten statt der
// Fehlerproben des Audits.
import { Suspense } from 'react'
import { act, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'
import { logout } from '../api/auth.ts'
import { useLoad } from '../components/forms.ts'
import { bindUndoToUser, clearUndo, noteChange, resetUndo, undo } from '../components/undo.ts'
import { daysOf } from '../components/calendar/time.ts'
import type { Occurrence } from '../api/events.ts'
import { waitFor as waitForJob } from '../api/exchange.ts'
import { editScale } from '../components/photoCrop.ts'
import { lazyPage, preloadPages } from '../lazyPages.ts'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

afterEach(() => {
  resetUndo()
  vi.unstubAllGlobals()
})

function stacked(): number {
  return JSON.parse(sessionStorage.getItem('hubiplan-undo') ?? '{"undo":[]}').undo.length
}

describe('Gesamtaudit Frontend', () => {
  it('S1: abgelehnte Abmeldung meldet einen Fehler', async () => {
    document.cookie = 'csrftoken=probe; path=/'
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{"detail":"CSRF rejected"}', { status: 403 })),
    )
    await expect(logout()).rejects.toThrow()
  })

  it('S1: erfolgreiche Abmeldung (401 von allauth) gilt als erfolgreich', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{}', { status: 401 })),
    )
    await expect(logout()).resolves.toBeUndefined()
  })

  it('S3: Schritte gehören zum Benutzer und verschwinden beim Abmelden', () => {
    bindUndoToUser(1)
    noteChange(
      '/api/orgs/7/members/11/',
      200,
      new Headers({ 'X-Change-Set': 's1', 'X-Change-Undoable': '1', 'X-Change-Label': 'Muster' }),
    )
    expect(stacked()).toBe(1)
    bindUndoToUser(2) // anderer Benutzer im selben Tab
    expect(stacked()).toBe(0)
    noteChange(
      '/api/orgs/7/members/11/',
      200,
      new Headers({ 'X-Change-Set': 's2', 'X-Change-Undoable': '1' }),
    )
    clearUndo()
    expect(sessionStorage.getItem('hubiplan-undo')).toBeNull()
  })

  it('F2: fehlgeschlagenes Rückgängig behält den Schritt', async () => {
    document.cookie = 'csrftoken=probe; path=/'
    noteChange(
      '/api/orgs/7/members/11/',
      200,
      new Headers({ 'X-Change-Set': 'probe-set', 'X-Change-Undoable': '1' }),
    )
    expect(stacked()).toBe(1)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('offline')
      }),
    )
    const running = undo('/api/orgs/7')
    await userEvent.click(await screen.findByRole('button', { name: 'OK' }))
    await running
    expect(stacked()).toBe(1)
    // Server lehnt ab (500): Schritt bleibt ebenfalls
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{"detail":"kaputt"}', { status: 500 })),
    )
    const again = undo('/api/orgs/7')
    await userEvent.click(await screen.findByRole('button', { name: 'OK' }))
    await again
    expect(stacked()).toBe(1)
  })

  it('F3: altes Nachladen überschreibt keine neueren Daten', async () => {
    const oldReload = deferred<string>()
    let oldCalls = 0
    const { result, rerender } = renderHook(
      ({ id }) =>
        useLoad(
          () =>
            id === 1
              ? ++oldCalls === 1
                ? Promise.resolve('member 1')
                : oldReload.promise
              : Promise.resolve('member 2'),
          [id],
        ),
      { initialProps: { id: 1 } },
    )
    await waitFor(() => expect(result.current.data).toBe('member 1'))
    let reload!: Promise<void>
    act(() => {
      reload = result.current.reload()
    })
    rerender({ id: 2 })
    await waitFor(() => expect(result.current.data).toBe('member 2'))
    await act(async () => {
      oldReload.resolve('member 1')
      await reload
    })
    expect(result.current.data).toBe('member 2')
  })

  it('F7: langer Termin erscheint auch Monate nach Beginn', () => {
    const o = {
      starts_at: '2026-01-01T00:00:00+01:00',
      ends_at: '2026-03-31T00:00:00+02:00',
      all_day: true,
    } as Occurrence
    const days = daysOf(o, '2026-02-23', '2026-04-05')
    expect(days[0]).toBe('2026-02-23')
    expect(days).toContain('2026-03-15')
    expect(days[days.length - 1]).toBe('2026-03-31')
  })

  it('S2: Rollenwechsel im Editor übernimmt keine Rechte der vorigen Rolle', async () => {
    const roles = [
      {
        id: 1,
        name: 'Viele Rechte',
        description: '',
        is_board: true,
        permissions: ['members.edit'],
        assignment_count: 1,
      },
      {
        id: 2,
        name: 'Wenig Rechte',
        description: '',
        is_board: false,
        permissions: [],
        assignment_count: 1,
      },
    ]
    fakeApi({
      'GET /_allauth/browser/v1/auth/session': () => ({
        status: 200,
        body: { data: { user: testUser } },
      }),
      'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg()] }),
      'GET /api/orgs/7/roles/': () => ({ status: 200, body: roles }),
      'GET /api/orgs/7/assignments/': () => ({ status: 200, body: [] }),
      'GET /api/permissions/?org_type=club&org=7': () => ({
        status: 200,
        body: [
          {
            id: 'members',
            label: 'Mitglieder',
            permissions: [{ code: 'members.edit', label: 'Mitglieder bearbeiten' }],
          },
        ],
      }),
    })
    render(
      <MemoryRouter initialEntries={['/einstellungen/rollen']}>
        <AuthProvider>
          <OrgProvider>
            <App />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    const user = userEvent.setup()
    const high = (await screen.findByText('Viele Rechte', { selector: 'strong' })).closest('tr')!
    const low = screen.getByText('Wenig Rechte', { selector: 'strong' }).closest('tr')!
    await user.click(within(high).getByRole('button', { name: 'Bearbeiten' }))
    await user.click(within(low).getByRole('button', { name: 'Bearbeiten' }))
    expect(screen.getByLabelText('Name')).toHaveValue('Wenig Rechte')
    expect(screen.getByLabelText('Mitglieder bearbeiten')).not.toBeChecked()
  })

  it('P2: Warten auf einen Job fragt seltener nach und hört beim Verlassen auf', async () => {
    vi.useFakeTimers()
    try {
      const load = vi.fn(async () => ({ status: 'running' }))
      const controller = new AbortController()
      const running = waitForJob(load, ['running'], 600000, controller.signal)
      await vi.advanceTimersByTimeAsync(1000) // 1. Nachfrage nach 1 s
      await vi.advanceTimersByTimeAsync(1500) // 2. nach weiteren 1,5 s
      expect(load).toHaveBeenCalledTimes(3)
      controller.abort()
      await expect(running).resolves.toEqual({ status: 'running' })
      await vi.advanceTimersByTimeAsync(60000)
      expect(load).toHaveBeenCalledTimes(3)
    } finally {
      vi.useRealTimers()
    }
  })

  it('P3: riesige Bilder werden abgelehnt, große vorher verkleinert', () => {
    expect(() => editScale(10000, 10000)).toThrow(/Megapixel/)
    expect(editScale(6000, 4000)).toBe(0.5)
    expect(editScale(1200, 900)).toBe(1)
  })

  it('P1: Seiten laden erst bei Bedarf und lassen sich vorab laden', async () => {
    const load = vi.fn(async () => ({ Probe: () => <p>Probe</p> }))
    const Probe = lazyPage(load, 'Probe')
    expect(load).not.toHaveBeenCalled()
    await preloadPages()
    expect(load).toHaveBeenCalled()
    render(
      <Suspense fallback={<p>Lädt</p>}>
        <Probe />
      </Suspense>,
    )
    expect(await screen.findByText('Probe')).toBeInTheDocument()
  })
})
