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
        expect(TOP_ROUTES.has(route.split('/')[1]), `${name}: ${route}`).toBe(true)
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
    expect(pageHelpFor(entries, '/mitglieder/42')?.key).toBe('page.members')
    expect(pageHelpFor(entries, '/mein-kontoxyz')).toBeNull()
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

function renderApp(path: string, org = testOrg({ modules: ['members'] })) {
  fakeApi({
    [SESSION]: () => ({ status: 200, body: { status: 200, data: { user: testUser } } }),
    'GET /api/me/organizations/': () => ({ status: 200, body: [org] }),
  })
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <OrgProvider>
          <App />
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('Oberfläche', () => {
  it('Menüpunkt heißt „Hilfe“; /hilfe zeigt Anleitungen nach Rechten, die Suche auch das Glossar', async () => {
    renderApp('/hilfe')
    expect(await screen.findByRole('heading', { level: 1, name: 'Hilfe' })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Module' })
    expect(within(nav).getByRole('link', { name: 'Hilfe' })).toHaveAttribute('href', '/hilfe')
    expect(await screen.findByRole('link', { name: 'Passwort ändern' })).toHaveAttribute(
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
})
