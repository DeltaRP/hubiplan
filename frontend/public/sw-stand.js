// Offline-Speicher nur für den Standmodus (Schießstände im Keller, Ralf 2026-11-01).
// - Seiten unter /stand/: erst das Netz, ohne Netz die zuletzt gemerkte Seite.
// - Dateien unter /assets/ (Name enthält eine Prüfsumme, ändern sich also nie): aus dem Speicher.
// Alles andere, vor allem /api/, geht unverändert ans Netz.
const CACHE = 'hubiplan-stand-v1'
const SHELL = '/stand-seite'

self.addEventListener('install', () => self.skipWaiting())

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k.startsWith('hubiplan-stand-') && k !== CACHE)
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('message', (event) => {
  const data = event.data || {}
  if (data.type !== 'merken') return
  event.waitUntil(
    caches.open(CACHE).then(async (cache) => {
      if (typeof data.page === 'string' && data.page.startsWith('/stand/')) {
        const res = await fetch(data.page, { credentials: 'same-origin' }).catch(() => null)
        if (res && res.ok) await cache.put(SHELL, res)
      }
      const keep = new Set()
      for (const url of Array.isArray(data.assets) ? data.assets.slice(0, 200) : []) {
        if (typeof url !== 'string' || !url.startsWith('/assets/')) continue
        keep.add(url)
        if (await cache.match(url)) continue
        const res = await fetch(url).catch(() => null)
        if (res && res.ok) await cache.put(url, res)
      }
      // Dateien älterer Fassungen entfernen, damit der Speicher nicht wächst
      if (keep.size) {
        for (const req of await cache.keys()) {
          const path = new URL(req.url).pathname
          if (path.startsWith('/assets/') && !keep.has(path)) await cache.delete(req)
        }
      }
    }),
  )
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return
  if (req.mode === 'navigate' && url.pathname.startsWith('/stand/')) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone()
            caches.open(CACHE).then((c) => c.put(SHELL, copy))
          }
          return res
        })
        .catch(() => caches.match(SHELL).then((hit) => hit || Response.error())),
    )
    return
  }
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            if (res.ok && url.pathname.startsWith('/assets/')) {
              const copy = res.clone()
              caches.open(CACHE).then((c) => c.put(req, copy))
            }
            return res
          }),
      ),
    )
  }
})
