import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { displayName, platformApi } from '../../api/orgs.ts'
import type { PlatformOrg, PlatformSettings } from '../../api/orgs.ts'
import { Alert, Checkbox, Field, LoadError, SelectField, Tabs } from '../../components/ui.tsx'
import { errorMessage, formatDate, useForm, useLoad } from '../../components/forms.ts'
import { useOrg } from '../../org/OrgContext.tsx'
import { peeringApi } from '../../api/peering.ts'
import type { InstanceKeys, PendingPeerKeys } from '../../api/peering.ts'
import { portalApi } from '../../api/portal.ts'
import { OutboxBrowser } from '../../components/OutboxList.tsx'
import { ExportSection, ImportSection } from '../../components/DataTransfer.tsx'
import { LabelFields } from '../../components/LabelFields.tsx'
import { buildTerms } from '../../org/terms.ts'
import { Why } from '../../learning/Aids.tsx'

// Vorschlag für die Bezeichnung neuer Einheiten, je nachdem, ob sie eigene Mitglieder
// führen (wie im Backend). Jede Einheit kann ihre Bezeichnung frei ändern.
const DEFAULT_LABELS = {
  without: {
    label: 'Dachverband',
    plural: 'Dachverbände',
    gender: 'm',
    genitive: 'Dachverbands',
  },
  members: { label: 'Verein', plural: 'Vereine', gender: 'm', genitive: 'Vereins' },
} as const

function suggestedLabels(keeps: boolean) {
  return DEFAULT_LABELS[keeps ? 'members' : 'without']
}

const ACCESS_LABELS = { none: 'kein Zugriff', read: 'nur lesen', write: 'lesen und ändern' }
const MODULES = [
  { id: 'members', label: 'Mitglieder' },
  { id: 'finance', label: 'Kasse' },
  { id: 'billing', label: 'Beiträge/Rechnungen' },
  { id: 'events', label: 'Termine' },
  { id: 'website', label: 'Webseite' },
  { id: 'competitions', label: 'Wettbewerbe' },
  { id: 'entries', label: 'Meldungen' },
]

export function PlatformLayout() {
  const location = useLocation()
  if (location.pathname.replace(/\/$/, '') === '/plattform') {
    return <Navigate to="/plattform/organisationen" replace />
  }
  return (
    <section>
      <h1>Plattform</h1>
      <Tabs
        items={[
          { to: '/plattform/organisationen', label: 'Einheiten' },
          { to: '/plattform/einstellungen', label: 'Einstellungen' },
          { to: '/plattform/impressum', label: 'Impressum' },
          { to: '/plattform/postfach', label: 'Postfach' },
          { to: '/plattform/datenuebernahme', label: 'Datenübernahme' },
        ]}
      />
      <Outlet />
    </section>
  )
}

export function PlatformOrgsPage() {
  const { data, error, reload } = useLoad(() => platformApi.orgs(), [])
  const [editing, setEditing] = useState<PlatformOrg | 'new' | null>(null)

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>

  const federations = data.filter((o) => o.type === 'federation')
  const clubsOf = (fed: number | null) =>
    data.filter((o) => o.type === 'club' && o.federation === fed)

  if (editing !== null) {
    return (
      <PlatformOrgForm
        org={editing === 'new' ? null : editing}
        parents={federations}
        onDone={async () => {
          setEditing(null)
          await reload()
        }}
        onCancel={() => setEditing(null)}
      />
    )
  }

  const row = (o: PlatformOrg, indent = false) => (
    <tr key={o.id} className={o.is_active ? '' : 'inactive'}>
      <td className={indent ? 'indent' : ''}>
        <strong>{displayName(o)}</strong>
        <div className="small muted">
          {o.short_name && `${o.name} · `}
          {o.type_label} · {o.postal_code} {o.city}
          {!o.is_active && ' · deaktiviert'}
        </div>
      </td>
      <td className="small">
        <div>{o.keeps_members ? 'führt eigene Mitglieder' : 'ohne eigene Mitglieder'}</div>
        {o.type === 'federation' && (
          <div>Mitgliedsdaten darunter: {ACCESS_LABELS[o.federation_member_access]}</div>
        )}
        <div className="muted">
          {o.enabled_modules.length
            ? `Module: ${o.enabled_modules.map((m) => MODULES.find((x) => x.id === m)?.label ?? m).join(', ')}`
            : 'keine Module'}
        </div>
      </td>
      <td className="actions">
        <button type="button" className="link-button" onClick={() => setEditing(o)}>
          Bearbeiten
        </button>
      </td>
    </tr>
  )

  return (
    <div className="card card-wide">
      <div className="button-row">
        <button type="button" className="button button-primary" onClick={() => setEditing('new')}>
          Einheit anlegen
        </button>
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>Einheit</th>
            <th>Freigaben</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {federations.flatMap((f) => [row(f), ...clubsOf(f.id).map((c) => row(c, true))])}
          {clubsOf(null).map((c) => row(c))}
        </tbody>
      </table>
    </div>
  )
}

function PlatformOrgForm({
  org,
  parents,
  onDone,
  onCancel,
}: {
  org: PlatformOrg | null
  /** Einheiten, unter denen Einheiten mit eigenen Mitgliedern angelegt werden können */
  parents: PlatformOrg[]
  onDone: () => void
  onCancel: () => void
}) {
  const { refresh } = useOrg()
  const initialKeeps = org ? !!org.keeps_members : true
  const form = useForm({
    keeps_members: initialKeeps,
    federation: org?.federation ?? null,
    name: org?.name ?? '',
    short_name: org?.short_name ?? '',
    founding_year: org?.founding_year ? String(org.founding_year) : '',
    street: org?.street ?? '',
    postal_code: org?.postal_code ?? '',
    city: org?.city ?? '',
    country: org?.country ?? 'Deutschland',
    contact_email: org?.contact_email ?? '',
    contact_phone: org?.contact_phone ?? '',
    website: org?.website ?? '',
    label: org?.label ?? suggestedLabels(initialKeeps).label,
    label_plural: org?.label_plural ?? suggestedLabels(initialKeeps).plural,
    label_gender: org?.label_gender ?? suggestedLabels(initialKeeps).gender,
    label_genitive: org?.label_genitive ?? suggestedLabels(initialKeeps).genitive,
    federation_member_access: org?.federation_member_access ?? 'none',
    federation_show_former_memberships: org?.federation_show_former_memberships ?? false,
    enabled_modules: org?.enabled_modules ?? ['finance', 'members'],
    is_active: org?.is_active ?? true,
  })
  const v = form.values
  const e = form.errors
  const [board, setBoard] = useState('')
  const [boardResult, setBoardResult] = useState<string | null>(null)
  const t = buildTerms(v.label, v.label_plural, v.label_gender, v.label_genitive)
  // Unter einer übergeordneten Einheit führen Einheiten immer eigene Mitglieder
  const underParent = v.federation !== null
  const switchable = org ? !!org.can_switch_members : !underParent
  // Zugriff nach unten: Einheiten, die andere Einheiten mit eigenen Mitgliedern zusammenfassen
  const groupsUnits = org ? org.type === 'federation' : !underParent && !v.keeps_members

  function setKeeps(keeps: boolean) {
    form.set('keeps_members', keeps)
    // Vorschlag für die Bezeichnung mitziehen, solange keine eigene gewählt ist
    const before = suggestedLabels(v.keeps_members)
    if (v.label === before.label && v.label_plural === before.plural) {
      const next = suggestedLabels(keeps)
      form.set('label', next.label)
      form.set('label_plural', next.plural)
      form.set('label_gender', next.gender)
      form.set('label_genitive', next.genitive)
    }
  }

  async function save(ev: FormEvent) {
    ev.preventDefault()
    const { keeps_members, ...rest } = v
    const payload = {
      ...rest,
      // Nur senden, was sich ändern lässt
      ...(switchable && (!org || keeps_members !== initialKeeps) ? { keeps_members } : {}),
      founding_year: v.founding_year ? Number(v.founding_year) : null,
    } as Partial<PlatformOrg>
    const ok = await form.submit(() =>
      org ? platformApi.update(org.id, payload) : platformApi.create(payload),
    )
    if (ok) {
      await refresh()
      onDone()
    }
  }

  async function addBoard(ev: FormEvent) {
    ev.preventDefault()
    if (!org) return
    const res = await form.submit(() => platformApi.addBoard(org.id, board), 'Vorstand zugeordnet.')
    if (res) {
      const r = res as { email: string; invited: boolean; new_account: boolean }
      setBoardResult(
        !r.new_account
          ? `${r.email} hat jetzt die Rolle „Vorstand“.`
          : r.invited
            ? `Neues Konto ${r.email} angelegt; die Einladung zum Festlegen des Passworts ist per E-Mail unterwegs (gilt 7 Tage).`
            : `Neues Konto ${r.email} angelegt, aber die Einladung konnte nicht verschickt werden. Die Person kann auf der Anmeldeseite „Passwort vergessen“ wählen.`,
      )
      setBoard('')
    }
  }

  return (
    <div className="stack">
      <form className="card card-wide" onSubmit={save}>
        <h2>{org ? `${t.Sg} bearbeiten` : `${t.Sg} anlegen`}</h2>
        {(!org || org.keeps_members) && (
          <SelectField
            label="Übergeordnete Einheit"
            value={v.federation ?? ''}
            error={e.federation}
            onChange={(ev) => {
              const parent = ev.target.value ? Number(ev.target.value) : null
              form.set('federation', parent)
              if (parent !== null && !v.keeps_members) setKeeps(true)
            }}
          >
            <option value="">– keine (direkt unter der Plattform) –</option>
            {parents
              .filter((p) => p.id !== org?.id)
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {displayName(p)}
                </option>
              ))}
          </SelectField>
        )}
        <Checkbox
          label="Führt eigene Mitglieder (Mitgliederliste, Mitgliedsarten, Ein- und Austritt)"
          checked={underParent || v.keeps_members}
          disabled={!switchable}
          onChange={setKeeps}
        />
        {e.keeps_members && <Alert kind="error">{e.keeps_members}</Alert>}
        <p className="small muted">
          {underParent
            ? 'Unter einer übergeordneten Einheit führen Einheiten immer eigene Mitglieder.'
            : org && !switchable
              ? 'Lässt sich nur ändern, solange die Einheit keine eigenen Mitglieder und keine Untereinheiten hat.'
              : 'Ohne eigene Mitglieder fasst die Einheit andere Einheiten zusammen, die Mitglieder führen. Umschalten geht, solange die Einheit leer ist.'}
        </p>
        <div className="grid-2">
          <Field
            label="Vollständiger Name"
            required
            value={v.name}
            error={e.name}
            onChange={(ev) => form.set('name', ev.target.value)}
          />
          <Field
            label="Kurzname (optional)"
            maxLength={50}
            value={v.short_name}
            error={e.short_name}
            hint="Für Navigation, Listen und Auswahlfelder"
            onChange={(ev) => form.set('short_name', ev.target.value)}
          />
          <Field
            label="Gründungsjahr"
            type="number"
            required
            value={v.founding_year}
            error={e.founding_year}
            onChange={(ev) => form.set('founding_year', ev.target.value)}
          />
        </div>
        <h3>Bezeichnung</h3>
        <LabelFields
          value={{
            label: v.label,
            plural: v.label_plural,
            gender: v.label_gender,
            genitive: v.label_genitive,
          }}
          errors={{
            label: e.label,
            plural: e.label_plural,
            gender: e.label_gender,
            genitive: e.label_genitive,
          }}
          onChange={(l) => {
            form.set('label', l.label)
            form.set('label_plural', l.plural)
            form.set('label_gender', l.gender)
            form.set('label_genitive', l.genitive)
          }}
        />
        <Field
          label="Straße und Hausnummer"
          required
          value={v.street}
          error={e.street}
          onChange={(ev) => form.set('street', ev.target.value)}
        />
        <div className="grid-3">
          <Field
            label="PLZ"
            required
            value={v.postal_code}
            error={e.postal_code}
            onChange={(ev) => form.set('postal_code', ev.target.value)}
          />
          <Field
            label="Ort"
            required
            value={v.city}
            error={e.city}
            onChange={(ev) => form.set('city', ev.target.value)}
          />
          <Field
            label="Land"
            value={v.country}
            error={e.country}
            onChange={(ev) => form.set('country', ev.target.value)}
          />
        </div>
        <div className="grid-3">
          <Field
            label="E-Mail"
            type="email"
            value={v.contact_email}
            error={e.contact_email}
            onChange={(ev) => form.set('contact_email', ev.target.value)}
          />
          <Field
            label="Telefon"
            value={v.contact_phone}
            error={e.contact_phone}
            onChange={(ev) => form.set('contact_phone', ev.target.value)}
          />
          <Field
            label="Website"
            type="url"
            value={v.website}
            error={e.website}
            onChange={(ev) => form.set('website', ev.target.value)}
          />
        </div>

        {groupsUnits && (
          <>
            <h3>Freigaben für {t.diese}</h3>
            <SelectField
              label="Zugriff auf Mitgliedsdaten der Untereinheiten"
              value={v.federation_member_access}
              error={e.federation_member_access}
              onChange={(ev) =>
                form.set(
                  'federation_member_access',
                  ev.target.value as PlatformOrg['federation_member_access'],
                )
              }
            >
              {Object.entries(ACCESS_LABELS).map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </SelectField>
            <Checkbox
              label="Frühere Mitgliedschaften (Einheit, Eintritt, Austritt) für die Untereinheiten sichtbar"
              checked={v.federation_show_former_memberships}
              onChange={(val) => form.set('federation_show_former_memberships', val)}
            />
          </>
        )}

        <h3>Module</h3>
        {MODULES.map((m) => (
          <Checkbox
            key={m.id}
            label={m.label}
            checked={v.enabled_modules.includes(m.id)}
            onChange={(on) =>
              form.set(
                'enabled_modules',
                on ? [...v.enabled_modules, m.id] : v.enabled_modules.filter((x) => x !== m.id),
              )
            }
          />
        ))}
        {org && (
          <Checkbox
            label={`${t.Sg} ist aktiv`}
            checked={v.is_active}
            onChange={(val) => form.set('is_active', val)}
          />
        )}

        {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
        <div className="button-row">
          <button type="submit" className="button button-primary" disabled={form.busy}>
            Speichern
          </button>
          <button type="button" className="button button-ghost" onClick={onCancel}>
            Zurück
          </button>
        </div>
      </form>

      {org && (
        <form className="card card-wide" onSubmit={addBoard}>
          <h2>Vorstand festlegen</h2>
          <p className="muted small">
            Die Person bekommt die Rolle „Vorstand“ mit allen Rechten in {t.diesem} und kann danach
            selbst Rollen und Benutzer verwalten.
          </p>
          <Field
            label="E-Mail-Adresse"
            type="email"
            required
            value={board}
            onChange={(ev) => setBoard(ev.target.value)}
          />
          {boardResult && <Alert kind="info">{boardResult}</Alert>}
          <button type="submit" className="button button-primary">
            Zuordnen
          </button>
        </form>
      )}
    </div>
  )
}

export function PlatformSettingsPage() {
  const { data, error, setData } = useLoad(() => platformApi.settings(), [])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>
  return <SettingsForm settings={data} onSaved={setData} />
}

function SettingsForm({
  settings,
  onSaved,
}: {
  settings: PlatformSettings
  onSaved: (s: PlatformSettings) => void
}) {
  const form = useForm(settings)
  async function save(e: FormEvent) {
    e.preventDefault()
    const saved = await form.submit(() => platformApi.updateSettings(form.values))
    if (saved) onSaved(saved as PlatformSettings)
  }
  return (
    <form className="card card-wide" onSubmit={save}>
      <h2>Einstellungen der Plattform</h2>
      <SelectField
        label="Personendaten bei Mitgliedschaft in mehreren Einheiten"
        value={form.values.person_data_mode}
        error={form.errors.person_data_mode}
        onChange={(e) =>
          form.set('person_data_mode', e.target.value as PlatformSettings['person_data_mode'])
        }
      >
        <option value="shared">gemeinsam gepflegt (eine Änderung gilt für alle Einheiten)</option>
        <option value="per_club">eigene Kopie je Einheit</option>
      </SelectField>
      <Why k="person_data_mode" />
      <Field
        label="Löschfrist nach Austritt (Monate)"
        type="number"
        min={1}
        max={600}
        value={form.values.deletion_period_months}
        error={form.errors.deletion_period_months}
        hint="Danach bleibt nur ein Minimum: Name, Geburtsdatum, Verbandsnummer und Zeiträume."
        onChange={(e) => form.set('deletion_period_months', Number(e.target.value))}
      />
      <Why k="deletion_period" />
      <h3>Verbund mit anderen HUBIplan-Instanzen</h3>
      <Checkbox
        label="Einheiten dürfen sich mit Einheiten auf anderen Instanzen koppeln"
        checked={form.values.peering_enabled}
        onChange={(v) => form.set('peering_enabled', v)}
        hint="Aus: alles bleibt wie bisher auf dieser Instanz."
      />
      {form.values.peering_enabled && (
        <>
          <label className="field">
            <span>Erlaubte Instanzen (eine Domain je Zeile, leer = alle)</span>
            <textarea
              rows={3}
              value={form.values.peering_allowed_hosts}
              onChange={(e) => form.set('peering_allowed_hosts', e.target.value)}
            />
          </label>
          {!form.values.peering_allowed_hosts.trim() && (
            <Alert kind="info">
              Die Liste ist leer: Jede HUBIplan-Instanz kann sich mit einem Kopplungscode koppeln.
              Für den Echtbetrieb besser nur die Instanzen eintragen, mit denen ihr wirklich
              zusammenarbeitet.
            </Alert>
          )}
          <Checkbox
            label="Anmelden mit dem Zugang einer gekoppelten Instanz erlauben"
            checked={form.values.peering_login}
            onChange={(v) => form.set('peering_login', v)}
            hint="Nur nach eigener Verknüpfung unter Mein Konto; Rechte vergibt weiter diese Instanz. Plattformverwaltung meldet sich nie so an."
          />
          <PeeringInstanceInfo />
        </>
      )}
      <p className="muted small">
        Das Erscheinungsbild der Plattform (Standard für alle) stellst du unter Einstellungen →
        Erscheinungsbild ein.
      </p>
      {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
      <button type="submit" className="button button-primary" disabled={form.busy}>
        Speichern
      </button>
    </form>
  )
}

function PeeringInstanceInfo() {
  const { data, reload } = useLoad(() => peeringApi.platform(), [])
  if (!data) return null
  return (
    <>
      <p className="muted small">
        Diese Instanz: {data.instance.base_url} · Fingerabdruck{' '}
        <code>{data.instance.fingerprint}</code> · {data.couplings.length} Kopplung(en)
      </p>
      {(data.pending_keys ?? []).map((p) => (
        <PeerKeysConfirm key={p.id} pending={p} onChange={reload} />
      ))}
      <InstanceKeysBox keys={data.keys} onChange={reload} />
    </>
  )
}

/** Notfallwechsel einer Gegenstelle bestätigen: nur die Plattform, gilt für alle (FQ-11). */
function PeerKeysConfirm({
  pending,
  onChange,
}: {
  pending: PendingPeerKeys
  onChange: () => void
}) {
  const [fingerprint, setFingerprint] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(action: 'confirm' | 'decline') {
    setErr(null)
    setBusy(true)
    try {
      await peeringApi.peerKeys(pending.id, action, fingerprint)
      onChange()
    } catch (e) {
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="move-confirm">
      <Alert kind="error">
        {pending.base_url} meldet einen Notfallwechsel der Schlüssel: Die alten wurden dort
        vermutlich gestohlen. Bis zur Bestätigung ruht der Austausch mit dieser Instanz
        {pending.units.length > 0 && ` (betrifft: ${pending.units.join(', ')})`}.
      </Alert>
      <p>
        Neuer Fingerabdruck: <code>{pending.fingerprint}</code>. Lass ihn dir von der anderen Seite
        auf anderem Weg (Telefon) nennen und gib ihn hier ein. Wenn dort niemand von einem Notfall
        weiß: ablehnen. Die betroffenen Einheiten bekommen danach eine Mitteilung.
      </p>
      <Field
        label="Fingerabdruck von der anderen Seite"
        value={fingerprint}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => setFingerprint(e.target.value)}
      />
      {err && <Alert kind="error">{err}</Alert>}
      <div className="button-row">
        <button
          type="button"
          className="button button-primary"
          disabled={busy || !fingerprint.trim()}
          onClick={() => void run('confirm')}
        >
          Neue Schlüssel bestätigen
        </button>
        <button
          type="button"
          className="button"
          disabled={busy}
          onClick={() => void run('decline')}
        >
          Ablehnen
        </button>
      </div>
    </div>
  )
}

/** Schlüssel der Instanz wechseln: geplant oder im Notfall (Härtung H6). */
export function InstanceKeysBox({ keys, onChange }: { keys: InstanceKeys; onChange: () => void }) {
  const [mode, setMode] = useState<'planned' | 'emergency' | null>(null)
  const [word, setWord] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const needed = mode === 'emergency' ? 'NOTFALL' : 'WECHSELN'
  const unaware = keys.peers.filter((p) => !p.knows_current)

  async function rotate() {
    if (!mode) return
    setErr(null)
    setBusy(true)
    try {
      await peeringApi.rotateKeys(mode, word)
      setMode(null)
      setWord('')
      onChange()
    } catch (e) {
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="keys-box">
      <h4>Schlüssel der Instanz</h4>
      <p className="muted small">
        Zuletzt gewechselt: {formatDate(keys.rotated_at ?? keys.created)}
        {keys.next_rotation &&
          ` · nächster automatischer Wechsel: ${formatDate(keys.next_rotation)}`}
        {keys.previous_until &&
          !keys.emergency &&
          ` · alter Schlüssel gilt noch bis ${formatDate(keys.previous_until)}`}
      </p>
      {keys.emergency && keys.previous_until && (
        <Alert kind="info">
          Notfallwechsel: Die Plattformverwaltung jeder Partner-Instanz muss den neuen Fingerabdruck{' '}
          <code>{keys.fingerprint}</code> bestätigen. Teile ihn ihr auf anderem Weg (Telefon) mit.
        </Alert>
      )}
      {unaware.length > 0 && (
        <p className="muted small">
          Kennen den aktuellen Schlüssel noch nicht: {unaware.map((p) => p.base_url).join(', ')}
        </p>
      )}
      {mode ? (
        <div className="keys-confirm">
          <p>
            {mode === 'emergency'
              ? 'Notfallwechsel, wenn der Server vermutlich gehackt wurde: Der alte Schlüssel gilt sofort nicht mehr, und jeder Partner muss den neuen Fingerabdruck bestätigen. Bis dahin ruht der Austausch.'
              : 'Geplanter Wechsel: Die Partner übernehmen den neuen Schlüssel automatisch, der alte gilt noch 30 Tage.'}{' '}
            Zum Bestätigen <strong>{needed}</strong> eintippen.
          </p>
          <Field label="Bestätigung" value={word} onChange={(e) => setWord(e.target.value)} />
          {err && <Alert kind="error">{err}</Alert>}
          <div className="button-row">
            <button
              type="button"
              className={mode === 'emergency' ? 'button button-danger' : 'button button-primary'}
              disabled={busy || word.trim().toUpperCase() !== needed}
              onClick={() => void rotate()}
            >
              {mode === 'emergency' ? 'Notfallwechsel ausführen' : 'Schlüssel wechseln'}
            </button>
            <button type="button" className="button" onClick={() => setMode(null)}>
              Abbrechen
            </button>
          </div>
        </div>
      ) : (
        <div className="button-row">
          <button type="button" className="button" onClick={() => setMode('planned')}>
            Schlüssel wechseln
          </button>
          <button
            type="button"
            className="button button-danger"
            onClick={() => setMode('emergency')}
          >
            Notfallwechsel …
          </button>
        </div>
      )}
    </div>
  )
}

/** Test-Postfach: alle Mails, die die Plattform verschickt hat. */
export function PlatformMailPage() {
  return (
    <div className="card card-wide">
      <h2>Postfach</h2>
      <p className="muted small">
        Alle Mails der Plattform. Solange kein Mailserver hinterlegt ist, werden Mails nur hier
        gesammelt und nicht zugestellt.
      </p>
      <OutboxBrowser
        load={portalApi.platformOutbox}
        deps={[]}
        attachmentUrl={portalApi.platformAttachmentUrl}
        showOrg
      />
    </div>
  )
}

export function PlatformTransferPage() {
  const { data, error, reload } = useLoad(() => platformApi.orgs(), [])
  return (
    <>
      {error && (
        <LoadError
          message={`Die Einheiten zur Auswahl konnten nicht geladen werden: ${error}`}
          onRetry={() => void reload()}
        />
      )}
      <ExportSection base={{ platform: true }} organizations={data ?? []} />
      <ImportSection base={{ platform: true }} target="platform" onImported={() => void reload()} />
    </>
  )
}
