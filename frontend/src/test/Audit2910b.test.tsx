// Gesamtaudit 29.10.2026, Teil b (Frontend): 2FA-Ladefehler, Rückgängig nach dem
// Abmelden.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getTotp } from '../api/auth.ts'
import { request } from '../api/client.ts'
import { bindUndoToUser, clearUndo, resetUndo } from '../components/undo.ts'

afterEach(() => {
  resetUndo()
  vi.unstubAllGlobals()
})

function stacked(): number {
  return JSON.parse(sessionStorage.getItem('hubiplan-undo') ?? '{"undo":[]}').undo.length
}

describe('Gesamtaudit 29.10. Teil b', () => {
  it('FE-F01: Fehler beim Laden der 2FA ist kein „nicht eingerichtet“', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{}', { status: 403 })),
    )
    await expect(getTotp()).rejects.toThrow()
  })

  it('FE-F01: 404 heißt „nicht eingerichtet“', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response('{"meta":{"secret":"ABC","totp_url":"otpauth://x"}}', { status: 404 }),
      ),
    )
    await expect(getTotp()).resolves.toEqual({
      active: false,
      secret: 'ABC',
      totpUrl: 'otpauth://x',
    })
  })

  it('AUD-FE-S3: späte Antwort nach dem Abmelden legt keinen Schritt an', async () => {
    document.cookie = 'csrftoken=probe; path=/'
    let finish!: () => void
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            finish = () =>
              resolve(
                new Response('{}', {
                  status: 200,
                  headers: {
                    'X-Change-Set': 'alt',
                    'X-Change-Undoable': '1',
                    'X-Change-Label': 'Muster',
                  },
                }),
              )
          }),
      ),
    )
    bindUndoToUser(1)
    const pending = request('PATCH', '/api/orgs/7/members/11/', { x: 1 })
    await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
    clearUndo()
    finish()
    await pending
    expect(stacked()).toBe(0)
    // Auch ohne Besitzer gespeicherte Schritte bekommt der nächste Benutzer nicht
    sessionStorage.setItem(
      'hubiplan-undo',
      JSON.stringify({ undo: [{ base: '/api/orgs/7', setId: 'x', label: 'y' }], redo: [] }),
    )
    sessionStorage.removeItem('hubiplan-undo-user')
    bindUndoToUser(2)
    expect(stacked()).toBe(0)
  })
})
