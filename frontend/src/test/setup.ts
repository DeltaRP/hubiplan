import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach, beforeAll, vi } from 'vitest'
import { retry } from '../api/client.ts'
import { preloadPages } from '../lazyPages.ts'
import '../App.tsx'

// jsdom misst nichts; der Texteditor (ProseMirror) fragt beim Scrollen nach Rechtecken
if (!('getClientRects' in Range.prototype)) {
  Object.assign(Range.prototype, {
    getClientRects: () => [] as unknown as DOMRectList,
    getBoundingClientRect: () => new DOMRect(),
  })
}

// Zwei Testläufe teilen sich auf Ralfs PC die Kerne; unter Last braucht das Rendern
// länger als die üblichen 1 s, die findBy… und waitFor warten.
configure({ asyncUtilTimeout: 5000 })

// Seiten werden erst bei Bedarf geladen; in Tests vorab, damit nichts auf das Laden wartet
beforeAll(async () => {
  // Keine automatischen Wiederholungen: Tests erwarten Fehler sofort
  retry.delays = []
  await preloadPages()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  // gemerkte Ansichten (z. B. Kalender) nicht in den nächsten Test mitnehmen
  try {
    localStorage.clear()
    sessionStorage.clear()
  } catch {
    // ohne Speicher
  }
  document.cookie = 'csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
})
