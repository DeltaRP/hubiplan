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

  it('löscht ein verwendetes Bild nach Rückfrage mit den Stellen', async () => {
    const image = {
      id: 3,
      key: 'k3',
      caption: 'Gruppenbild',
      alt_text: 'Gruppenbild',
      width: 60,
      height: 40,
      url: '/img/3',
      small_url: '/img/3?size=small',
      markdown: '![Gruppenbild](bild:k3)',
      uploaded_at: '2026-10-28T10:00:00Z',
    }
    const calls = renderApp(
      {
        [`GET ${base}`]: () => ({ status: 200, body: data(website()) }),
        [`GET ${base}texts/`]: () => ({ status: 200, body: { texts: [], units: [] } }),
        [`GET ${base}images/`]: () => ({ status: 200, body: [image] }),
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
      '/webseite/inhalte',
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Bild Gruppenbild löschen' }))
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
    const img = (id: number, alt: string) => ({
      id,
      key: `k${id}`,
      caption: '',
      alt_text: alt,
      width: 60,
      height: 40,
      url: `/img/${id}`,
      small_url: `/img/${id}?size=small`,
      markdown: '',
      uploaded_at: '2026-10-28T10:00:00Z',
    })
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
    await user.selectOptions(await screen.findByLabelText('Bild hinzufügen'), '2')
    await user.click(screen.getByRole('button', { name: 'Zelt nach vorn' }))
    await waitFor(
      () => {
        const put = calls.filter((c) => c.key === `PUT ${base}texts/6/`).at(-1)
        expect(put && JSON.parse(String(put.init?.body))).toEqual({ gallery: [2, 1] })
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
