import { vi } from 'vitest'

// Standardantworten, falls ein Test sie nicht selbst festlegt
const DEFAULTS: Record<string, Handler> = {
  'GET /api/me/organizations/': () => ({ status: 200, body: [] }),
  'GET /api/me/contexts/': () => ({ status: 200, body: { departments: [], portal: [] } }),
  // Verbund: ohne eigene Angabe keine Anmeldung über andere Instanzen
  'GET /api/peering/sso/choices/': () => ({ status: 200, body: [] }),
  'GET /api/peering/sso/account/': () => ({
    status: 200,
    body: { login_enabled: false, links: [], linkable: [], accounts: [] },
  }),
  // Briefvorlage: ohne eigene Angabe keine Funktion und keine Hinweise
  'GET /api/me/letterheads/': () => ({
    status: 200,
    body: { contexts: [], choices: [], notices: [] },
  }),
  // Hinterlegte Unterschrift (Quittungen): ohne eigene Angabe keine
  'GET /api/me/signature/': () => ({ status: 200, body: { signature: null, updated_at: null } }),
  // Sprache: ohne eigene Angabe nur Deutsch (kein Umschalter)
  'GET /api/me/language/': () => ({
    status: 200,
    body: { languages: [{ code: 'de', name: 'Deutsch' }], default: 'de', language: 'de' },
  }),
  'GET /api/public/languages/': () => ({
    status: 200,
    body: { languages: [{ code: 'de', name: 'Deutsch' }], default: 'de' },
  }),
  // Lernhilfen: ohne eigene Angabe ausgeschaltet (Abwägungen bleiben sichtbar)
  'GET /api/me/learning/': () => ({
    status: 200,
    body: { learning_aids: false, learning_hidden: [] },
  }),
}

type Handler = (init: RequestInit | undefined) => {
  status: number
  body?: unknown
  headers?: Record<string, string>
}

/** Ersetzt fetch durch eine Tabelle "METHODE URL" -> Antwort. */
export function fakeApi(routes: Record<string, Handler>) {
  document.cookie = 'csrftoken=test-token'
  const calls: { key: string; init?: RequestInit }[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const key = `${init?.method ?? 'GET'} ${String(input)}`
    calls.push({ key, init })
    const handler =
      routes[key] ??
      DEFAULTS[key] ??
      // Jubiläen von Einheiten und Geburtstage: ohne eigene Angabe leer
      (/^GET \/api\/orgs\/\d+\/(unit-jubilees|birthdays)\//.test(key)
        ? () => ({ status: 200, body: { von: '', bis: '', results: [] } })
        : // Impressum: ohne eigene Angabe vollständig (kein Hinweis auf der Startseite)
          /^GET \/api\/orgs\/\d+\/imprint\/$/.test(key)
          ? () => ({ status: 200, body: { missing: [] } })
          : // Social-Media-Kanäle: ohne eigene Angabe keine
            /^GET \/api\/orgs\/\d+\/social-links\/$/.test(key)
            ? () => ({ status: 200, body: [] })
            : // Offene Aufgaben: ohne eigene Angabe keine
              /^GET \/api\/orgs\/\d+\/open-tasks\/$/.test(key)
              ? () => ({ status: 200, body: { items: [] } })
              : // Beitragsordnung, Gründungsurkunde (optional): ohne eigene Angabe keine
                /^GET \/api\/orgs\/\d+\/statutes\/\?(department=\d+&)?kind=(fee_rules|founding_deed)$/.test(
                    key,
                  )
                ? () => ({
                    status: 200,
                    body: {
                      kind: key.endsWith('founding_deed') ? 'founding_deed' : 'fee_rules',
                      versions: [],
                      publication: { is_public: false, pdf_url: null, info_url: null },
                      can_manage: false,
                    },
                  })
                : undefined)
    if (!handler) throw new Error(`Unerwarteter Aufruf: ${key}`)
    const { status, body, headers } = handler(init)
    // 204 darf keinen Inhalt haben
    const text = body === undefined ? (status === 204 ? null : '') : JSON.stringify(body)
    return new Response(text, { status, headers })
  })
  return calls
}

export const testUser = { id: 1, email: 'kassenwart@example.org', display: 'Karla' }

export function testOrg(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    name: 'TV Beispielhausen',
    type: 'club',
    type_label: 'Verein',
    parent_name: 'Testbund',
    permissions: ['members.view', 'roles.manage', 'org.edit'],
    modules: ['members'],
    department_label: 'Abteilung',
    department_label_plural: 'Abteilungen',
    theme: {
      primary: '#123e7a',
      on_primary: '#ffffff',
      accent: '#e0a526',
      on_accent: '#1d2421',
      logo_url: null,
      inherited_from: { colors: 'TV Beispielhausen', logo: null },
    },
    ...overrides,
  }
}
