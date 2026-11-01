// Hilfe (konzepte/hilfe-funktion.md, docs/hilfe.md): Dateien, Übersetzung, Bilder, Oberfläche.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import axe from 'axe-core'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { PERM } from '../api/orgs.ts'
import { DEPT_PERM } from '../api/portal.ts'
import { AuthProvider } from '../auth/AuthContext.tsx'
import {
  AREAS,
  guidesFor,
  imagesIn,
  pageHelpFor,
  parseHelpFile,
  relName,
  visibleFor,
} from '../help/content.ts'
import type { HelpEntry } from '../help/content.ts'
import { highlight, labelsIn } from '../help/extras.ts'
import { renderHelp } from '../help/markdown.ts'
import SPEC from '../help/bilder.json'
import EN from '../i18n/en.json'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const RAW = {
  de: import.meta.glob('../help/de/**/*.md', {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>,
  en: import.meta.glob('../help/en/**/*.md', {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>,
}
const IMAGES = Object.keys(
  import.meta.glob('../../public/hilfe-bilder/**/*.png', { query: '?url', eager: true }),
).map((p) => p.replace(/^.*\/hilfe-bilder\//, ''))
const APP_SOURCE = Object.values(
  import.meta.glob('../App.tsx', { query: '?raw', import: 'default', eager: true }),
)[0] as string

// Alle Ziele der Navigation (Seitenleiste und Unterpunkte)
const NAV_SOURCES = import.meta.glob(
  [
    '../modules.tsx',
    '../pages/**/access.ts',
    '../pages/**/sections.ts',
    '../pages/settings/*.ts',
    '../pages/settings/SettingsLayout.tsx',
  ],
  { query: '?raw', import: 'default', eager: true },
) as Record<string, string>
const NAV_ROUTES = [
  ...new Set(
    Object.values(NAV_SOURCES).flatMap((src) =>
      [...src.matchAll(/(?:to|path): '(\/[^']*)'/g)].map((m) => m[1]),
    ),
  ),
]

const parsed = (language: 'de' | 'en') =>
  new Map(
    Object.entries(RAW[language]).map(([path, raw]) => {
      const name = relName(path.replace('../help/', './'))
      return [name, parseHelpFile(name, raw)] as const
    }),
  )
const DE = parsed('de')
const ENG = parsed('en')
const RIGHTS = new Set<string>([...Object.values(PERM), ...Object.values(DEPT_PERM)])
const TOP_ROUTES = new Set(
  [...APP_SOURCE.matchAll(/<Route\s+path="\/?([^"/*]+)/g)].map((m) => m[1]),
)
const bold = (body: string) => [...body.matchAll(/\*\*([^*]+)\*\*/g)].map((m) => m[1])

describe('Hilfedateien', () => {
  it('jede Datei gibt es auf Deutsch und Englisch mit gleichem Kopf', () => {
    expect(DE.size).toBeGreaterThan(0)
    expect([...ENG.keys()].sort()).toEqual([...DE.keys()].sort())
    for (const [name, de] of DE) {
      const en = ENG.get(name) as HelpEntry
      const meta = (e: HelpEntry) => [e.key, e.area, e.module, e.rights, e.routes]
      expect(meta(en), name).toEqual(meta(de))
      expect(en.keywords.length, `${name}: Stichworte`).toBeGreaterThan(0)
      expect(imagesIn(en.body), `${name}: Bilder`).toEqual(imagesIn(de.body))
    }
  })

  it('Schlüssel eindeutig, Bereiche bekannt, Seitenhilfen im Ordner seiten/', () => {
    const keys = [...DE.values()].map((e) => e.key)
    expect(new Set(keys).size).toBe(keys.length)
    for (const [name, e] of DE) {
      expect(AREAS as readonly string[], name).toContain(e.area)
      expect(name.startsWith('seiten/'), name).toBe(e.kind === 'page')
      expect(e.routes.length, `${name}: routen`).toBeGreaterThan(0)
    }
  })

  it('Rechte und Routen gibt es wirklich', () => {
    for (const [name, e] of DE) {
      for (const r of e.rights)
        expect(RIGHTS.has(r) || r === 'platform.manage', `${name}: ${r}`).toBe(true)
      for (const route of e.routes) {
        expect(route.startsWith('/'), `${name}: ${route}`).toBe(true)
        expect(route === '/' || TOP_ROUTES.has(route.split('/')[1]), `${name}: ${route}`).toBe(true)
      }
      for (const link of e.body.matchAll(/\]\((\/[^)\s]*)\)/g))
        expect(TOP_ROUTES.has(link[1].split('/')[1]), `${name}: Link ${link[1]}`).toBe(true)
    }
  })

  it('Knopf- und Feldnamen in Fettschrift stehen so in der Oberfläche', () => {
    const deTexts = new Set(Object.keys(EN))
    const enTexts = new Set(Object.values(EN).filter((v): v is string => typeof v === 'string'))
    for (const [name, e] of DE)
      for (const b of bold(e.body)) expect(deTexts.has(b), `${name}: „${b}“`).toBe(true)
    for (const [name, e] of ENG)
      for (const b of bold(e.body)) expect(enTexts.has(b), `en/${name}: “${b}”`).toBe(true)
  })

  it('jede Seite der Navigation hat eine Seitenhilfe', () => {
    const entries = [...DE.values()]
    expect(NAV_ROUTES.length).toBeGreaterThan(50)
    const missing = NAV_ROUTES.filter((r) => !pageHelpFor(entries, r))
    expect(missing).toEqual([])
  })

  it('Anleitungen haben höchstens zehn Schritte', () => {
    for (const [name, e] of DE)
      expect(e.body.match(/^\d+\. /gm)?.length ?? 0, name).toBeLessThanOrEqual(10)
  })

  it('jedes Bild ist beschrieben, in bilder.json erklärt und in beiden Sprachen da', () => {
    const spec = new Set(SPEC.bilder.map((b) => b.name))
    const used = new Set<string>()
    for (const [name, e] of [...DE, ...ENG]) {
      for (const m of e.body.matchAll(/!\[([^\]]*)\]\(bild:([a-z0-9-]+)\)/g)) {
        expect(m[1].trim().length, `${name}: Bildbeschreibung`).toBeGreaterThan(0)
        used.add(m[2])
      }
      expect(e.body, `${name}: Bilder nur als bild:name`).not.toMatch(/!\[[^\]]*\]\((?!bild:)/)
    }
    for (const img of used) {
      expect(spec.has(img), `bilder.json: ${img}`).toBe(true)
      for (const lang of ['de', 'en'])
        expect(
          IMAGES,
          `fehlt: public/hilfe-bilder/${lang}/${img}.png (scripts/hilfe-bilder.sh)`,
        ).toContain(`${lang}/${img}.png`)
    }
    for (const b of SPEC.bilder) expect(used.has(b.name), `${b.name} wird nicht benutzt`).toBe(true)
  })
})

describe('Auswahl', () => {
  const entries = [...DE.values()]
  it('Seitenhilfe: längste passende Route gewinnt', () => {
    expect(pageHelpFor(entries, '/mein-konto/anmeldung')?.key).toBe('page.account_login')
    expect(pageHelpFor(entries, '/mein-konto')?.key).toBe('page.account')
    expect(pageHelpFor(entries, '/mein-kontoxyz')).toBeNull()
    expect(pageHelpFor(entries, '/mitglieder/42')?.key).toBe('page.member_file')
    expect(pageHelpFor(entries, '/mitglieder/neu')?.key).toBe('page.members')
    expect(guidesFor(entries, '/mein-konto/anmeldung').map((g) => g.key)).toContain(
      'guide.password',
    )
  })

  it('nur mit freigeschaltetem Modul und einem der Rechte', () => {
    const e = { module: 'members', rights: ['members.edit'] }
    expect(
      visibleFor(
        e,
        () => true,
        () => true,
      ),
    ).toBe(true)
    expect(
      visibleFor(
        e,
        () => false,
        () => true,
      ),
    ).toBe(false)
    expect(
      visibleFor(
        e,
        () => true,
        () => false,
      ),
    ).toBe(false)
    expect(
      visibleFor(
        { module: undefined, rights: [] },
        () => false,
        () => false,
      ),
    ).toBe(true)
  })

  it('kein rohes HTML, fremde Bilder fallen weg, Webadressen in neuem Fenster', () => {
    const html = renderHelp(
      '<script>x</script> [a](javascript:alert(1)) [b](https://example.org) ![c](https://x.test/a.png) ![d](bild:konto-passwort)',
    )
    expect(html).not.toContain('<script>')
    expect(html).not.toMatch(/href="javascript/)
    expect(html).toContain('target="_blank"')
    expect(html).not.toContain('x.test')
    expect(html).toContain('src="/hilfe-bilder/de/konto-passwort.png"')
  })
})

const SESSION = 'GET /_allauth/browser/v1/auth/session'

function renderApp(
  path: string,
  org: Record<string, unknown> = testOrg({ modules: ['members'] }),
  routes: Parameters<typeof fakeApi>[0] = {},
) {
  const api = fakeApi({
    [SESSION]: () => ({ status: 200, body: { status: 200, data: { user: testUser } } }),
    'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
    ...routes,
  })
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
  return api
}

const ORG_HELP = {
  contacts: [],
  contacts_from: null,
  own_contacts: [],
  notes: {},
  admin_roles: ['Vorstand'],
  rights: { 'members.edit': 'Mitglieder bearbeiten' },
  can_edit: false,
}

describe('Oberfläche', () => {
  it('Menüpunkt heißt „Hilfe“; /hilfe zeigt Anleitungen nach Rechten, die Suche auch das Glossar', async () => {
    renderApp('/hilfe')
    expect(await screen.findByRole('heading', { level: 1, name: 'Hilfe' })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Module' })
    expect(within(nav).getByRole('link', { name: 'Hilfe' })).toHaveAttribute('href', '/hilfe')
    expect((await screen.findAllByRole('link', { name: 'Passwort ändern' }))[0]).toHaveAttribute(
      'href',
      '/hilfe/passwort-aendern',
    )
    // testOrg hat members.view, aber nicht members.edit
    expect(screen.queryByRole('link', { name: 'Neues Mitglied aufnehmen' })).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Hilfe durchsuchen'), 'Authenticator')
    expect(
      await screen.findByRole('link', { name: 'Zwei-Faktor-Anmeldung einrichten' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Passwort ändern' })).not.toBeInTheDocument()
  })

  it('mit dem Recht erscheint die Anleitung; Anleitung als eigene Seite mit Bild', async () => {
    renderApp(
      '/hilfe/mitglied-aufnehmen',
      testOrg({ modules: ['members'], permissions: ['members.view', 'members.edit'] }),
    )
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Neues Mitglied aufnehmen' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Formular „Mitglied aufnehmen“' })).toHaveAttribute(
      'src',
      '/hilfe-bilder/de/mitglieder-aufnehmen.png',
    )
    expect(screen.getByRole('link', { name: 'Zur Seite in HUBIplan' })).toHaveAttribute(
      'href',
      '/mitglieder',
    )
  })

  it('„?“ öffnet die Hilfe zu dieser Seite, Esc schließt sie und der Fokus kehrt zurück', async () => {
    const user = userEvent.setup()
    renderApp('/mein-konto')
    const button = await screen.findByRole('button', { name: 'Hilfe zu dieser Seite' })
    await user.click(button)
    const panel = await screen.findByRole('complementary', { name: 'Hilfe zu dieser Seite' })
    expect(
      await within(panel).findByRole('heading', { name: 'Mein Konto › Profil' }),
    ).toBeInTheDocument()
    await user.click(
      within(panel).getByRole('button', { name: 'Sprache umstellen (Deutsch oder Englisch)' }),
    )
    expect(
      within(panel).getByRole('img', { name: 'Auswahl „Sprache der Oberfläche“ im Profil' }),
    ).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() =>
      expect(
        screen.queryByRole('complementary', { name: /Hilfe|Sprache/ }),
      ).not.toBeInTheDocument(),
    )
    expect(button).toHaveFocus()
    await user.keyboard('?')
    expect(
      await screen.findByRole('complementary', { name: 'Hilfe zu dieser Seite' }),
    ).toBeInTheDocument()
    const result = await axe.run(document.body, { rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations.map((v) => v.id)).toEqual([])
  })

  it('„Für dich“: erste Schritte abhaken, die Haken speichert das Konto', async () => {
    const user = userEvent.setup()
    const api = renderApp('/hilfe', testOrg({ modules: ['members'] }), {
      'GET /api/me/help/': () => ({ status: 200, body: { help_done: ['guide.two_factor'] } }),
      'POST /api/me/help/guide.password/': () => ({
        status: 200,
        body: { help_done: ['guide.password', 'guide.two_factor'] },
      }),
    })
    const box = await screen.findByRole('checkbox', { name: 'Passwort ändern erledigt' })
    await waitFor(() => expect(box).toBeEnabled())
    expect(screen.getByRole('checkbox', { name: /Zwei-Faktor.* erledigt/ })).toBeChecked()
    await user.click(box)
    await waitFor(() => expect(box).toBeChecked())
    expect(api.some((c) => c.key === 'POST /api/me/help/guide.password/')).toBe(true)
    expect(screen.getByText(/2 von \d+ erledigt/)).toBeInTheDocument()
  })

  it('Ansicht als Rolle: Haken gesperrt, mit Hinweis', async () => {
    renderApp(
      '/hilfe',
      testOrg({
        modules: ['members'],
        role_preview: { available: true, active: { id: 3, name: 'Kassierer' } },
      }),
    )
    const box = await screen.findByRole('checkbox', { name: 'Passwort ändern erledigt' })
    expect(box).toBeDisabled()
    expect(screen.getByText(/wie sie Personen mit der Rolle „Kassierer“ sehen/)).toBeInTheDocument()
  })

  it('Warum sehe ich das nicht? Suche zeigt fehlende Rechte und wer sie vergibt', async () => {
    const user = userEvent.setup()
    renderApp('/hilfe', testOrg({ modules: ['members'] }), {
      'GET /api/orgs/7/help/': () => ({ status: 200, body: ORG_HELP }),
    })
    await screen.findByRole('heading', { name: 'Wer hilft bei uns?' })
    expect(
      screen.getByText('Bei Fragen zu HUBIplan hilft dir jemand mit der Rolle „Vorstand“.'),
    ).toBeInTheDocument()
    await user.type(screen.getByLabelText('Hilfe durchsuchen'), 'Neues Mitglied aufnehmen')
    expect(
      await screen.findByRole('heading', { name: 'Dafür fehlt dir ein Recht' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Neues Mitglied aufnehmen' })).not.toBeInTheDocument()
    expect(
      screen.getAllByText(
        'Dafür brauchst du das Recht „Mitglieder bearbeiten“. Vergeben kann es, wer die Rolle „Vorstand“ hat.',
      ).length,
    ).toBeGreaterThan(0)
  })

  it('Anleitung ohne Recht: Seite nennt das fehlende Recht', async () => {
    renderApp('/hilfe/mitglied-aufnehmen', testOrg({ modules: ['members'] }), {
      'GET /api/orgs/7/help/': () => ({ status: 200, body: ORG_HELP }),
    })
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Neues Mitglied aufnehmen' }),
    ).toBeInTheDocument()
    expect(await screen.findByText(/Recht „Mitglieder bearbeiten“/)).toBeInTheDocument()
  })

  it('Ansprechpartner und Hinweise des Vereins; eigenen Hinweis ergänzen', async () => {
    const user = userEvent.setup()
    const state = {
      ...ORG_HELP,
      contacts: [{ name: 'Anna Beispiel', hint: 'Mitglieder', email: 'anna@example.org' }],
      contacts_from: { name: 'Testbund', own: false },
      notes: {
        'guide.member_admit': [{ text: 'Formular B nutzen.', from: 'Testbund', own: false }],
      },
      can_edit: true,
    }
    const api = renderApp(
      '/hilfe/mitglied-aufnehmen',
      testOrg({ modules: ['members'], permissions: ['members.view', 'members.edit', 'org.edit'] }),
      {
        'GET /api/orgs/7/help/': () => ({ status: 200, body: state }),
        'PUT /api/orgs/7/help/notes/guide.member_admit/': () => ({
          status: 200,
          body: {
            ...state,
            notes: {
              'guide.member_admit': [
                ...state.notes['guide.member_admit'],
                { text: 'Bei uns die Kasse fragen.', from: 'TV Beispielhausen', own: true },
              ],
            },
          },
        }),
      },
    )
    expect(await screen.findByText('Formular B nutzen.')).toBeInTheDocument()
    expect(screen.getByText('Hinweis von Testbund')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Hinweis für unsere Einheit ergänzen' }))
    await user.type(
      screen.getByLabelText(/Hinweis zu dieser Anleitung/),
      'Bei uns die Kasse fragen.',
    )
    await user.click(screen.getByRole('button', { name: 'Speichern' }))
    expect(await screen.findByText('Bei uns die Kasse fragen.')).toBeInTheDocument()
    const put = api.find((c) => c.key.startsWith('PUT '))
    expect(JSON.parse(String(put?.init?.body))).toEqual({ text: 'Bei uns die Kasse fragen.' })

    await user.click(screen.getByRole('link', { name: '← Alle Hilfe' }))
    expect(await screen.findByText('Anna Beispiel')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'anna@example.org' })).toHaveAttribute(
      'href',
      'mailto:anna@example.org',
    )
    expect(screen.getByText('Angegeben von Testbund.')).toBeInTheDocument()
  })
})

describe('Zeig es mir', () => {
  it('findet das Bedienelement mit der fett genannten Beschriftung', () => {
    expect(labelsIn('Klicke **Speichern**, dann **Weiter** und **Speichern**.')).toEqual([
      'Speichern',
      'Weiter',
    ])
    document.body.innerHTML =
      '<main id="inhalt"><h1>Profil</h1><button>Weiter</button></main><aside class="help-panel"><button>Speichern</button></aside>'
    expect(highlight(['Speichern'])).toBe(false)
    expect(highlight(['Speichern', 'Weiter'])).toBe(true)
    expect(document.querySelector('#inhalt button')).toHaveClass('help-highlight')
  })
})
