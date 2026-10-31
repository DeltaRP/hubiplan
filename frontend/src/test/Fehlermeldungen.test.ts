import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api, requestBlob, retry } from '../api/client.ts'

const nginx502 =
  '<html>\r\n<head><title>502 Bad Gateway</title></head>\r\n<body>\r\n' +
  '<center><h1>502 Bad Gateway</h1></center>\r\n<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n'

function respond(status: number, text: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(text, { status })),
  )
}

async function fehler(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (err) {
    return err as ApiError
  }
  throw new Error('kein Fehler')
}

describe('Fehlermeldungen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('zeigt bei einer HTML-Fehlerseite des Proxys einen verständlichen Satz', async () => {
    respond(502, nginx502)
    const err = await fehler(api.get('/api/x/'))
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(502)
    expect(err.message).toMatch(/Server ist gerade nicht erreichbar/)
    expect(err.message).not.toMatch(/</)
  })

  it('gilt auch beim Speichern (CSRF-Abruf scheitert ebenfalls mit 502)', async () => {
    document.cookie = 'csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
    respond(502, nginx502)
    const err = await fehler(api.post('/api/x/', { name: 'Hubertuskönig' }))
    expect(err).toBeInstanceOf(ApiError)
    expect(err.message).toMatch(/Server ist gerade nicht erreichbar/)
  })

  it('gilt auch für Dateiabrufe', async () => {
    respond(504, '<html><body>Gateway Time-out</body></html>')
    const err = await fehler(requestBlob('GET', '/api/x.pdf'))
    expect(err.message).toMatch(/Server ist gerade nicht erreichbar/)
  })

  it('meldet fehlende Verbindung verständlich', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )
    const err = await fehler(api.get('/api/x/'))
    expect(err).toBeInstanceOf(ApiError)
    expect(err.message).toMatch(/Keine Verbindung zum Server/)
  })

  it('übernimmt Meldungen aus JSON weiterhin', async () => {
    respond(400, JSON.stringify({ name: ['Diese Würde gibt es schon.'] }))
    const err = await fehler(api.get('/api/x/'))
    expect(err.message).toBe('Diese Würde gibt es schon.')
    expect(err.fieldErrors.name).toBe('Diese Würde gibt es schon.')
  })

  describe('automatische Wiederholung (z. B. während des Ausrollens)', () => {
    afterEach(() => {
      retry.delays = []
    })

    function sequence(...answers: (() => Response)[]) {
      const fn = vi.fn(async () => {
        const next = answers.shift()
        if (!next) throw new Error('zu viele Aufrufe')
        return next()
      })
      vi.stubGlobal('fetch', fn)
      return fn
    }
    const gateway = () =>
      new Response(nginx502, { status: 502, headers: { 'Content-Type': 'text/html' } })
    const ok = () =>
      new Response(JSON.stringify({ id: 5 }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      })

    it('liest nach kurzer Pause erneut, wenn der Server kurz weg war', async () => {
      retry.delays = [0, 0, 0]
      const fn = sequence(
        gateway,
        () => {
          throw new TypeError('Failed to fetch')
        },
        ok,
      )
      await expect(api.get('/api/x/')).resolves.toEqual({ id: 5 })
      expect(fn).toHaveBeenCalledTimes(3)
    })

    it('wiederholt Anlegen mit Idempotency-Key', async () => {
      retry.delays = [0]
      document.cookie = 'csrftoken=t'
      const fn = sequence(gateway, ok)
      await expect(api.post('/api/x/', { a: 1 }, 'k')).resolves.toEqual({ id: 5 })
      expect(fn).toHaveBeenCalledTimes(2)
    })

    it('wiederholt Anlegen ohne Schlüssel nicht (sonst womöglich doppelt)', async () => {
      retry.delays = [0, 0]
      document.cookie = 'csrftoken=t'
      const fn = sequence(gateway, ok)
      const err = await fehler(api.post('/api/x/', { name: 'Hubertuskönig' }))
      expect(err.status).toBe(502)
      expect(fn).toHaveBeenCalledTimes(1)
    })

    it('wiederholt eigene JSON-Antworten des Backends nicht', async () => {
      retry.delays = [0, 0]
      const fn = sequence(
        () =>
          new Response(JSON.stringify({ detail: 'Wartung.' }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          }),
        ok,
      )
      const err = await fehler(api.get('/api/x/'))
      expect(err.message).toBe('Wartung.')
      expect(fn).toHaveBeenCalledTimes(1)
    })

    it('gibt nach der letzten Wiederholung die verständliche Meldung', async () => {
      retry.delays = [0, 0]
      const fn = sequence(gateway, gateway, gateway)
      const err = await fehler(api.get('/api/x/'))
      expect(err.message).toMatch(/Server ist gerade nicht erreichbar/)
      expect(fn).toHaveBeenCalledTimes(3)
    })
  })
})
