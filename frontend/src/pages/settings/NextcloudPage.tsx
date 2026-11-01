// Einstellungen › Nextcloud: Anmeldung an der Nextcloud der Einheit mit dem HUBIplan-Konto.
// HUBIplan ist dabei Anmeldedienst (OpenID Connect), die Nextcloud nutzt die App „user_oidc“.
import { useState } from 'react'
import { nextcloudApi } from '../../api/nextcloud.ts'
import type { NextcloudClient, NextcloudInput } from '../../api/nextcloud.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, useLoad } from '../../components/forms.ts'
import { Alert, Checkbox, Field, LoadError, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { formatDayTime } from '../../i18n/format.ts'
import { t } from '../../i18n/index.ts'

function Copyable({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="field">
      <span>{label}</span>
      <div className="button-row">
        <code className="break-all">{value}</code>
        <button
          type="button"
          className="button"
          onClick={() => {
            void navigator.clipboard?.writeText(value).then(() => setCopied(true))
          }}
        >
          {copied ? t('Kopiert') : t('Kopieren')}
        </button>
      </div>
    </div>
  )
}

function ClientCard({
  org,
  isClub,
  client,
  secret,
  onChanged,
  onRemoved,
}: {
  org: number
  isClub: boolean
  client: NextcloudClient
  secret: string
  onChanged: (c: NextcloudClient) => void
  onRemoved: () => void
}) {
  const [values, setValues] = useState<NextcloudInput>({
    name: client.name,
    base_url: client.base_url,
    audience: client.audience,
    require_mfa: client.require_mfa,
    groups_board: client.groups_board,
    groups_roles: client.groups_roles,
    groups_units: client.groups_units,
    groups_members: client.groups_members,
    usernames: client.usernames,
    is_active: client.is_active,
  })
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const set = <K extends keyof NextcloudInput>(key: K, value: NextcloudInput[K]) => {
    setSaved(false)
    setValues((v) => ({ ...v, [key]: value }))
  }

  async function save() {
    setError(null)
    try {
      onChanged(await nextcloudApi.update(org, client.id, values))
      setSaved(true)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function renew() {
    if (
      !(await confirmDialog({
        title: t('Neues Geheimnis erzeugen?'),
        message: t(
          'Das bisherige Geheimnis gilt sofort nicht mehr. Bis das neue in der Nextcloud eingetragen ist, kann sich dort niemand mit HUBIplan anmelden.',
        ),
      }))
    )
      return
    try {
      onChanged(await nextcloudApi.renewSecret(org, client.id))
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function remove() {
    if (
      !(await confirmDialog({
        title: t('Nextcloud-Anmeldung entfernen?'),
        message: t(
          'Danach kann sich niemand mehr mit dem HUBIplan-Konto bei dieser Nextcloud anmelden. Konten und Dateien in der Nextcloud bleiben.',
        ),
      }))
    )
      return
    try {
      await nextcloudApi.remove(org, client.id)
      onRemoved()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <section className="card card-wide">
      <h2>
        {client.name} <span className="muted small">{client.base_url}</span>
      </h2>
      {!client.is_active && (
        <Alert kind="info">{t('Ausgeschaltet: Niemand kann sich anmelden.')}</Alert>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void save()
        }}
      >
        <Field
          label={t('Name')}
          value={values.name ?? ''}
          maxLength={100}
          onChange={(e) => set('name', e.target.value)}
        />
        <Field
          label={t('Adresse der Nextcloud')}
          type="url"
          value={values.base_url ?? ''}
          onChange={(e) => set('base_url', e.target.value)}
        />
        <SelectField
          label={t('Wer darf sich anmelden?')}
          value={values.audience}
          onChange={(e) => set('audience', e.target.value as NextcloudInput['audience'])}
          hint={t(
            'Zählt nur, was bei dieser Einheit gilt: aktive Rollen, Ämter in Untereinheiten und, falls gewählt, Mitglieder mit Zugang und laufender Mitgliedschaft. Wer austritt oder seine Rolle abgibt, kommt nicht mehr hinein.',
          )}
        >
          <option value="board">{t('Vorstand und Rollen (auch Ämter in Untereinheiten)')}</option>
          <option value="roles">
            {t('Nur Rollen dieser Einheit (ohne Ämter in Untereinheiten)')}
          </option>
          {isClub && <option value="members">{t('zusätzlich Mitglieder mit Zugang')}</option>}
        </SelectField>
        <Checkbox
          label={t('Nur mit Zwei-Faktor-Anmeldung')}
          checked={Boolean(values.require_mfa)}
          onChange={(v) => set('require_mfa', v)}
          hint={t('empfohlen, wenn in der Nextcloud Vorstandsunterlagen liegen')}
        />
        <fieldset>
          <legend>{t('Gruppen in der Nextcloud')}</legend>
          <Checkbox
            label={t('„Vorstand“ für alle mit einer Vorstandsrolle')}
            checked={Boolean(values.groups_board)}
            onChange={(v) => set('groups_board', v)}
          />
          <Checkbox
            label={t('je Rolle eine Gruppe (z. B. „Kassierer“, „Zugführer (Jäger)“)')}
            checked={Boolean(values.groups_roles)}
            onChange={(v) => set('groups_roles', v)}
          />
          <Checkbox
            label={t('je Untereinheit eine Gruppe für ihre Mitglieder')}
            checked={Boolean(values.groups_units)}
            onChange={(v) => set('groups_units', v)}
          />
          <Checkbox
            label={t('„Mitglieder“ für alle mit laufender Mitgliedschaft')}
            checked={Boolean(values.groups_members)}
            onChange={(v) => set('groups_members', v)}
          />
        </fieldset>
        <label className="field">
          <span>{t('Bisherige Benutzernamen in der Nextcloud')}</span>
          <textarea
            rows={4}
            placeholder="maria.muster@example.org = mmuster"
            value={values.usernames ?? ''}
            onChange={(e) => set('usernames', e.target.value)}
          />
          <small className="muted">
            {t(
              'Für Konten, die es in der Nextcloud schon gibt: je Zeile die Anmelde-E-Mail bei HUBIplan und der bisherige Benutzername. Wer hier steht, landet bei der ersten Anmeldung in seinem vorhandenen Konto mit allen Dateien. Wer fehlt, bekommt ein neues Konto. Nur eintragen, wenn es wirklich dieselbe Person ist.',
            )}
          </small>
        </label>
        <Checkbox
          label={t('Eingeschaltet')}
          checked={Boolean(values.is_active)}
          onChange={(v) => set('is_active', v)}
        />
        {error && <Alert kind="error">{error}</Alert>}
        {saved && <Alert kind="success">{t('Gespeichert.')}</Alert>}
        <div className="button-row">
          <button type="submit" className="button button-primary">
            {t('Speichern')}
          </button>
        </div>
      </form>

      <h3>{t('In der Nextcloud eintragen')}</h3>
      <p className="muted small">
        {t(
          'In der Nextcloud als Administrator die App „OpenID Connect user backend“ (user_oidc) installieren, dann unter Verwaltung › OpenID Connect einen Anbieter mit diesen Angaben anlegen. Dort „Gruppen-Provisionierung“ einschalten und als Gruppen-Zuordnung „groups“ eintragen. Für bisherige Benutzernamen: Benutzer-ID-Zuordnung „preferred_username“, „Eindeutige Benutzer-ID verwenden“ aus und in der config.php „soft_auto_provision“ an (siehe Anleitung).',
        )}
      </p>
      <Copyable label={t('Discovery-Endpunkt')} value={client.discovery_url} />
      <Copyable label={t('Client-ID')} value={client.client_id} />
      {secret ? (
        <>
          <Alert kind="info">
            {t(
              'Das Geheimnis wird nur jetzt angezeigt. Bitte gleich in der Nextcloud eintragen; HUBIplan speichert nur eine Prüfsumme.',
            )}
          </Alert>
          <Copyable label={t('Client-Geheimnis')} value={secret} />
        </>
      ) : (
        <p className="muted small">
          {t('Client-Geheimnis: nur beim Anlegen sichtbar. Vergessen? Dann ein neues erzeugen.')}
        </p>
      )}
      <Copyable label={t('Rückleitung (zur Kontrolle)')} value={client.redirect_uri} />
      <p className="muted small">
        {client.last_used_at
          ? t('Zuletzt benutzt: {when}', { when: formatDayTime(client.last_used_at) })
          : t('Noch nicht benutzt.')}
      </p>
      <div className="button-row">
        <button type="button" className="button" onClick={() => void renew()}>
          {t('Neues Geheimnis')}
        </button>
        <button type="button" className="button button-danger" onClick={() => void remove()}>
          {t('Entfernen')}
        </button>
      </div>
    </section>
  )
}

export function NextcloudPage() {
  const active = useActiveOrg()
  const { data, error, reload, setData } = useLoad(() => nextcloudApi.list(active.id), [active.id])
  const [secrets, setSecrets] = useState<Record<number, string>>({})
  const [name, setName] = useState('Nextcloud')
  const [url, setUrl] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)

  function remember(c: NextcloudClient) {
    if (c.client_secret) setSecrets((s) => ({ ...s, [c.id]: c.client_secret ?? '' }))
  }

  async function create() {
    setCreateError(null)
    try {
      const created = await nextcloudApi.create(active.id, { name, base_url: url })
      remember(created)
      setData([...(data ?? []), created])
      setUrl('')
    } catch (e) {
      setCreateError(errorMessage(e))
    }
  }

  if (error) return <LoadError message={error} onRetry={reload} />
  if (!data) return null
  return (
    <>
      <section className="card card-wide">
        <h2>{t('Anmeldung an der Nextcloud')}</h2>
        <p>
          {t(
            'Nutzt ihr eine Nextcloud, können sich Vorstand, Rollen und auf Wunsch Mitglieder dort mit ihrem HUBIplan-Konto anmelden. Die Nextcloud bekommt Name, E-Mail-Adresse und die Gruppen; Konten legt sie bei der ersten Anmeldung selbst an. Wer bei HUBIplan keinen Zugang mehr hat, kann sich dort nicht mehr anmelden.',
          )}
        </p>
        <p className="muted small">
          {t(
            'Bereits angemeldete Sitzungen in der Nextcloud laufen weiter, bis sie ablaufen. Zum sofortigen Sperren das Konto in der Nextcloud deaktivieren.',
          )}
        </p>
      </section>
      {data.map((c) => (
        <ClientCard
          key={c.id}
          org={active.id}
          isClub={active.type === 'club'}
          client={c}
          secret={secrets[c.id] ?? ''}
          onChanged={(updated) => {
            remember(updated)
            setData(data.map((x) => (x.id === updated.id ? updated : x)))
          }}
          onRemoved={() => setData(data.filter((x) => x.id !== c.id))}
        />
      ))}
      <section className="card card-wide">
        <h2>{data.length ? t('Weitere Nextcloud eintragen') : t('Nextcloud eintragen')}</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void create()
          }}
        >
          <Field
            label={t('Name')}
            value={name}
            maxLength={100}
            onChange={(e) => setName(e.target.value)}
          />
          <Field
            label={t('Adresse der Nextcloud')}
            type="url"
            placeholder="https://cloud.example.org"
            required
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          {createError && <Alert kind="error">{createError}</Alert>}
          <div className="button-row">
            <button type="submit" className="button button-primary">
              {t('Eintragen')}
            </button>
          </div>
        </form>
      </section>
    </>
  )
}
