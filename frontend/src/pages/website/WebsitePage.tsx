// Webseite der Einheit: einrichten, dann Unterpunkte (Seitenleiste) Übersicht (Prüfliste, Zustand, Vorschau),
// Inhalte, Gestaltung (Design), Aufbau (Bausteine, Personen, Untereinheiten), Domain und Kontakt. Die Datenschutzhinweise
// der Webseite stehen unter Einstellungen › Datenschutz (WebsitePrivacy.tsx).
// Die Seite selbst zeigt das Projekt „hubiplan-website“.
import { useState } from 'react'
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { SubpageUnavailable } from '../NoticePages.tsx'
import { heldApi, websiteApi } from '../../api/website.ts'
import type {
  HomeSection,
  PreviewLink,
  Website,
  WebsiteData,
  WebsiteSettings,
} from '../../api/website.ts'
import { confirmDialog } from '../../components/dialog.ts'
import {
  errorMessage,
  formatDateTime,
  useAutoSave,
  useForm,
  useLoad,
} from '../../components/forms.ts'
import { Alert, Checkbox, Field, LoadError, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { Term, Why } from '../../learning/Aids.tsx'
import type { TermKey } from '../../learning/content.ts'
import { ContentPage } from './ContentPage.tsx'
import { ImagesPage } from './images.tsx'
import { DesignChooser } from './DesignChooser.tsx'
import { SiteLanguage } from './SiteLanguage.tsx'
import { t } from '../../i18n/index.ts'
import { SocialPage } from './SocialPage.tsx'
import { MenuTree } from './MenuTree.tsx'
import { sectionTitle } from './sections.ts'
import { TextEditor } from '../../components/texteditor/TextEditor.tsx'

const STATE_TEXT: Record<string, string> = {
  off: 'Aus: Die Webseite ist nicht erreichbar.',
  maintenance: 'Wartung: Besucher sehen nur eine Wartungsseite mit Impressum und Datenschutz.',
  public: 'Öffentlich: Die Webseite ist für alle sichtbar.',
}

export function WebsitePage() {
  const org = useActiveOrg()
  const location = useLocation()
  const { data, error, reload, setData } = useLoad(() => websiteApi.get(org.id), [org.id])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  if (error) return <LoadError message={error} onRetry={() => void reload()} />
  if (!data) return <p className="muted">Lädt …</p>

  async function setup() {
    setBusy(true)
    setMessage(null)
    try {
      setData(await websiteApi.setup(org.id))
    } catch (err) {
      setMessage(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="muted small eyebrow">Webseite</p>
          <h1>{data.website ? sectionTitle(location.pathname) : 'Webseite'}</h1>
        </div>
      </div>
      {!data.module_enabled && (
        <Alert kind="info">
          Das Modul „Webseite“ ist für {org.name} nicht freigeschaltet. Die Plattform schaltet es
          für Einheiten frei, die eine eigene Webseite bekommen sollen.
        </Alert>
      )}
      {data.module_enabled && !data.website && (
        <div className="card card-wide">
          <h2>Webseite einrichten</h2>
          <p>
            HUBIplan stellt Vorstand, Untereinheiten, Termine mit Kalender-Abo, Social-Media-Links
            und ein Kontaktformular für eine öffentliche Webseite bereit. Personendaten erscheinen
            nur nach den Regeln zu Einwilligung und Widerspruch.
          </p>
          <p className="muted small">
            Eine neue Webseite startet im Wartungsmodus: Besucher sehen nur einen Hinweis, du selbst
            kannst sie in der Vorschau ansehen.
          </p>
          {message && <Alert kind="error">{message}</Alert>}
          {data.can_manage && (
            <button type="button" className="button" disabled={busy} onClick={() => void setup()}>
              Webseite einrichten
            </button>
          )}
        </div>
      )}
      {data.website && (
        <WebsiteAdmin
          key={data.website.public_key}
          data={data}
          website={data.website}
          onChange={setData}
          reload={() => void reload()}
        />
      )}
    </section>
  )
}

const SETTINGS: (keyof WebsiteSettings)[] = [
  'state',
  'maintenance_text',
  'blocks',
  'menu',
  'home_sections',
  'design',
  'color_roles',
  'name_format',
  'show_vacant',
  'missing_consent',
  'units_mode',
  'unit_ids',
  'include_unit_events',
  'include_parent_events',
  'include_parent_honors',
  'allow_indexing',
  'language',
  'contact_limit_per_hour',
]

function pick(w: Website): WebsiteSettings {
  return Object.fromEntries(SETTINGS.map((k) => [k, w[k]])) as unknown as WebsiteSettings
}

function WebsiteAdmin({
  data,
  website,
  onChange,
  reload,
}: {
  data: WebsiteData
  website: Website
  onChange: (data: WebsiteData) => void
  reload: () => void
}) {
  const org = useActiveOrg()
  const form = useForm(pick(website))
  const { values: v, set, errors } = form
  const auto = useAutoSave(form, (changes) => websiteApi.save(org.id, changes), {
    enabled: data.can_manage,
    onSaved: (saved) => onChange(saved as WebsiteData),
  })
  const [message, setMessage] = useState<string | null>(null)

  async function remove() {
    const ok = await confirmDialog({
      title: 'Webseite entfernen?',
      message:
        'Einstellungen, Domains und Vorschau-Links werden gelöscht. Die Daten in HUBIplan (Mitglieder, Termine, Einwilligungen) bleiben erhalten.',
      confirmLabel: 'Entfernen',
    })
    if (!ok) return
    try {
      await websiteApi.remove(org.id)
      reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  const settings = (title: string, children: React.ReactNode) => (
    <form className="card card-wide" onSubmit={(e) => e.preventDefault()}>
      {data.can_manage && <SaveStatus auto={auto} />}
      <h2>{title}</h2>
      <fieldset disabled={!data.can_manage}>{children}</fieldset>
    </form>
  )

  const overview = (
    <>
      <ChecklistCard website={website} />
      {settings(
        'Zustand',
        <>
          <SelectField
            label="Zustand der Webseite"
            value={v.state}
            error={errors.state}
            hint={STATE_TEXT[v.state]}
            onChange={(e) => set('state', e.target.value as WebsiteSettings['state'])}
          >
            <option value="off">Aus</option>
            <option value="maintenance">Wartung</option>
            <option value="public">Öffentlich</option>
          </SelectField>
          {data.preview_only && (
            <Alert kind="info">
              Auf diesem Server sind alle Webseiten nur in der Vorschau sichtbar (Testserver).
            </Alert>
          )}
          <TextEditor
            label="Hinweis auf der Wartungsseite"
            value={v.maintenance_text}
            error={errors.maintenance_text}
            rows={3}
            onChange={(text) => set('maintenance_text', text)}
          />
          <p className="muted small">
            Schlüssel der Webseite in der öffentlichen Schnittstelle:{' '}
            <code>{website.public_key}</code>
          </p>
        </>,
      )}
      <PreviewCard data={data} website={website} onChange={reload} />
      {data.can_manage && (
        <div className="card card-wide">
          <h2>Webseite entfernen</h2>
          {message && <Alert kind="error">{message}</Alert>}
          <button type="button" className="button button-danger" onClick={() => void remove()}>
            Webseite entfernen
          </button>
        </div>
      )}
    </>
  )

  const design = (
    <>
      {data.designs ? (
        settings(
          'Design',
          <DesignChooser
            data={data}
            design={v.design ?? 'classic'}
            colorRoles={v.color_roles ?? {}}
            onDesign={(key) => set('design', key)}
            onColorRoles={(next) => set('color_roles', next)}
          />,
        )
      ) : (
        <Alert kind="info">Auf diesem Server gibt es keine Designs zur Auswahl.</Alert>
      )}
      <SiteLanguage
        value={v.language ?? 'de'}
        error={errors.language}
        render={(field) => settings(t('Sprache der Webseite'), field)}
        onChange={(lang) => set('language', lang)}
      />
    </>
  )

  const structure = (
    <>
      {settings(
        'Bausteine',
        <>
          <p className="muted small">
            Welche Bereiche die Webseite zeigt, in der Reihenfolge des Menüs.
          </p>
          {website.menu_items && (
            <MenuTree
              items={website.menu_items}
              value={v.menu ?? []}
              blocks={v.blocks}
              disabled={!data.can_manage}
              onChange={(next) => set('menu', next)}
              onToggle={(key, on) => set('blocks', { ...v.blocks, [key]: on })}
            />
          )}
          {Object.entries(data.block_labels)
            .filter(([key]) => !website.menu_items?.some((it) => it.toggle === key))
            .map(([key, label]) => (
              <Checkbox
                key={key}
                label={label}
                hint={data.block_hints?.[key]}
                checked={v.blocks[key] ?? true}
                onChange={(on) => set('blocks', { ...v.blocks, [key]: on })}
              />
            ))}
        </>,
      )}
      {data.home_labels &&
        v.home_sections &&
        settings(
          'Startseite',
          <HomeSections
            data={data}
            value={v.home_sections}
            blocks={v.blocks}
            onChange={(next) => set('home_sections', next)}
          />,
        )}
      {settings(
        'Personen',
        <>
          <div className="grid-2">
            <SelectField
              label="Namensform"
              value={v.name_format}
              onChange={(e) => set('name_format', e.target.value as WebsiteSettings['name_format'])}
            >
              <option value="full">Vorname Name</option>
              <option value="initial">Vorname N.</option>
            </SelectField>
            <SelectField
              label="Personen ohne Einwilligung (z. B. in der Chronik)"
              value={v.missing_consent}
              onChange={(e) =>
                set('missing_consent', e.target.value as WebsiteSettings['missing_consent'])
              }
            >
              <option value="omit">auslassen</option>
              <option value="nn">als „N. N.“ zeigen</option>
            </SelectField>
          </div>
          <div className="aid-row">
            <Why k="web_names" />
            <Why k="web_consent" />
          </div>
          <Checkbox
            label="Unbesetzte Funktionen als „derzeit unbesetzt“ zeigen"
            checked={v.show_vacant}
            onChange={(on) => set('show_vacant', on)}
          />
          <p className="muted small">
            Welche Funktionen erscheinen, legst du an den Rollen fest („auf der Webseite zeigen“).
            Einwilligungen und Widersprüche stehen in der Mitgliederakte unter „Veröffentlichung“.
          </p>
        </>,
      )}
      {settings(
        'Untereinheiten',
        <>
          <SelectField
            label="Untereinheiten auf der Webseite"
            value={v.units_mode}
            onChange={(e) => set('units_mode', e.target.value as WebsiteSettings['units_mode'])}
          >
            <option value="all">alle</option>
            <option value="selected">ausgewählte</option>
            <option value="none">keine</option>
          </SelectField>
          {v.units_mode === 'selected' &&
            data.units.map((u) => (
              <Checkbox
                key={u.id}
                label={u.name}
                checked={v.unit_ids.includes(u.id)}
                onChange={(on) =>
                  set(
                    'unit_ids',
                    on ? [...v.unit_ids, u.id] : v.unit_ids.filter((id) => id !== u.id),
                  )
                }
              />
            ))}
          {errors.unit_ids && <Alert kind="error">{errors.unit_ids}</Alert>}
        </>,
      )}
      {settings(
        'Termine',
        <>
          <Checkbox
            label="Öffentliche Termine der Untereinheiten im Kalender der Webseite"
            checked={v.include_unit_events}
            onChange={(on) => set('include_unit_events', on)}
          />
          <Checkbox
            label="Öffentliche Termine der übergeordneten Einheiten im Kalender der Webseite"
            hint="z. B. Dachverband; nur Termine, die nach unten freigegeben sind"
            checked={v.include_parent_events}
            onChange={(on) => set('include_parent_events', on)}
          />
        </>,
      )}
      {settings(
        'Würdenträger',
        <>
          <Checkbox
            label="Weitergegebene Würden der übergeordneten Einheiten zeigen"
            hint="z. B. Könige des Dachverbands; nur die Träger, die aus eurer Einheit kamen"
            checked={v.include_parent_honors}
            onChange={(on) => set('include_parent_honors', on)}
          />
        </>,
      )}
    </>
  )

  const domain = (
    <>
      <DomainsCard data={data} website={website} onChange={reload} />
      {settings(
        'Suchmaschinen',
        <>
          <Checkbox
            label="Suchmaschinen dürfen die Webseite aufnehmen"
            checked={v.allow_indexing}
            onChange={(on) => set('allow_indexing', on)}
          />
          <Why k="web_indexing" />
        </>,
      )}
    </>
  )

  const contact = (
    <>
      {settings(
        'Kontaktformular',
        <Field
          label="Höchstens Mails aus dem Kontaktformular je Stunde"
          type="number"
          min={1}
          max={100}
          value={v.contact_limit_per_hour}
          error={errors.contact_limit_per_hour}
          hint="Schützt das Postfach vor Massenversand (Mails von Rundschreiben zählen beim Anbieter mit)."
          onChange={(e) => set('contact_limit_per_hour', Number(e.target.value))}
        />,
      )}
      {data.can_manage && <HeldCard />}
    </>
  )

  return (
    <>
      <Routes>
        <Route index element={overview} />
        <Route
          path="inhalte"
          element={
            data.can_edit_content ? (
              <ContentPage />
            ) : (
              <Alert kind="info">Dafür fehlt dir das Recht „Inhalte bearbeiten“.</Alert>
            )
          }
        />
        <Route
          path="bilder"
          element={
            data.can_edit_content ? (
              <ImagesPage />
            ) : (
              <Alert kind="info">Dafür fehlt dir das Recht „Inhalte bearbeiten“.</Alert>
            )
          }
        />
        <Route
          path="beitraege"
          element={
            data.can_edit_content ? (
              <SocialPage />
            ) : (
              <Alert kind="info">Dafür fehlt dir das Recht „Inhalte bearbeiten“.</Alert>
            )
          }
        />
        <Route path="gestaltung" element={design} />
        <Route path="aufbau" element={structure} />
        <Route path="domain" element={domain} />
        <Route path="kontakt" element={contact} />
        {/* Datenschutzhinweise stehen jetzt unter Einstellungen › Datenschutz */}
        <Route path="datenschutz" element={<Navigate to="/einstellungen/datenschutz" replace />} />
        <Route path="*" element={<SubpageUnavailable to="/webseite" label="Zur Webseite" />} />
      </Routes>
    </>
  )
}

/** Bausteine der Startseite: ein/aus und Reihenfolge (↑ ↓). */
function HomeSections({
  data,
  value,
  blocks,
  onChange,
}: {
  data: WebsiteData
  value: HomeSection[]
  blocks: Record<string, boolean>
  onChange: (next: HomeSection[]) => void
}) {
  const labels = data.home_labels ?? {}
  const move = (index: number, delta: number) => {
    const next = [...value]
    const [item] = next.splice(index, 1)
    next.splice(index + delta, 0, item)
    onChange(next)
  }
  return (
    <>
      <p className="muted small">
        Was die Startseite zeigt, von oben nach unten. Die Reihenfolge änderst du mit den Pfeilen.
      </p>
      <ol className="home-sections">
        {value.map((s, index) => {
          // Bausteine ohne Bezeichnung gibt es hier nicht (z. B. Ergebnisse ohne Modul)
          if (!labels[s.key]) return null
          const label = labels[s.key]
          const needs = data.home_needs_block?.[s.key]
          const blockOff = needs ? blocks[needs] === false : false
          const hint = blockOff
            ? `Erscheint nicht: Der Bereich „${data.block_labels[needs!] ?? needs}“ ist oben ausgeschaltet.`
            : data.home_hints?.[s.key]
          return (
            <li key={s.key}>
              <Checkbox
                label={label}
                hint={hint}
                checked={s.on}
                onChange={(on) => onChange(value.map((x) => (x.key === s.key ? { ...x, on } : x)))}
              />
              <span className="button-row">
                <button
                  type="button"
                  className="button button-ghost"
                  disabled={index === 0}
                  aria-label={`${label} nach oben`}
                  onClick={() => move(index, -1)}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="button button-ghost"
                  disabled={index === value.length - 1}
                  aria-label={`${label} nach unten`}
                  onClick={() => move(index, 1)}
                >
                  ↓
                </button>
              </span>
            </li>
          )
        })}
      </ol>
    </>
  )
}

function DomainsCard({
  data,
  website,
  onChange,
}: {
  data: WebsiteData
  website: Website
  onChange: () => void
}) {
  const org = useActiveOrg()
  const [host, setHost] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
      onChange()
      return true
    } catch (err) {
      setError(errorMessage(err))
      return false
    }
  }

  return (
    <div className="card card-wide">
      <h2>Domains</h2>
      <p className="muted small">
        Unter diesen Adressen erkennt die Webseite {org.name}. Die Domain muss beim Anbieter auf den
        Server der Webseite zeigen.
      </p>
      {website.domains.length === 0 && <p className="muted">Noch keine Domain eingetragen.</p>}
      <ul className="plain-list">
        {website.domains.map((d) => (
          <li key={d.id}>
            <strong>{d.hostname}</strong>
            {d.is_primary ? ' (Hauptadresse)' : ''}
            {data.can_manage && (
              <span className="button-row">
                {!d.is_primary && (
                  <button
                    type="button"
                    className="button button-ghost"
                    onClick={() => void run(() => websiteApi.makePrimary(org.id, d.id))}
                  >
                    Als Hauptadresse
                  </button>
                )}
                <button
                  type="button"
                  className="button button-ghost"
                  aria-label={`${d.hostname} entfernen`}
                  onClick={() => void run(() => websiteApi.removeDomain(org.id, d.id))}
                >
                  Entfernen
                </button>
              </span>
            )}
          </li>
        ))}
      </ul>
      {error && <Alert kind="error">{error}</Alert>}
      {data.can_manage && (
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault()
            void run(() => websiteApi.addDomain(org.id, host)).then((ok) => ok && setHost(''))
          }}
        >
          <Field
            label="Domain hinzufügen"
            placeholder="www.beispiel-verein.de"
            value={host}
            onChange={(e) => setHost(e.target.value)}
          />
          <button type="submit" className="button" disabled={!host.trim()}>
            Hinzufügen
          </button>
        </form>
      )}
    </div>
  )
}

/** Was vor dem Schalten auf „öffentlich“ erledigt sein muss. */
const CHECK_LINKS: Record<string, string> = {
  imprint: '/einstellungen/impressum',
  responsible: '/einstellungen/impressum?feld=verantwortlich',
  privacy: '/einstellungen/datenschutz',
  privacy_outdated: '/einstellungen/datenschutz',
  domain: '/webseite/domain',
}

/** Begriffe mit „?“ an den Punkten der Prüfliste */
const CHECK_TERMS: Partial<Record<string, TermKey>> = {
  imprint: 'imprint',
  responsible: 'responsible',
}

function ChecklistCard({ website }: { website: Website }) {
  const open = website.checks.filter((c) => !c.ok)
  return (
    <div className="card card-wide">
      <h2>Prüfliste vor dem Veröffentlichen</h2>
      {open.length === 0 && <Alert kind="success">Alles erledigt.</Alert>}
      <ul className="plain-list">
        {website.checks.map((c) => (
          <li key={c.key}>
            <span aria-hidden="true">{c.ok ? '✓' : c.blocking ? '✗' : '!'}</span>{' '}
            <strong>
              {CHECK_TERMS[c.key] ? <Term k={CHECK_TERMS[c.key]!}>{c.label}</Term> : c.label}
            </strong>
            {!c.ok && (
              <>
                {' '}
                <span className="muted small">
                  {c.blocking ? '(nötig) ' : '(Empfehlung) '}
                  {c.hint}
                </span>
                {CHECK_LINKS[c.key] && (
                  <>
                    {' '}
                    <Link to={CHECK_LINKS[c.key]} className="small">
                      Erledigen
                    </Link>
                  </>
                )}
              </>
            )}
          </li>
        ))}
      </ul>
      {open.some((c) => c.blocking) && (
        <p className="muted small">
          Solange ein nötiger Punkt offen ist, lässt sich die Webseite nicht auf „Öffentlich“
          schalten.
        </p>
      )}
    </div>
  )
}

function PreviewCard({
  data,
  website,
  onChange,
}: {
  data: WebsiteData
  website: Website
  onChange: () => void
}) {
  const org = useActiveOrg()
  const [label, setLabel] = useState('')
  const [days, setDays] = useState(7)
  const [created, setCreated] = useState<PreviewLink | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Nach dem Warten blockt mancher Browser das neue Fenster: dann hilft der Link
  const [opened, setOpened] = useState<string | null>(null)

  async function open() {
    setError(null)
    setOpened(null)
    try {
      const result = await websiteApi.openPreview(org.id)
      if (result.url) {
        window.open(result.url, '_blank', 'noopener')
        setOpened(result.url)
      } else setError('Für die Vorschau fehlt noch eine Domain.')
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function create() {
    setError(null)
    try {
      setCreated(await websiteApi.addPreviewLink(org.id, label, days))
      setLabel('')
      onChange()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function revoke(link: PreviewLink) {
    setError(null)
    try {
      await websiteApi.revokePreviewLink(org.id, link.id)
      onChange()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="card card-wide">
      <h2>Vorschau</h2>
      <p className="muted small">
        In der Vorschau siehst du die vollständige Webseite, auch im Wartungsmodus, mit dem Hinweis
        „Vorschau – nicht öffentlich“.
      </p>
      {error && <Alert kind="error">{error}</Alert>}
      <button type="button" className="button" onClick={() => void open()}>
        Vorschau öffnen
      </button>
      {opened && (
        <p className="muted small">
          Kein neues Fenster?{' '}
          <a href={opened} target="_blank" rel="noopener noreferrer">
            Vorschau hier öffnen
          </a>
          .
        </p>
      )}
      {data.can_manage && (
        <>
          <h3>Vorschau-Links zum Weitergeben</h3>
          <p className="muted small">
            Zum Beispiel für Vorstandsmitglieder ohne Zugang zu HUBIplan. Jeder Link gilt höchstens
            14 Tage und lässt sich jederzeit widerrufen.
          </p>
          {created?.url && (
            <Alert kind="success">
              Neuer Link (wird nur jetzt angezeigt): <code>{created.url}</code>
            </Alert>
          )}
          {created && !created.url && (
            <Alert kind="info">
              Link angelegt. Für eine Adresse fehlt noch eine Domain; Schlüssel:{' '}
              <code>{created.token}</code>
            </Alert>
          )}
          <ul className="plain-list">
            {website.preview_links.map((link) => (
              <li key={link.id}>
                {link.label || 'Vorschau-Link'} · gültig bis {formatDateTime(link.expires_at)}
                {!link.is_active ? ' (abgelaufen)' : ''}{' '}
                <button
                  type="button"
                  className="button button-ghost"
                  onClick={() => void revoke(link)}
                >
                  Widerrufen
                </button>
              </li>
            ))}
          </ul>
          <div className="grid-2">
            <Field
              label="Bezeichnung (z. B. für wen)"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
            <Field
              label="Gültig (Tage)"
              type="number"
              min={1}
              max={14}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            />
          </div>
          <button type="button" className="button" onClick={() => void create()}>
            Vorschau-Link erzeugen
          </button>
        </>
      )}
    </div>
  )
}

function HeldCard() {
  const org = useActiveOrg()
  const { data, error, reload } = useLoad(() => heldApi.list(org.id), [org.id])
  const [message, setMessage] = useState<string | null>(null)

  async function run(action: () => Promise<unknown>) {
    setMessage(null)
    try {
      await action()
      void reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  return (
    <div className="card card-wide">
      <h2>Zurückgehaltene Nachrichten</h2>
      <p className="muted small">
        Nachrichten aus dem Kontaktformular, die nach Spam aussehen oder über der Obergrenze je
        Stunde lagen. Sie werden nach 7 Tagen automatisch gelöscht.
      </p>
      {error && <LoadError message={error} onRetry={() => void reload()} />}
      {data && data.length === 0 && <p className="muted">Keine.</p>}
      <ul className="plain-list">
        {(data ?? []).map((m) => (
          <li key={m.id}>
            <strong>{m.subject}</strong> · von {m.sender_name} ({m.sender_email}) an{' '}
            {m.recipient_name} · {formatDateTime(m.created_at)}
            <br />
            <small className="muted">Grund: {m.reason}</small>
            <p className="mail-body">{m.body}</p>
            <div className="button-row">
              <button
                type="button"
                className="button"
                onClick={() => void run(() => heldApi.release(org.id, m.id))}
              >
                Zustellen
              </button>
              <button
                type="button"
                className="button button-ghost"
                onClick={() => void run(() => heldApi.discard(org.id, m.id))}
              >
                Verwerfen
              </button>
            </div>
          </li>
        ))}
      </ul>
      {message && <Alert kind="error">{message}</Alert>}
    </div>
  )
}
