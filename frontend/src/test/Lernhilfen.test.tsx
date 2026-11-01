// Lernhilfen: Inhalte, Bausteine, Glossar, Prüflisten (Akzeptanzkriterien 1–15).
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import axe from 'axe-core'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App.tsx'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { HowTo, Term, Why } from '../learning/Aids.tsx'
import { Checklist } from '../learning/Checklist.tsx'
import {
  closingChecks,
  debitChecks,
  easterSunday,
  feeRunChecks,
  isBankBusinessDay,
  MIN_DUE_DAYS,
  donationChecks,
} from '../learning/checks.ts'
import {
  DECISIONS,
  HOWTOS,
  LANGUAGES,
  PHASES,
  SECTIONS,
  SOURCES,
  TERMS,
  termAnchor,
  tr,
  type Text,
} from '../learning/content.ts'
import { GlossaryPage } from '../learning/GlossaryPage.tsx'
import { LearningCard } from '../learning/LearningCard.tsx'
import { LearningProvider, NoLearningAids } from '../learning/LearningContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const state =
  (learning_aids: boolean, learning_hidden: string[] = []) =>
  () => ({
    status: 200,
    body: { learning_aids, learning_hidden },
  })

// Quelltexte der Oberfläche, um Schlüssel und Tabellenköpfe zu prüfen
const SOURCES_TSX = import.meta.glob(['../**/*.tsx', '../learning/checks.ts', '!../test/**'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>
// Schlüsselliste des Backends (scripts/test.sh hängt das Backend dafür ein)
const BACKEND_KEYS = import.meta.glob('../../../backend/accounts/learning_keys.json', {
  import: 'default',
  eager: true,
}) as Record<string, { decisions: string[] }>

/** Sätze zählen; Abkürzungen wie „z. B.“, „Abs.“ oder „Nr.“ beenden keinen Satz. */
function sentences(text: string): number {
  const cleaned = text
    .replace(
      /\b(z|d|u|o|v|s|bzw|ggf|usw|vgl|Abs|Art|Nr|lit|Satz|S|Verbandsnr|USt-IdNr|ca)\./g,
      '$1',
    )
    .replace(/\d\./g, '0')
  return cleaned.split(/[.!?](?:\s|$)/).filter((s) => s.trim()).length
}

const allTexts = (): [string, Text][] => [
  ...Object.entries(DECISIONS).flatMap(([k, e]): [string, Text][] => [
    [`${k}.title`, e.title],
    [`${k}.text`, e.text],
    [`${k}.place`, e.place],
  ]),
  ...Object.entries(TERMS).flatMap(([k, t]): [string, Text][] => [
    [`${k}.name`, t.name],
    [`${k}.meaning`, t.meaning],
    [`${k}.example`, t.example],
  ]),
  ...Object.entries(HOWTOS).flatMap(([k, h]): [string, Text][] => [
    [`${k}.title`, h.title],
    [`${k}.text`, h.text],
  ]),
]

function renderAids(ui: ReactNode, on: boolean, hidden: string[] = []) {
  const calls = fakeApi({ 'GET /api/me/learning/': state(on, hidden) })
  const view = render(
    <MemoryRouter>
      <LearningProvider>{ui}</LearningProvider>
    </MemoryRouter>,
  )
  return { calls, ...view }
}

function renderWithOrg(ui: ReactNode, modules: string[], on = true) {
  const calls = fakeApi({
    [SESSION]: loggedIn,
    'GET /api/me/organizations/': () => ({ status: 200, body: [testOrg({ modules })] }),
    'GET /api/me/learning/': state(on),
  })
  render(
    <MemoryRouter>
      <AuthProvider>
        <OrgProvider>
          <LearningProvider>{ui}</LearningProvider>
        </OrgProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
  return calls
}

describe('Inhalte', () => {
  it('1: jede Entscheidung und jeder Begriff hat eine vollständige Quelle, Begriffe ein Beispiel, kein Text mehr als drei Sätze', () => {
    for (const [k, e] of Object.entries(DECISIONS)) {
      expect(e.sources.length, k).toBeGreaterThan(0)
      for (const s of e.sources) expect(SOURCES[s].full.length, s).toBeGreaterThan(20)
    }
    for (const [k, t] of Object.entries(TERMS)) {
      expect(t.sources.length, k).toBeGreaterThan(0)
      expect(tr(t.example), k).toMatch(/^Beispiel: .*\d/)
    }
    for (const [k, text] of allTexts()) expect(sentences(tr(text)), k).toBeLessThanOrEqual(3)
    // Kurzbeleg im Text: Paragraph, Artikel oder Regelwerk
    const cite = /§|Art\. \d|EPC|UStAE|GoBD|Bundesbank|WCAG|EuGH|ISO 20022|DSB-Sportordnung/
    for (const [k, e] of Object.entries(DECISIONS)) expect(tr(e.text), k).toMatch(cite)
    for (const [k, t] of Object.entries(TERMS)) expect(tr(t.meaning), k).toMatch(cite)
  })

  it('2: jeder Text hat eine Fassung je Oberflächensprache; Schlüssel wie im Backend', () => {
    for (const [k, text] of allTexts())
      for (const lang of LANGUAGES) expect(text[lang]?.trim(), `${k}.${lang}`).toBeTruthy()
    const backend = Object.values(BACKEND_KEYS)[0]
    expect(backend, 'backend/accounts/learning_keys.json fehlt').toBeDefined()
    expect([...backend.decisions].sort()).toEqual(Object.keys(DECISIONS).sort())
  })

  it('3 und 4: verwendete Schlüssel existieren, jeder Eintrag steht an einer Stelle', () => {
    const code = Object.entries(SOURCES_TSX).filter(([path]) => !path.includes('/learning/'))
    const all = code.map(([, src]) => src).join('\n')
    const checks = Object.entries(SOURCES_TSX)
      .filter(([path]) => path.endsWith('checks.ts'))
      .map(([, src]) => src)
      .join('\n')
    const used = (re: RegExp, src = all) => [...src.matchAll(re)].map((m) => m[1])
    const whys = used(/<Why k="(\w+)"/g)
    const terms = [
      ...used(/<Term k="(\w+)"/g),
      // Begriffe über eine Zuordnung (z. B. steuerliche Bereiche)
      ...used(/: '(\w+)',?$/gm).filter((k) => k in TERMS),
    ]
    const hows = used(/<HowTo k="(\w+)"/g)
    const checkWhys = used(/why: '(\w+)'/g, checks)
    for (const k of whys) expect(DECISIONS, k).toHaveProperty(k)
    for (const k of checkWhys) expect(DECISIONS, k).toHaveProperty(k)
    for (const k of used(/<Term k="(\w+)"/g)) expect(TERMS, k).toHaveProperty(k)
    for (const k of hows) expect(HOWTOS, k).toHaveProperty(k)
    for (const k of Object.keys(DECISIONS))
      expect([...whys, ...checkWhys], `Entscheidung ${k} steht nirgends`).toContain(k)
    for (const k of Object.keys(TERMS)) expect(terms, `Begriff ${k} steht nirgends`).toContain(k)
    for (const k of Object.keys(HOWTOS)) expect(hows, `${k} steht nirgends`).toContain(k)
    for (const [k, e] of Object.entries(DECISIONS)) {
      expect(tr(e.place), k).toBeTruthy()
      expect(PHASES, k).toHaveProperty(e.phase)
    }
  })

  it('6: Tabellenköpfe mit einem Begriff aus dem Glossar laufen über das „?“', () => {
    const names = new Map<string, string>()
    for (const [k, t] of Object.entries(TERMS)) {
      if (t.simple) continue
      names.set(tr(t.name), k)
      if (t.symbol) names.set(t.symbol, k)
    }
    const offenders: string[] = []
    for (const [path, src] of Object.entries(SOURCES_TSX)) {
      if (path.includes('/learning/')) continue
      for (const m of src.matchAll(/<th\b[^>]*>\s*([^<{]+?)\s*<\/th>/g))
        if (names.has(m[1])) offenders.push(`${path}: ${m[1]}`)
    }
    expect(offenders).toEqual([])
  })
})

describe('Schalter', () => {
  it('7: AUS zeigt keine „?“ und keine Grundlagen, aber die Abwägungen', async () => {
    renderAids(
      <>
        <Why k="member_type_active" />
        <Why k="dpo" />
        <Term k="member_type">Mitgliedsart</Term>
      </>,
      false,
    )
    expect(await screen.findByText(DECISIONS.member_type_active.title.de)).toBeInTheDocument()
    expect(screen.queryByText(DECISIONS.dpo.title.de)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Was heißt das/ })).not.toBeInTheDocument()
    expect(screen.getByText('Mitgliedsart')).toBeInTheDocument()
  })

  it('7: EIN zeigt beides', async () => {
    renderAids(
      <>
        <Why k="member_type_active" />
        <Why k="dpo" />
        <Term k="member_type">Mitgliedsart</Term>
      </>,
      true,
    )
    expect(await screen.findByText(DECISIONS.dpo.title.de)).toBeInTheDocument()
    expect(screen.getByText(DECISIONS.member_type_active.title.de)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mitgliedsart: Was heißt das?' })).toBeInTheDocument()
  })

  it('Mein Konto: Schalter speichert sofort, Ausgeblendete lassen sich zurückholen', async () => {
    const calls = fakeApi({
      'GET /api/me/learning/': state(true, ['dpo', 'sepa_use']),
      'PATCH /api/me/learning/': (init) => ({
        status: 200,
        body: { learning_aids: true, learning_hidden: [], ...JSON.parse(String(init?.body)) },
      }),
    })
    render(
      <MemoryRouter>
        <LearningProvider>
          <LearningCard />
        </LearningProvider>
      </MemoryRouter>,
    )
    expect(await screen.findByText('2 Erklärungen „Warum?“ ausgeblendet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Glossar' })).toHaveAttribute('href', '/glossar')
    await userEvent.click(
      screen.getByRole('button', { name: 'Ausgeblendete Erklärungen wieder zeigen' }),
    )
    await waitFor(() => expect(screen.queryByText(/ausgeblendet\./)).not.toBeInTheDocument())
    await userEvent.click(screen.getByRole('checkbox', { name: 'Lernhilfen zeigen' }))
    const patches = calls.filter((c) => c.key === 'PATCH /api/me/learning/')
    expect(patches.map((c) => JSON.parse(String(c.init?.body)))).toEqual([
      { learning_hidden: [] },
      { learning_aids: false },
    ])
  })
})

describe('Nicht mehr zeigen', () => {
  it('9: blendet genau diese Erklärung überall aus, Rückgängig holt sie zurück', async () => {
    const calls = fakeApi({
      'GET /api/me/learning/': state(false),
      'POST /api/me/learning/member_type_active/hide/': () => ({
        status: 200,
        body: { ok: true, learning_hidden: ['member_type_active'] },
      }),
      'POST /api/me/learning/member_type_active/show/': () => ({
        status: 200,
        body: { ok: true, learning_hidden: [] },
      }),
    })
    render(
      <MemoryRouter>
        <LearningProvider>
          <Why k="member_type_active" />
          <Why k="member_type_active" />
          <Why k="member_type_duration" />
        </LearningProvider>
      </MemoryRouter>,
    )
    const titles = await screen.findAllByText(DECISIONS.member_type_active.title.de)
    expect(titles).toHaveLength(2)
    await userEvent.click(titles[0])
    const dialog = screen.getByRole('dialog', { name: DECISIONS.member_type_active.title.de })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Nicht mehr zeigen' }))
    expect(screen.queryByText(DECISIONS.member_type_active.title.de)).not.toBeInTheDocument()
    expect(screen.getByText(DECISIONS.member_type_duration.title.de)).toBeInTheDocument()
    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('Erklärung ausgeblendet · Rückgängig')
    expect(status).toHaveFocus()
    // der CSRF-Schutz geht mit
    const hide = calls.find((c) => c.key.endsWith('/hide/'))!
    const headers = (hide.init?.headers ?? {}) as Record<string, string>
    expect(headers['X-CSRFToken']).toBe('test-token')

    await userEvent.click(within(status).getByRole('button', { name: 'Rückgängig' }))
    const back = await screen.findAllByText(DECISIONS.member_type_active.title.de)
    expect(back).toHaveLength(2)
    await waitFor(() => expect(back[0].closest('summary')).toHaveFocus())
    expect(calls.some((c) => c.key.endsWith('/show/'))).toBe(true)
  })

  it('9: bereits ausgeblendete Erklärungen erscheinen nicht', async () => {
    renderAids(
      <>
        <Why k="member_type_active" />
        <Why k="member_type_duration" />
      </>,
      true,
      ['member_type_active'],
    )
    expect(await screen.findByText(DECISIONS.member_type_duration.title.de)).toBeInTheDocument()
    expect(screen.queryByText(DECISIONS.member_type_active.title.de)).not.toBeInTheDocument()
  })
})

describe('Bausteine', () => {
  it('10: einfache Begriffe und „nur einmal“-Erklärungen erscheinen einmal pro Seite', async () => {
    renderWithOrg(
      <>
        <Term k="balance">Saldo</Term>
        <Term k="balance">Saldo</Term>
        <Term k="mandate">Mandat</Term>
        <Term k="mandate">Mandat</Term>
        <Why k="receipts" />
        <Why k="receipts" />
      </>,
      ['finance', 'billing'],
    )
    await screen.findAllByText(DECISIONS.receipts.title.de)
    await waitFor(() => expect(screen.getAllByText(DECISIONS.receipts.title.de)).toHaveLength(1))
    expect(screen.getAllByRole('button', { name: 'Saldo: Was heißt das?' })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'SEPA-Mandat: Was heißt das?' })).toHaveLength(2)
    // beide Wörter bleiben stehen (der Name in der „?“-Box zählt nicht)
    expect(screen.getAllByText('Saldo').filter((el) => !el.closest('.term-box'))).toHaveLength(2)
  })

  it('11: „?“-Box mit Name, Bedeutung, Beispiel, Glossarlink; Tooltip der Zelle wird übernommen', async () => {
    renderAids(
      <table>
        <thead>
          <tr>
            <th title="Nur Mitgliedsarten mit Beitrag">
              <Term k="member_type">Mitgliedsart</Term>
            </th>
          </tr>
        </thead>
      </table>,
      true,
    )
    const button = await screen.findByRole('button', { name: 'Mitgliedsart: Was heißt das?' })
    const th = button.closest('th')!
    await waitFor(() => expect(th).not.toHaveAttribute('title'))
    expect(button).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    const box = document.getElementById(button.getAttribute('aria-controls')!)!
    expect(box).toBeVisible()
    expect(box).toHaveTextContent('Mitgliedsart')
    expect(box).toHaveTextContent(TERMS.member_type.meaning.de)
    expect(box).toHaveTextContent(TERMS.member_type.example.de)
    expect(box).toHaveTextContent('Nur Mitgliedsarten mit Beitrag')
    expect(within(box).getByRole('link', { name: 'im Glossar ↗' })).toHaveAttribute(
      'href',
      `/glossar#${termAnchor('member_type')}`,
    )
  })

  it('14: Tastatur: Tab erreicht „?“ und Hilfe, Enter öffnet, Esc schließt, Fokus kehrt zurück', async () => {
    const user = userEvent.setup()
    renderAids(
      <>
        <Term k="member_type">Mitgliedsart</Term>
        <Why k="member_type_active" />
        <HowTo k="how_units" />
      </>,
      true,
    )
    const q = await screen.findByRole('button', { name: 'Mitgliedsart: Was heißt das?' })
    await user.tab()
    expect(q).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(q).toHaveAttribute('aria-expanded', 'true')
    await user.keyboard('{Escape}')
    expect(q).toHaveAttribute('aria-expanded', 'false')
    expect(q).toHaveFocus()

    await user.tab()
    const summary = screen.getByText(DECISIONS.member_type_active.title.de).closest('summary')!
    expect(summary).toHaveFocus()
    expect(summary).toHaveAttribute('aria-expanded', 'false')
    await user.keyboard('{Enter}')
    const dialog = screen.getByRole('dialog', { name: DECISIONS.member_type_active.title.de })
    expect(within(dialog).getByRole('button', { name: 'Schließen' })).toHaveFocus()
    expect(summary).toHaveAttribute('aria-expanded', 'true')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(summary).toHaveFocus()

    // immer nur eine Hilfe offen
    await user.click(summary)
    await user.click(screen.getByText(HOWTOS.how_units.title.de))
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
    expect(screen.getByRole('dialog', { name: HOWTOS.how_units.title.de })).toBeInTheDocument()
    expect(screen.getByText('So funktioniert es:')).toBeInTheDocument()
  })

  it('14: keine Verstöße laut axe auf einer Seite mit offener Hilfe', async () => {
    renderAids(
      <main>
        <h1>Test</h1>
        <p>
          <Term k="member_type">Mitgliedsart</Term>
        </p>
        <Why k="member_type_active" />
      </main>,
      true,
    )
    await userEvent.click(await screen.findByText(DECISIONS.member_type_active.title.de))
    await userEvent.click(screen.getByRole('button', { name: 'Mitgliedsart: Was heißt das?' }))
    const result = await axe.run(document.body, { rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([])
  })

  it('15: im Mitgliederbereich und ohne Anmeldung keine Lernhilfen', async () => {
    renderAids(
      <NoLearningAids>
        <Why k="member_type_active" />
        <Term k="member_type">Mitgliedsart</Term>
      </NoLearningAids>,
      true,
    )
    await act(async () => undefined)
    expect(screen.queryByText(DECISIONS.member_type_active.title.de)).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByText('Mitgliedsart')).toBeInTheDocument()
  })

  it('15: öffentliche Seiten laden keine Lernhilfen', async () => {
    const calls = fakeApi({
      [SESSION]: () => ({ status: 401, body: { status: 401, data: {} } }),
      'GET /api/public/imprint/': () => ({ status: 200, body: { text: 'Impressum', html: '' } }),
    })
    render(
      <MemoryRouter initialEntries={['/anmelden']}>
        <AuthProvider>
          <OrgProvider>
            <App />
          </OrgProvider>
        </AuthProvider>
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { level: 1 })
    expect(calls.some((c) => c.key.includes('/api/me/learning/'))).toBe(false)
    expect(document.querySelector('.aid, .term-q')).toBeNull()
  })
})

describe('Freischaltung', () => {
  it('13: Hilfen nicht freigeschalteter Funktionen erscheinen weder an der Stelle noch im Glossar', async () => {
    renderWithOrg(
      <>
        <Why k="sepa_use" />
        <Why k="member_type_active" />
        <GlossaryPage />
      </>,
      ['members'],
    )
    expect(await screen.findAllByText(DECISIONS.member_type_active.title.de)).not.toHaveLength(0)
    await waitFor(() => expect(document.getElementById(termAnchor('member_type'))).not.toBeNull())
    expect(screen.queryByText(DECISIONS.sepa_use.title.de)).not.toBeInTheDocument()
    expect(document.getElementById(termAnchor('mandate'))).toBeNull()
    expect(screen.queryByRole('heading', { name: 'SEPA-Lastschrift' })).not.toBeInTheDocument()
  })
})

describe('Glossar', () => {
  it('5: jeder Begriff in genau einem Abschnitt, mit Anker, sortiert; Entscheidungen mit Ort und Phase; Quellen je einmal', async () => {
    for (const [k, t] of Object.entries(TERMS)) expect(SECTIONS, k).toHaveProperty(t.section)
    renderWithOrg(<GlossaryPage />, [
      'members',
      'billing',
      'finance',
      'events',
      'website',
      'competitions',
    ])
    await waitFor(() => expect(document.getElementById(termAnchor('mandate'))).not.toBeNull())
    for (const k of Object.keys(TERMS))
      expect(document.getElementById(termAnchor(k)), k).not.toBeNull()
    for (const section of document.querySelectorAll('.glossary-section')) {
      const names = [
        ...section.querySelectorAll(':scope > .glossary-list > .glossary-entry dt'),
      ].map((dt) => dt.textContent!.replace(/^.* · /, ''))
      expect(names).toEqual(
        [...names].sort((a, b) => a.localeCompare(b, 'de', { sensitivity: 'base' })),
      )
    }
    const decisions = screen.getByRole('heading', { name: 'Entscheidungen' }).closest('section')!
    expect(within(decisions).getByRole('heading', { name: 'Einrichten' })).toBeInTheDocument()
    expect(
      within(decisions).getByText(`(${DECISIONS.age_brackets.place.de})`, { exact: false }),
    ).toBeInTheDocument()
    // Plattform-Einstellungen nur für die Plattform
    expect(document.getElementById('warum-deletion_period')).toBeNull()
    const sources = screen.getByRole('heading', { name: 'Quellen' }).closest('section')!
    const items = [...sources.querySelectorAll('li')].map((li) => li.textContent)
    expect(new Set(items).size).toBe(items.length)
  })

  it('5: Suche filtert über alle Wörter, leere Abschnitte verschwinden, sonst „Nichts gefunden.“', async () => {
    renderWithOrg(<GlossaryPage />, ['members', 'billing', 'finance'])
    const search = await screen.findByRole('searchbox', { name: 'Glossar durchsuchen' })
    await waitFor(() => expect(document.getElementById(termAnchor('mandate'))).not.toBeNull())
    await userEvent.type(search, 'mandat 36')
    expect(document.getElementById(termAnchor('mandate_expiry'))).not.toBeNull()
    expect(document.getElementById(termAnchor('mandate'))).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Steuer' })).not.toBeInTheDocument()
    await userEvent.clear(search)
    await userEvent.type(search, 'xyzunbekannt')
    expect(screen.getByText('Nichts gefunden.')).toBeInTheDocument()
  })

  it('14: keine Verstöße laut axe', async () => {
    renderWithOrg(
      <main>
        <GlossaryPage />
      </main>,
      ['members', 'billing', 'finance', 'events'],
    )
    await waitFor(() => expect(document.getElementById(termAnchor('mandate'))).not.toBeNull())
    const result = await axe.run(document.body, { rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([])
  })
})

describe('Prüflisten', () => {
  const run = {
    skipped: [],
    members: 10,
    dueDays: 14,
    accountWithIban: true,
    sepaEnabled: false,
    checks: { unreachable: 0, with_mandate: 0, open_change_requests: 0 },
  }

  it('12: Zahlungsziel greift ab der Schwelle (knapp darunter und darüber)', () => {
    const at = (d: number) =>
      feeRunChecks({ ...run, dueDays: d }).find((i) => i.key === 'due_days')!
    expect(at(MIN_DUE_DAYS - 1).ok).toBe(false)
    expect(at(MIN_DUE_DAYS).ok).toBe(true)
    expect(at(MIN_DUE_DAYS + 1).ok).toBe(true)
  })

  it('12: Zeilen erscheinen nur, wenn sie zählen', () => {
    const keys = (input: Partial<typeof run>) =>
      feeRunChecks({ ...run, ...input }).map((i) => i.key)
    expect(keys({})).not.toContain('change_requests')
    expect(
      keys({ checks: { unreachable: 0, with_mandate: 0, open_change_requests: 1 } }),
    ).toContain('change_requests')
    expect(keys({})).not.toContain('mandates')
    expect(keys({ sepaEnabled: true })).toContain('mandates')
    expect(keys({ members: 0 })).not.toContain('unreachable')

    const debit = {
      creditorId: 'DE98ZZZ09999999999',
      creditorValid: true,
      date: '2026-11-16',
      earliest: '2026-11-10',
      invoices: [{ due_date: '2026-11-01', has_email: true }],
    }
    const dk = (input: Record<string, unknown>) =>
      debitChecks({ prenotificationDays: 14, ...debit, ...input }).map((i) => i.key)
    expect(dk({ prenotificationDays: 14 })).not.toContain('prenotification_days')
    expect(dk({ prenotificationDays: 13 })).toContain('prenotification_days')
    expect(dk({})).not.toContain('expiring')
    expect(dk({ expiringSoon: 1 })).toContain('expiring')

    expect(
      closingChecks({
        bookings: 0,
        without_receipt: 0,
        tax_areas_enabled: false,
        categories_without_area: 0,
      }).map((i) => i.key),
    ).toEqual(['audit'])
    expect(
      closingChecks({
        bookings: 1,
        without_receipt: 1,
        tax_areas_enabled: true,
        categories_without_area: 0,
      }).map((i) => i.key),
    ).toEqual(['receipts', 'tax_areas', 'audit'])
  })

  it('12: Prüfliste vor den Jahresbestätigungen', () => {
    const none = {
      problems: [],
      open: 0,
      without_address: 0,
      goods_without_documents: 0,
      goods_open: 0,
      fees_skipped: 0,
    }
    // ohne offene Zuwendungen nur der Bescheid
    expect(donationChecks(none).map((c) => c.key)).toEqual(['notice'])
    const items = donationChecks({
      ...none,
      problems: ['Es fehlt: Steuernummer.'],
      open: 5,
      without_address: 1,
      goods_open: 2,
      goods_without_documents: 1,
      fees_skipped: 3,
    })
    expect(items.map((c) => [c.key, c.ok])).toEqual([
      ['notice', false],
      ['address', false],
      ['goods', false],
      ['goods_single', true],
      ['fees', true],
    ])
    expect(items[0].text).toBe('Es fehlt: Steuernummer.')
    expect(items[1].text).toBe('1 offene Zuwendung ohne Anschrift.')
    expect(items[2].why).toBe('donation_goods')
    expect(items.filter((c) => c.info).map((c) => c.key)).toEqual(['goods_single', 'fees'])
  })

  it('12: Bankarbeitstage ohne Wochenende und TARGET-Feiertage', () => {
    expect(easterSunday(2026).getDate()).toBe(5)
    expect(easterSunday(2027).getMonth()).toBe(2) // 28. März
    expect(isBankBusinessDay('2026-11-14')).toBe(false) // Samstag
    expect(isBankBusinessDay('2026-04-03')).toBe(false) // Karfreitag
    expect(isBankBusinessDay('2026-04-06')).toBe(false) // Ostermontag
    expect(isBankBusinessDay('2026-12-24')).toBe(true)
    expect(isBankBusinessDay('2026-12-25')).toBe(false)
    expect(isBankBusinessDay('2026-11-16')).toBe(true) // Montag
    const before = debitChecks({
      creditorId: 'x',
      creditorValid: true,
      date: '2026-11-16',
      earliest: '2026-11-10',
      prenotificationDays: 14,
      invoices: [{ due_date: '2026-11-17' }, { due_date: '2026-11-16' }],
    }).find((i) => i.key === 'before_due')!
    expect(before.ok).toBe(false)
    expect(before.text).toBe('1 Rechnung wird vor der Fälligkeit eingezogen.')
  })

  it('12: zeigt „x von y Punkten erledigt“, Hinweise zählen nicht, nichts blockiert', async () => {
    renderWithOrg(
      <>
        <Checklist
          title="Vor dem Beitragslauf"
          items={feeRunChecks({ ...run, dueDays: 7, sepaEnabled: true })}
        />
        <button type="submit">Erstellen</button>
      </>,
      ['billing'],
    )
    expect(await screen.findByText('3 von 4 Punkten erledigt')).toBeInTheDocument()
    expect(screen.getByText(/Zahlungsziel 7 Tage/)).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Zur Stelle' })[0]).toHaveAttribute(
      'href',
      '/finanzen/einstellungen/rechnung',
    )
    expect(await screen.findByText(DECISIONS.due_days.title.de)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Erstellen' })).toBeEnabled()
  })
})
