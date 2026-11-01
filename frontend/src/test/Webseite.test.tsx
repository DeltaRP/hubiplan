import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '../App.tsx'
import { leaveTo } from '../api/peering.ts'
import { AuthProvider } from '../auth/AuthContext.tsx'
import { OrgProvider } from '../org/OrgContext.tsx'
import { PublicationSection } from '../pages/members/PublicationSection.tsx'
import { fakeApi, testOrg, testUser } from './fakeApi.ts'

const SESSION = 'GET /_allauth/browser/v1/auth/session'
const loggedIn = () => ({ status: 200, body: { status: 200, data: { user: testUser } } })
const base = '/api/orgs/7/website/'

const website = (state = 'maintenance', extra: Record<string, unknown> = {}) => ({
  state,
  maintenance_text: 'Hier entsteht unsere neue Webseite.',
  blocks: { board: true, events: true, contact: true },
  name_format: 'full',
  show_vacant: false,
  missing_consent: 'omit',
  units_mode: 'all',
  unit_ids: [],
  include_unit_events: true,
  include_parent_events: false,
  include_parent_honors: false,
  allow_indexing: true,
  contact_limit_per_hour: 20,
  public_key: 'abc',
  effective_state: state,
  url: 'https://www.beispiel.test/',
  domains: [{ id: 1, hostname: 'www.beispiel.test', is_primary: true }],
  preview_links: [],
  privacy_mode: 'text',
  privacy_text: '',
  privacy_url: '',
  privacy_generated_at: null,
  checks: [
    { key: 'imprint', label: 'Impressum vollständig', ok: true, blocking: true, hint: '' },
    {
      key: 'privacy',
      label: 'Datenschutzhinweise der Webseite',
      ok: false,
      blocking: true,
      hint: 'Bitte erzeugen oder eintragen.',
    },
    { key: 'domain', label: 'Domain eingetragen', ok: true, blocking: true, hint: '' },
  ],
  ...extra,
})

const data = (site: unknown, moduleEnabled = true) => ({
  module_enabled: moduleEnabled,
  can_manage: true,
  can_edit_content: true,
  preview_only: false,
  block_labels: {
    board: 'Vorstand und Ansprechpartner',
    events: 'Termine und Kalender-Abo',
    contact: 'Kontaktformular',
  },
  units: [],
  website: site,
})

function renderApp(
  routes: Record<string, () => { status: number; body?: unknown }>,
  path = '/webseite',
) {
  const org = testOrg({
    permissions: ['members.view', 'roles.manage', 'website.manage'],
    modules: ['members', 'website'],
  })
  const calls = fakeApi({
    [SESSION]: loggedIn,
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
  return calls
}

describe('Webseite', () => {
  it('ohne freigeschaltetes Modul nur ein Hinweis', async () => {
    renderApp({ [`GET ${base}`]: () => ({ status: 200, body: data(null, false) }) })
    expect(await screen.findByText(/ist für TV Beispielhausen nicht freigeschaltet/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Webseite einrichten' })).not.toBeInTheDocument()
  })

  it('richtet die Webseite ein und zeigt Zustand, Domain und Vorschau', async () => {
    const calls = renderApp({
      [`GET ${base}`]: () => ({ status: 200, body: data(null) }),
      [`POST ${base}`]: () => ({ status: 201, body: data(website()) }),
      [`GET ${base}held/`]: () => ({ status: 200, body: [] }),
    })
    await userEvent
      .setup()
      .click(await screen.findByRole('button', { name: 'Webseite einrichten' }))
    expect(await screen.findByLabelText(/Zustand der Webseite/)).toHaveValue('maintenance')
    expect(screen.getByRole('button', { name: 'Vorschau öffnen' })).toBeVisible()
    expect(calls.some((c) => c.key === `POST ${base}`)).toBe(true)
    // Domains stehen im eigenen Reiter
    await userEvent.setup().click(screen.getByRole('link', { name: 'Internetadresse' }))
    expect(await screen.findByText('www.beispiel.test')).toBeVisible()
  })

  it('speichert den Zustand automatisch', async () => {
    const calls = renderApp({
      [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
      [`PUT ${base}`]: () => ({ status: 200, body: data(website('public')) }),
      [`GET ${base}held/`]: () => ({
        status: 200,
        body: [
          {
            id: 1,
            recipient_name: 'Verein',
            sender_name: 'Max',
            sender_email: 'max@example.org',
            subject: 'Angebot',
            body: 'Billige Uhren',
            reason: 'enthält 4 Links',
            created_at: '2026-10-28T10:00:00Z',
          },
        ],
      }),
    })
    const user = userEvent.setup()
    const select = await screen.findByLabelText(/Zustand der Webseite/)
    await user.selectOptions(select, 'public')
    await waitFor(() => expect(calls.some((c) => c.key === `PUT ${base}`)).toBe(true), {
      timeout: 3000,
    })
    const put = calls.find((c) => c.key === `PUT ${base}`)
    expect(JSON.parse(String(put?.init?.body))).toEqual({ state: 'public' })
    // Zurückgehaltene Nachrichten unter „Kontaktformular“
    await user.click(screen.getByRole('link', { name: 'Kontaktformular' }))
    expect(await screen.findByText('Grund: enthält 4 Links')).toBeVisible()
  })

  it('stellt die Startseite zusammen', async () => {
    const home = [
      { key: 'carousel', on: true },
      { key: 'greeting', on: true },
      { key: 'events', on: true },
      { key: 'instagram', on: false },
    ]
    const withHome = {
      ...data(website('maintenance', { home_sections: home, blocks: { events: false } })),
      home_labels: {
        carousel: 'Bilderkarussell',
        greeting: 'Willkommenstext',
        events: 'Nächste Termine',
        instagram: 'Instagram-Beiträge',
      },
      home_needs_block: { events: 'events' },
    }
    const calls = renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: withHome }),
        [`PUT ${base}`]: () => ({ status: 200, body: withHome }),
      },
      '/webseite/aufbau',
    )
    const user = userEvent.setup()
    expect(
      await screen.findByText(/Bereich „Termine und Kalender-Abo“ ist oben ausgeschaltet/),
    ).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Willkommenstext nach oben' }))
    await waitFor(() => expect(calls.some((c) => c.key === `PUT ${base}`)).toBe(true), {
      timeout: 3000,
    })
    const put = calls.find((c) => c.key === `PUT ${base}`)
    expect(
      JSON.parse(String(put?.init?.body)).home_sections.map((s: { key: string }) => s.key),
    ).toEqual(['greeting', 'carousel', 'events', 'instagram'])
  })

  it('wählt ein Design und ordnet Farben zu', async () => {
    const designs = ['classic', 'festive', 'sidebar', 'stage', 'newspaper'].map((key) => ({
      key,
      label: {
        classic: 'Klassisch',
        festive: 'Festlich',
        sidebar: 'Seitenleiste',
        stage: 'Bühne',
        newspaper: 'Zeitung',
      }[key],
      hint: 'erfunden',
      roles: [
        { key: 'header', label: 'Kopf', default: 0 },
        { key: 'footer', label: 'Fuß', default: 'dark' },
      ],
    }))
    const body = {
      ...data(website('maintenance', { design: 'classic', color_roles: {} })),
      designs,
      palette: [
        { color: '#1f4e2c', on_color: '#ffffff', name: 'Grün' },
        { color: '#c9a227', on_color: '#1d2421', name: 'Gold' },
        { color: '#8b1e2d', on_color: '#ffffff', name: 'Weinrot' },
      ],
    }
    const calls = renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body }),
        [`PUT ${base}`]: () => ({ status: 200, body }),
      },
      '/webseite/gestaltung',
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('radio', { name: /Festlich/ }))
    await waitFor(() => expect(calls.some((c) => c.key === `PUT ${base}`)).toBe(true), {
      timeout: 3000,
    })
    const put = calls.find((c) => c.key === `PUT ${base}`)
    expect(JSON.parse(String(put?.init?.body)).design).toBe('festive')
    expect(screen.getAllByRole('button', { name: 'Vorschau ansehen' })).toHaveLength(5)
    await user.selectOptions(screen.getByLabelText('Fuß'), '2')
    await waitFor(
      () =>
        expect(
          calls.some(
            (c) =>
              c.key === `PUT ${base}` &&
              JSON.parse(String(c.init?.body)).color_roles?.festive?.footer === 2,
          ),
        ).toBe(true),
      { timeout: 3000 },
    )
    expect(screen.getAllByRole('option', { name: /3\. Farbe \(Weinrot\)/ }).length).toBeGreaterThan(
      0,
    )
  })

  it('alte Adresse Webseite › Datenschutz führt zu Einstellungen › Datenschutz', async () => {
    renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
        [`GET ${base}held/`]: () => ({ status: 200, body: [] }),
        'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
        'GET /api/orgs/7/imprint/': () => ({ status: 404, body: { detail: 'Nicht gefunden.' } }),
      },
      '/webseite/datenschutz',
    )
    expect(
      await screen.findByRole('heading', { name: 'Datenschutzhinweise der Webseite' }),
    ).toBeVisible()
    expect(
      screen.getAllByRole('link', { name: 'Datenschutz' }).map((a) => a.getAttribute('href')),
    ).toContain('/einstellungen/datenschutz')
  })

  it('verlinkt in der Prüfliste das Feld „Verantwortlich“ im Impressum', async () => {
    const site = website('maintenance', {
      checks: [
        {
          key: 'responsible',
          label: 'Verantwortlich für den Inhalt (§ 18 Abs. 2 MStV)',
          ok: false,
          blocking: false,
          hint: 'Die Webseite hat eigene Texte.',
        },
      ],
    })
    renderApp({
      [`GET ${base}`]: () => ({ status: 200, body: data(site) }),
      [`GET ${base}held/`]: () => ({ status: 200, body: [] }),
    })
    // Ralf 2026-10-31: „Wo mache ich das? Kann das hier verlinkt werden?“
    expect(await screen.findByRole('link', { name: 'Erledigen' })).toHaveAttribute(
      'href',
      '/einstellungen/impressum?feld=verantwortlich',
    )
  })

  it('zeigt die Prüfliste und erzeugt die Datenschutzhinweise', async () => {
    const generated = website('maintenance', {
      privacy_text: 'Datenschutzhinweise für die Webseite von TV Beispielhausen',
      privacy_generated_at: '2026-10-28T10:00:00Z',
      checks: [
        { key: 'imprint', label: 'Impressum vollständig', ok: true, blocking: true, hint: '' },
        {
          key: 'privacy',
          label: 'Datenschutzhinweise der Webseite',
          ok: true,
          blocking: true,
          hint: '',
        },
        { key: 'domain', label: 'Domain eingetragen', ok: true, blocking: true, hint: '' },
      ],
    })
    const calls = renderApp({
      [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
      [`GET ${base}held/`]: () => ({ status: 200, body: [] }),
      [`POST ${base}privacy/generate/`]: () => ({ status: 200, body: data(generated) }),
      'GET /api/orgs/7/departments/': () => ({ status: 200, body: [] }),
      'GET /api/orgs/7/imprint/': () => ({ status: 404, body: { detail: 'Nicht gefunden.' } }),
    })
    expect(await screen.findByText('Prüfliste vor dem Veröffentlichen')).toBeVisible()
    expect(screen.getByText(/Bitte erzeugen oder eintragen/)).toBeVisible()
    const user = userEvent.setup()
    // Die Prüfliste führt direkt zu Einstellungen › Datenschutz
    await user.click(screen.getByRole('link', { name: 'Erledigen' }))
    expect(await screen.findByText(/Zwei getrennte Texte für zwei Personengruppen/)).toBeVisible()
    await user.click(await screen.findByRole('button', { name: 'Textentwurf erzeugen' }))
    expect(
      await screen.findByRole('textbox', { name: 'Entwurf der Datenschutzhinweise' }),
    ).toHaveTextContent('Datenschutzhinweise für die Webseite von TV Beispielhausen')
    expect(calls.some((c) => c.key === `POST ${base}privacy/generate/`)).toBe(true)
  })
})

describe('Inhalte der Webseite', () => {
  const text = (over: Record<string, unknown> = {}) => ({
    id: 5,
    kind: 'page',
    kind_label: 'Textseite',
    department: null,
    department_name: null,
    slug: 'geschichte',
    menu_position: 0,
    show_in_menu: true,
    title: 'Geschichte',
    is_published: false,
    has_changes: true,
    published_at: null,
    updated_at: '2026-10-28T10:00:00Z',
    body: 'Gegründet 1920.',
    image: null,
    image_data: null,
    gallery: [],
    gallery_interval: 7,
    gallery_random: false,
    published_title: '',
    published_body: '',
    revisions: [],
    ...over,
  })

  it('öffnet aus der Untereinheit heraus deren Text zum Anlegen', async () => {
    renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
        [`GET ${base}texts/`]: () => ({
          status: 200,
          body: {
            texts: [],
            units: [
              { id: 3, name: 'Erster Zug' },
              { id: 4, name: 'Zweiter Zug' },
            ],
          },
        }),
        [`GET ${base}images/`]: () => ({ status: 200, body: [] }),
      },
      '/webseite/inhalte?einheit=4',
    )
    const select = await screen.findByLabelText(/Untereinheit/)
    expect(select).toHaveValue('4')
  })

  it('öffnet eine Textseite und veröffentlicht sie', async () => {
    const calls = renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
        [`GET ${base}texts/`]: () => ({ status: 200, body: { texts: [text()], units: [] } }),
        [`GET ${base}texts/5/`]: () => ({ status: 200, body: text() }),
        [`GET ${base}images/`]: () => ({ status: 200, body: [] }),
        [`POST ${base}texts/5/publish/`]: () => ({
          status: 200,
          body: text({
            is_published: true,
            has_changes: false,
            published_at: '2026-10-28T11:00:00Z',
            revisions: [
              {
                id: 1,
                title: 'Geschichte',
                published_at: '2026-10-28T11:00:00Z',
                published_by: 'Uwe',
              },
            ],
          }),
        }),
      },
      '/webseite/inhalte',
    )
    const user = userEvent.setup()
    expect(await screen.findByText(/Entwurf, nicht veröffentlicht/)).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Geschichte' }))
    expect(await screen.findByRole('textbox', { name: 'Text' })).toHaveTextContent(
      'Gegründet 1920.',
    )
    await user.click(screen.getByRole('button', { name: 'Veröffentlichen' }))
    expect(await screen.findByText('Frühere Fassungen')).toBeVisible()
    expect(calls.some((c) => c.key === `POST ${base}texts/5/publish/`)).toBe(true)
  })

  const img = (id: number, alt: string, over: Record<string, unknown> = {}) => ({
    id,
    key: `k${id}`,
    caption: '',
    alt_text: alt,
    decorative: false,
    width: 60,
    height: 40,
    url: `/img/${id}`,
    small_url: `/img/${id}?size=small`,
    original_url: `/img/${id}?size=original`,
    markdown: `![${alt}](bild:k${id})`,
    uploaded_at: '2026-10-28T10:00:00Z',
    department: null,
    department_name: null,
    crop: {},
    version: 0,
    used: true,
    ...over,
  })
  const units = [
    { id: 4, name: 'Zweiter Zug' },
    { id: 5, name: 'Dritter Zug' },
  ]

  it('zeigt die Bilder als Kacheln mit Suche und Filtern', async () => {
    renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
        [`GET ${base}texts/`]: () => ({ status: 200, body: { texts: [], units } }),
        [`GET ${base}images/`]: () => ({
          status: 200,
          body: [
            img(1, 'Fahne'),
            img(2, '', { caption: 'Zelt', used: false }),
            img(3, 'Gruppenbild', { department: 4, department_name: 'Zweiter Zug' }),
          ],
        }),
      },
      '/webseite/bilder',
    )
    const user = userEvent.setup()
    expect(await screen.findByText('3 Bilder')).toBeVisible()
    expect(screen.getByText('ohne Beschreibung', { selector: 'small' })).toBeVisible()
    expect(screen.getByText('nicht verwendet', { selector: 'small' })).toBeVisible()
    await user.selectOptions(screen.getByLabelText('Gehört zu'), '4')
    expect(screen.getByText('1 von 3 Bildern')).toBeVisible()
    expect(screen.getByRole('button', { name: /Gruppenbild/ })).toBeVisible()
    await user.selectOptions(screen.getByLabelText('Gehört zu'), 'all')
    await user.selectOptions(screen.getByLabelText('Zustand'), 'no_alt')
    expect(screen.getByRole('button', { name: /Zelt/ })).toBeVisible()
    expect(screen.queryByRole('button', { name: /Fahne/ })).toBeNull()
    await user.selectOptions(screen.getByLabelText('Zustand'), 'all')
    await user.type(screen.getByLabelText('Suchen'), 'fah')
    expect(screen.getByText('1 von 3 Bildern')).toBeVisible()
  })

  it('sortiert die Bilder nach Hochladedatum, Name oder letzter Änderung', async () => {
    renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
        [`GET ${base}texts/`]: () => ({ status: 200, body: { texts: [], units: [] } }),
        [`GET ${base}images/`]: () => ({
          status: 200,
          body: [
            img(1, 'Bühne', {
              uploaded_at: '2026-10-01T10:00:00Z',
              updated_at: '2026-10-30T10:00:00Z',
            }),
            img(2, 'Zelt', {
              uploaded_at: '2026-10-20T10:00:00Z',
              updated_at: '2026-10-20T10:00:00Z',
            }),
            img(3, 'Abzeichen', {
              uploaded_at: '2026-10-10T10:00:00Z',
              updated_at: '2026-10-10T10:00:00Z',
            }),
          ],
        }),
      },
      '/webseite/bilder',
    )
    const user = userEvent.setup()
    await screen.findByText('3 Bilder')
    const order = () =>
      screen
        .getAllByRole('button', { name: /Bühne|Zelt|Abzeichen/ })
        .map((b) => b.textContent?.match(/Bühne|Zelt|Abzeichen/)?.[0])
    expect(order()).toEqual(['Zelt', 'Abzeichen', 'Bühne'])
    await user.selectOptions(screen.getByLabelText('Sortieren'), 'oldest')
    expect(order()).toEqual(['Bühne', 'Abzeichen', 'Zelt'])
    await user.selectOptions(screen.getByLabelText('Sortieren'), 'name')
    expect(order()).toEqual(['Abzeichen', 'Bühne', 'Zelt'])
    await user.selectOptions(screen.getByLabelText('Sortieren'), 'changed')
    expect(order()).toEqual(['Bühne', 'Zelt', 'Abzeichen'])
  })

  it('ändert Angaben und Zuordnung eines Bildes im Fenster „Bild bearbeiten“', async () => {
    const image = img(3, 'Gruppenbild')
    const calls = renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
        [`GET ${base}texts/`]: () => ({ status: 200, body: { texts: [], units } }),
        [`GET ${base}images/`]: () => ({ status: 200, body: [image] }),
        [`GET ${base}images/3/`]: () => ({
          status: 200,
          body: {
            ...image,
            usage: [{ text: 6, label: 'Willkommen', places: ['Bilderkarussell'] }],
          },
        }),
        [`PUT ${base}images/3/`]: () => ({
          status: 200,
          body: { ...image, alt_text: 'Gruppenbild am Zelt', department: 5 },
        }),
      },
      '/webseite/bilder',
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /Gruppenbild/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Bild bearbeiten' })
    expect(await within(dialog).findByRole('link', { name: 'Willkommen' })).toHaveAttribute(
      'href',
      '/webseite/inhalte?text=6',
    )
    expect(within(dialog).getByText(/Bilderkarussell/)).toBeVisible()
    // Nur ein „Schließen“ (oben im Fenster)
    expect(within(dialog).getAllByRole('button', { name: 'Schließen' })).toHaveLength(1)
    const alt = within(dialog).getByLabelText('Alternativtext (was zu sehen ist)')
    await user.clear(alt)
    await user.type(alt, 'Gruppenbild am Zelt')
    await user.selectOptions(within(dialog).getByLabelText(/Gehört zu/), '5')
    await waitFor(
      () => {
        const sent = calls
          .filter((c) => c.key === `PUT ${base}images/3/`)
          .map((c) => JSON.parse(String(c.init?.body)))
        const merged = Object.assign({}, ...sent)
        expect(merged).toEqual({ alt_text: 'Gruppenbild am Zelt', department: 5 })
      },
      { timeout: 3000 },
    )
    // Schließen speichert vorher und schließt das Fenster
    await user.type(alt, '!')
    await user.click(within(dialog).getByRole('button', { name: 'Schließen' }))
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Bild bearbeiten' })).toBeNull(),
    )
    const last = calls.filter((c) => c.key === `PUT ${base}images/3/`).at(-1)
    expect(JSON.parse(String(last?.init?.body))).toEqual({ alt_text: 'Gruppenbild am Zelt!' })
  })

  it('lädt mehrere Bilder hoch und wählt den Ausschnitt später neu', async () => {
    if (!URL.createObjectURL) {
      URL.createObjectURL = vi.fn(() => 'blob:test')
      URL.revokeObjectURL = vi.fn()
    }
    const image = img(3, 'Gruppenbild', {
      crop: { x: 0, y: 0, width: 50, height: 100, rotation: 0, aspect: '16:9' },
    })
    const calls = renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
        [`GET ${base}texts/`]: () => ({ status: 200, body: { texts: [], units } }),
        [`GET ${base}images/`]: () => ({ status: 200, body: [image] }),
        [`POST ${base}images/`]: () => ({ status: 201, body: img(8, '') }),
        [`GET ${base}images/3/`]: () => ({ status: 200, body: { ...image, usage: [] } }),
        'GET /img/3?size=original': () => ({ status: 200, body: 'bild' }),
        [`POST ${base}images/3/crop/`]: () => ({ status: 200, body: { ...image, version: 1 } }),
      },
      '/webseite/bilder',
    )
    const user = userEvent.setup()
    await screen.findByText('1 Bild')
    await user.selectOptions(screen.getByLabelText('Gehört zu'), '4')
    const files = [
      new File(['a'], 'a.jpg', { type: 'image/jpeg' }),
      new File(['b'], 'b.jpg', { type: 'image/jpeg' }),
    ]
    await user.upload(screen.getByLabelText('Bilder hochladen'), files)
    for (let n = 0; n < 2; n++) {
      const crop = await screen.findByRole('dialog', { name: 'Bildausschnitt festlegen' })
      await user.click(within(crop).getByRole('button', { name: 'Unverändert übernehmen' }))
      await waitFor(() =>
        expect(calls.filter((c) => c.key === `POST ${base}images/`)).toHaveLength(n + 1),
      )
    }
    const form = calls.find((c) => c.key === `POST ${base}images/`)!.init!.body as FormData
    // Unverändert: die Datei ist zugleich das Original, neue Bilder gehören zum Filter
    expect(form.get('original')).toBeNull()
    expect(form.get('department')).toBe('4')

    await user.selectOptions(screen.getByLabelText('Gehört zu'), 'all')
    await user.click(screen.getByRole('button', { name: /Gruppenbild/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Bild bearbeiten' })
    await user.click(await within(dialog).findByRole('button', { name: 'Ausschnitt ändern' }))
    const crop = await screen.findByRole('dialog', { name: 'Ausschnitt ändern' })
    // Der zuletzt gewählte Ausschnitt ist vorgewählt
    expect(within(crop).getByLabelText('Seitenverhältnis')).toHaveValue('16:9')
    await user.click(within(crop).getByRole('button', { name: 'Unverändert übernehmen' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === `POST ${base}images/3/crop/`)).toBe(true),
    )
    const sent = calls.find((c) => c.key === `POST ${base}images/3/crop/`)!.init!.body as FormData
    expect(JSON.parse(String(sent.get('crop')))).toMatchObject({ width: 100, height: 100 })
  })

  it('löscht ein verwendetes Bild nach Rückfrage mit den Stellen', async () => {
    const image = img(3, 'Gruppenbild', { caption: 'Gruppenbild' })
    const calls = renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
        [`GET ${base}texts/`]: () => ({ status: 200, body: { texts: [], units: [] } }),
        [`GET ${base}images/`]: () => ({ status: 200, body: [image] }),
        [`GET ${base}images/3/`]: () => ({ status: 200, body: { ...image, usage: [] } }),
        [`DELETE ${base}images/3/`]: () => ({
          status: 409,
          body: {
            detail: 'Das Bild wird noch verwendet: Musterzug: Bilderkarussell.',
            places: ['Musterzug: Bilderkarussell'],
            revisions: [],
          },
        }),
        [`DELETE ${base}images/3/?trotzdem=1`]: () => ({ status: 204 }),
      },
      '/webseite/bilder',
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /Gruppenbild/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Bild bearbeiten' })
    await user.click(await within(dialog).findByRole('button', { name: 'Löschen' }))
    await user.click(
      within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Löschen' }),
    )
    const again = await screen.findByRole('alertdialog', { name: 'Bild trotzdem löschen?' })
    expect(within(again).getByText(/Musterzug: Bilderkarussell/)).toBeVisible()
    await user.click(within(again).getByRole('button', { name: 'Trotzdem löschen' }))
    await waitFor(() =>
      expect(calls.some((c) => c.key === `DELETE ${base}images/3/?trotzdem=1`)).toBe(true),
    )
  })

  it('stellt das Bilderkarussell der Begrüßung zusammen', async () => {
    const greeting = text({ id: 6, kind: 'greeting', title: 'Willkommen', slug: '', gallery: [1] })
    const calls = renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
        [`GET ${base}texts/`]: () => ({ status: 200, body: { texts: [greeting], units: [] } }),
        [`GET ${base}texts/6/`]: () => ({ status: 200, body: greeting }),
        [`GET ${base}images/`]: () => ({ status: 200, body: [img(1, 'Fahne'), img(2, 'Zelt')] }),
        [`PUT ${base}texts/6/`]: () => ({ status: 200, body: { ...greeting, gallery: [2, 1] } }),
      },
      '/webseite/inhalte',
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Willkommen' }))
    await user.click(await screen.findByRole('button', { name: 'Bilder ändern' }))
    const picker = await screen.findByRole('dialog', { name: 'Bilder fürs Karussell' })
    expect(within(picker).getByRole('button', { name: /Fahne/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await user.click(within(picker).getByRole('button', { name: /Zelt/ }))
    await user.click(within(picker).getByRole('button', { name: 'Übernehmen (2 von 10)' }))
    await user.click(screen.getByRole('button', { name: 'Zelt nach vorn' }))
    await waitFor(
      () => {
        const put = calls.filter((c) => c.key === `PUT ${base}texts/6/`).at(-1)
        expect(put && JSON.parse(String(put.init?.body))).toEqual({ gallery: [2, 1] })
      },
      { timeout: 3000 },
    )
  })

  it('stellt Wechselzeit und Startbild je Karussell ein', async () => {
    const greeting = text({
      id: 6,
      kind: 'greeting',
      title: 'Willkommen',
      slug: '',
      gallery: [1, 2],
    })
    const calls = renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
        [`GET ${base}texts/`]: () => ({ status: 200, body: { texts: [greeting], units: [] } }),
        [`GET ${base}texts/6/`]: () => ({ status: 200, body: greeting }),
        [`GET ${base}images/`]: () => ({ status: 200, body: [img(1, 'Fahne'), img(2, 'Zelt')] }),
        [`PUT ${base}texts/6/`]: () => ({
          status: 200,
          body: { ...greeting, gallery_interval: 12 },
        }),
      },
      '/webseite/inhalte',
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Willkommen' }))
    const field = await screen.findByLabelText('Nächstes Bild nach (Sekunden)')
    expect(field).toHaveValue(7)
    await user.clear(field)
    await user.type(field, '12')
    await waitFor(
      () => {
        const put = calls.filter((c) => c.key === `PUT ${base}texts/6/`).at(-1)
        expect(put && JSON.parse(String(put.init?.body))).toEqual({ gallery_interval: 12 })
      },
      { timeout: 3000 },
    )
    await user.selectOptions(screen.getByLabelText('Beginnt mit'), 'einem zufälligen Bild')
    await waitFor(
      () => {
        const put = calls.filter((c) => c.key === `PUT ${base}texts/6/`).at(-1)
        expect(put && JSON.parse(String(put.init?.body))).toEqual({ gallery_random: true })
      },
      { timeout: 3000 },
    )
  })

  it('zeigt bei der Bildauswahl einer Untereinheit zuerst deren Bilder', async () => {
    const unitText = text({
      id: 7,
      kind: 'unit',
      kind_label: 'Text einer Untereinheit',
      department: 4,
      department_name: 'Zweiter Zug',
      title: 'Zweiter Zug',
      slug: '',
    })
    const calls = renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
        [`GET ${base}texts/`]: () => ({ status: 200, body: { texts: [unitText], units } }),
        [`GET ${base}texts/7/`]: () => ({ status: 200, body: unitText }),
        [`GET ${base}images/`]: () => ({
          status: 200,
          body: [
            img(1, 'Vereinsfahne'),
            img(2, 'Zug zwei', { department: 4, department_name: 'Zweiter Zug' }),
            img(3, 'Zug drei', { department: 5, department_name: 'Dritter Zug' }),
          ],
        }),
        [`PUT ${base}texts/7/`]: () => ({ status: 200, body: { ...unitText, image: 2 } }),
      },
      '/webseite/inhalte?text=7',
    )
    const user = userEvent.setup()
    const choice = await screen.findByRole('group', { name: 'Bild der Untereinheit' })
    await user.click(within(choice).getByRole('button', { name: 'Bild wählen' }))
    const picker = await screen.findByRole('dialog', { name: 'Bild der Untereinheit' })
    expect(within(picker).getByRole('button', { name: /Vereinsfahne/ })).toBeVisible()
    expect(within(picker).queryByRole('button', { name: /Zug drei/ })).toBeNull()
    await user.click(within(picker).getByLabelText('nur Zweiter Zug'))
    expect(within(picker).queryByRole('button', { name: /Vereinsfahne/ })).toBeNull()
    expect(within(picker).getByRole('button', { name: /Zug zwei/ })).toBeVisible()
    await user.click(within(picker).getByLabelText('alle Bilder'))
    expect(within(picker).getByRole('button', { name: /Zug drei/ })).toBeVisible()
    await user.click(within(picker).getByRole('button', { name: /Zug zwei/ }))
    expect(await within(choice).findByRole('button', { name: 'Bearbeiten' })).toBeVisible()
    await waitFor(
      () => {
        const put = calls.filter((c) => c.key === `PUT ${base}texts/7/`).at(-1)
        expect(put && JSON.parse(String(put.init?.body))).toEqual({ image: 2 })
      },
      { timeout: 3000 },
    )
  })
})

describe('Veröffentlichung in der Mitgliederakte', () => {
  const path = '/api/orgs/7/members/11/publication/'
  const cat = (category: string, kind: string, active: boolean, published: boolean) => ({
    category,
    label: category === 'name' ? 'Name mit Funktion' : 'Foto',
    kind,
    active,
    published,
    since: active ? '2026-10-01' : null,
    source: active ? 'paper' : '',
    history: [],
  })

  it('zeigt Stand und erfasst eine Einwilligung', async () => {
    const calls = fakeApi({
      [`GET ${path}`]: () => ({
        status: 200,
        body: {
          categories: [
            cat('name', 'objection', false, true),
            cat('photo', 'consent', false, false),
          ],
        },
      }),
      [`PUT ${path}`]: () => ({
        status: 200,
        body: {
          categories: [cat('name', 'objection', false, true), cat('photo', 'consent', true, true)],
        },
      }),
    })
    render(<PublicationSection orgId={7} memberId={11} canEdit />)
    expect(await screen.findByText('kein Widerspruch')).toBeVisible()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Einwilligung erfassen' }))
    expect(await screen.findByText('Einwilligung seit 1.10.2026')).toBeVisible()
    const put = calls.find((c) => c.key === `PUT ${path}`)
    expect(JSON.parse(String(put?.init?.body))).toEqual({
      category: 'photo',
      active: true,
      source: 'paper',
    })
  })

  it('legt einen Instagram-Kanal an und schickt zum Verbinden zu Meta', async () => {
    const feed = {
      id: 5,
      kind: 'instagram',
      kind_label: 'Instagram',
      department: null,
      department_name: null,
      mode: 'auto',
      max_posts: 24,
      show_link: true,
      strip_hashtags: true,
      is_active: true,
      app_id: '',
      config_id: '',
      via_facebook: true,
      has_secret: false,
      status: 'new',
      status_label: 'nicht verbunden',
      account_name: '',
      token_expires_at: null,
      last_sync_at: null,
      last_error: '',
      connected_at: null,
      pages: [],
      post_count: 0,
      pending_count: 0,
    }
    let feeds: unknown[] = []
    const assign = vi.spyOn(leaveTo, 'go').mockImplementation(() => {})
    const calls = renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
        [`GET ${base}social/`]: () => ({
          status: 200,
          body: {
            feeds,
            redirect_uri: 'https://hubiplan.test/api/website/social/callback/',
            units: [],
            can_manage: true,
          },
        }),
        [`POST ${base}social/`]: () => {
          feeds = [feed]
          return { status: 201, body: feed }
        },
        [`PUT ${base}social/5/`]: () => ({
          status: 200,
          body: { ...feed, app_id: '123', has_secret: true },
        }),
        [`POST ${base}social/5/connect/`]: () => ({
          status: 200,
          body: { url: 'https://www.facebook.com/v26.0/dialog/oauth?x=1' },
        }),
      },
      '/webseite/beitraege',
    )
    const user = userEvent.setup()
    expect(await screen.findByText(/Weiterleitungs-URI/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Kanal hinzufügen' }))
    await user.click(screen.getByRole('button', { name: 'Anlegen' }))
    await user.type(await screen.findByLabelText(/^App-ID/), '123')
    await user.type(screen.getByLabelText(/^App-Geheimnis/), 'abc')
    const button = screen.getByRole('button', { name: 'Mit Instagram verbinden' })
    await user.type(screen.getByLabelText(/^Konfigurations-ID/), '987')
    await user.click(button)
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith('https://www.facebook.com/v26.0/dialog/oauth?x=1'),
    )
    const put = calls.find((c) => c.key === `PUT ${base}social/5/`)
    expect(JSON.parse(String(put?.init?.body))).toEqual({
      app_id: '123',
      config_id: '987',
      via_facebook: true,
      app_secret: 'abc',
    })
  })

  it('führt nach der Rückkehr von Meta zur Seite Social-Media-Beiträge', async () => {
    renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
        [`GET ${base}social/`]: () => ({
          status: 200,
          body: { feeds: [], redirect_uri: 'https://x.test/cb/', units: [], can_manage: true },
        }),
      },
      '/social-rueckkehr?fehler=Kein+Konto',
    )
    expect(await screen.findByText(/Nicht verbunden: Kein Konto/)).toBeInTheDocument()
  })
})
