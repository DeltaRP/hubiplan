// Mailverteiler: Verteiler-Adressen, an die Berechtigte aus ihrem eigenen
// Mailprogramm schreiben. HUBIplan macht daraus ein Rundschreiben an die
// Empfänger des Verteilers (Auswahl wie beim Rundschreiben).
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { circularApi, mailingListApi, type CircularAudience } from '../../api/circulars.ts'
import type {
  CircularBase,
  CircularFilters,
  CircularOptions,
  InboundEntry,
  MailingList,
  MailingListMode,
  MailingListSettings,
} from '../../api/circulars.ts'
import { confirmDialog } from '../dialog.ts'
import { errorMessage, formatDateTime, useAutoSave, useForm, useLoad } from '../forms.ts'
import { Alert, Checkbox, Field, LoadError, SaveStatus, SelectField } from '../ui.tsx'
import { DeliveryField } from './DeliveryField.tsx'
import { RecipientPanel } from './RecipientPanel.tsx'
import { t } from '../../i18n/index.ts'

const MODE_HINT: Record<MailingListMode, string> = {
  confirm: t(
    'Der Absender bekommt eine Mail mit Link und versendet erst mit einem Klick. Schützt vor gefälschten Absendern und Versehen.',
  ),
  draft: t('Das Rundschreiben liegt als Entwurf unter Rundschreiben und wird dort versendet.'),
  direct: t(
    'Die Mail geht sofort an alle Empfänger, ohne Link und ohne Freigabe. Der Absender bekommt nur eine Versandmeldung.',
  ),
}

export function MailingListsArea({
  base,
  root,
  circularsRoot,
}: {
  base: CircularBase
  root: string
  circularsRoot: string
}) {
  return (
    <Routes>
      <Route index element={<ListOverview base={base} root={root} />} />
      <Route
        path=":id"
        element={<ListPage base={base} root={root} circularsRoot={circularsRoot} />}
      />
    </Routes>
  )
}

function SetupHint({ settings }: { settings: MailingListSettings }) {
  if (settings.receiving) return null
  return (
    <Alert kind="info">
      {settings.domain && !settings.domain.endsWith('.invalid')
        ? t(
            'Das Sammelpostfach für {domain} ist noch nicht eingerichtet. Bis dahin kommen keine Mails an.',
            { domain: settings.domain },
          )
        : t(
            'Auf diesem Server ist noch kein Sammelpostfach eingerichtet. Bis dahin kommen keine Mails an.',
          )}{' '}
      {settings.simulation && t('Mit „Probe-Eingang“ beim Verteiler lässt sich der Ablauf testen.')}
    </Alert>
  )
}

function ListOverview({ base, root }: { base: CircularBase; root: string }) {
  const navigate = useNavigate()
  const data = useLoad(() => mailingListApi.list(base), [JSON.stringify(base)])
  const [name, setName] = useState('')
  const [local, setLocal] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const domain = data.data?.settings.domain ?? ''

  async function create(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setErrors({})
    try {
      const ml = await mailingListApi.create(base, { name, local_part: local })
      navigate(`${root}/${ml.id}`)
    } catch (err) {
      const fields = (err as { fieldErrors?: Record<string, string> }).fieldErrors
      if (fields && Object.keys(fields).length) setErrors(fields)
      else setError(errorMessage(err))
    }
  }

  async function toggle(ml: MailingList, on: boolean) {
    setError(null)
    try {
      await mailingListApi.update(base, ml.id, { is_active: on })
      await data.reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  if (data.error) return <LoadError message={data.error} onRetry={data.reload} />
  if (!data.data) return <p className="muted">{t('Wird geladen …')}</p>
  const items = data.data.items
  return (
    <div className="stack">
      <div className="card card-wide">
        <h2>{t('Verteiler')}</h2>
        <p className="muted small">
          {t(
            'Wer Rundschreiben versenden darf, schreibt aus dem eigenen Mailprogramm an die Adresse eines Verteilers. HUBIplan macht daraus ein Rundschreiben an die Empfänger des Verteilers: mit Abmeldelink, Versandprotokoll und Brief für Mitglieder ohne E-Mail. Mails von anderen Absendern werden verworfen. Antworten gehen an den Absender, nie an alle.',
          )}
        </p>
        <SetupHint settings={data.data.settings} />
        {error && items.length > 0 && <Alert kind="error">{error}</Alert>}
        {items.length === 0 ? (
          <p className="muted">{t('Noch keine Verteiler.')}</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">{t('Aktiv')}</th>
                <th scope="col">{t('Name')}</th>
                <th scope="col">{t('Adresse')}</th>
                <th scope="col" className="num">
                  {t('Empfänger')}
                </th>
                <th scope="col">{t('Versand')}</th>
                <th scope="col">{t('Letzter Eingang')}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((ml) => (
                <tr key={ml.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={ml.is_active}
                      aria-label={t('Verteiler {name} aktiv', { name: ml.name })}
                      title={t('Ausgeschaltet werden Mails an diese Adresse verworfen.')}
                      onChange={(e) => void toggle(ml, e.target.checked)}
                    />
                  </td>
                  <td>
                    <Link to={`${root}/${ml.id}`}>{ml.name}</Link>
                    {ml.department && <span className="muted small"> · {ml.department.name}</span>}
                  </td>
                  <td>{ml.address || ml.local_part}</td>
                  <td className="num">{ml.recipients ?? '–'}</td>
                  <td>{ml.mode_label}</td>
                  <td>
                    {ml.last_inbound
                      ? t('{x} · {status_label}', {
                          x: formatDateTime(ml.last_inbound.received_at),
                          status_label: ml.last_inbound.status_label,
                        })
                      : '–'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <form className="card card-wide stack-sm" onSubmit={(e) => void create(e)}>
        <h2>{t('Neuer Verteiler')}</h2>
        <Field
          label={t('Name')}
          value={name}
          maxLength={100}
          error={errors.name}
          placeholder={t('z. B. Alle Mitglieder')}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <Field
          label={t('Adresse')}
          value={local}
          maxLength={64}
          error={errors.local_part}
          placeholder={t('z. B. alle')}
          hint={
            domain
              ? t(
                  'Teil vor dem @: {x}@{domain}. Kleinbuchstaben, Ziffern, Punkt und Bindestrich.',
                  { x: local || 'alle', domain },
                )
              : t('Teil vor dem @. Kleinbuchstaben, Ziffern, Punkt und Bindestrich.')
          }
          onChange={(e) => setLocal(e.target.value.toLowerCase())}
          required
        />
        <div className="button-row">
          <button type="submit" className="button button-primary">
            {t('Anlegen')}
          </button>
        </div>
        {error && <Alert kind="error">{error}</Alert>}
      </form>
    </div>
  )
}

function ListPage({
  base,
  root,
  circularsRoot,
}: {
  base: CircularBase
  root: string
  circularsRoot: string
}) {
  const id = Number(useParams().id)
  const ml = useLoad(() => mailingListApi.get(base, id), [JSON.stringify(base), id])
  const all = useLoad(() => mailingListApi.list(base), [JSON.stringify(base)])
  const options = useLoad(() => circularApi.options(base), [JSON.stringify(base)])
  const pattern = useLoad(
    () => (ml.data ? circularApi.get(base, ml.data.pattern_id) : Promise.resolve(null)),
    [JSON.stringify(base), ml.data?.pattern_id],
  )
  const error = ml.error ?? options.error ?? pattern.error
  if (error) return <LoadError message={error} onRetry={ml.reload} />
  if (!ml.data || !options.data || !pattern.data || !all.data)
    return <p className="muted">{t('Wird geladen …')}</p>
  return (
    <div className="stack">
      <p>
        <Link to={root}>{t('← Alle Verteiler')}</Link>
      </p>
      <SetupHint settings={all.data.settings} />
      <ListSettings key={ml.data.id} base={base} root={root} initial={ml.data} />
      <ListRecipients
        key={`r${pattern.data.id}`}
        base={base}
        patternId={pattern.data.id}
        options={options.data}
        initial={{
          kind: pattern.data.kind,
          audience: pattern.data.audience,
          via_app: pattern.data.via_app ?? true,
          also_mail: pattern.data.also_mail ?? false,
          filters: pattern.data.filters ?? {},
        }}
      />
      <Inbound
        base={base}
        ml={ml.data}
        simulation={all.data.settings.simulation}
        circularsRoot={circularsRoot}
      />
    </div>
  )
}

type SettingsValues = {
  name: string
  local_part: string
  aliases: string[]
  mode: MailingListMode
  is_active: boolean
  open_senders: boolean
  senders: number[]
}

function ListSettings({
  base,
  root,
  initial,
}: {
  base: CircularBase
  root: string
  initial: MailingList
}) {
  const navigate = useNavigate()
  const form = useForm<SettingsValues>({
    name: initial.name,
    local_part: initial.local_part,
    aliases: initial.aliases ?? [],
    mode: initial.mode,
    is_active: initial.is_active,
    open_senders: initial.open_senders ?? false,
    senders: initial.senders,
  })
  const { values: v, errors, set } = form
  const [address, setAddress] = useState(initial.address)
  const [aliasText, setAliasText] = useState((initial.aliases ?? []).join(', '))
  const [aliasAddresses, setAliasAddresses] = useState(initial.alias_addresses ?? [])
  const [someSenders, setSomeSenders] = useState(initial.senders.length > 0)
  const options = initial.sender_options ?? []
  const [error, setError] = useState<string | null>(null)
  const auto = useAutoSave(form, (changes) => mailingListApi.update(base, initial.id, changes), {
    onSaved: (result) => {
      setAddress((result as MailingList).address)
      setAliasAddresses((result as MailingList).alias_addresses ?? [])
    },
  })

  async function chooseMode(mode: MailingListMode) {
    if (mode === 'direct') {
      const ok = await confirmDialog({
        message:
          t(
            'Wirklich direkt versenden? Dann geht jede Mail eines berechtigten Absenders sofort an ',
          ) +
          t(
            'alle Empfänger, ohne Bestätigungslink. Ein Versehen lässt sich nicht zurückholen, und ',
          ) +
          t('gegen gefälschte Absender schützt nur noch die DMARC-Prüfung. Bestätigt der ') +
          t('Mailserver die Herkunft nicht (dmarc=pass), kommt trotzdem ein Bestätigungslink. ') +
          t('Am besten nur für kleine Empfängerkreise nutzen.'),
        confirmLabel: t('Direkt versenden'),
      })
      if (!ok) return
    }
    set('mode', mode)
  }

  async function openToAll() {
    const ok = await confirmDialog({
      message:
        t('Wirklich alle schreiben lassen? Dann kann jeder, auch ohne HUBIplan-Konto, an diesen ') +
        t('Verteiler schreiben, und die Mail geht ohne Bestätigung an alle Empfänger. Auch Spam ') +
        t(
          'oder Mails mit gefälschtem Absender können durchrutschen. Am besten nur für sehr kleine ',
        ) +
        t('Empfängerkreise nutzen.'),
      confirmLabel: t('Alle schreiben lassen'),
    })
    if (!ok) return
    setSomeSenders(false)
    set('senders', [])
    set('open_senders', true)
  }

  async function remove() {
    const ok = await confirmDialog({
      message: t('Verteiler „{name}“ löschen? Mails an {address} werden danach verworfen.', {
        name: initial.name,
        address,
      }),
      confirmLabel: t('Löschen'),
    })
    if (!ok) return
    try {
      await mailingListApi.remove(base, initial.id)
      navigate(root)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="card card-wide stack-sm">
      <div className="card-head">
        <h2>{v.name || t('Verteiler')}</h2>
        <SaveStatus auto={auto} />
      </div>
      {address && (
        <p>
          {t('Adresse:')} <strong>{address}</strong>
          {aliasAddresses.length > 0 && (
            <span className="muted">
              {' '}
              {t('· auch:')} {aliasAddresses.join(', ')}
            </span>
          )}
        </p>
      )}
      <Field
        label={t('Name')}
        value={v.name}
        maxLength={100}
        error={errors.name}
        onChange={(e) => set('name', e.target.value)}
      />
      <Field
        label={t('Adresse')}
        value={v.local_part}
        maxLength={64}
        error={errors.local_part}
        hint={t('Teil vor dem @. Umlaute werden umgeschrieben (ü wird ue).')}
        onChange={(e) => set('local_part', e.target.value.toLowerCase())}
      />
      <Field
        label={t('Weitere Adressen')}
        value={aliasText}
        error={errors.aliases}
        hint={t(
          'Optional, mit Komma getrennt, z. B. „schriftfuehrerin, sf“. Mails an diese Adressen landen im selben Verteiler.',
        )}
        onChange={(e) => {
          setAliasText(e.target.value)
          set(
            'aliases',
            e.target.value
              .split(',')
              .map((a) => a.trim().toLowerCase())
              .filter(Boolean),
          )
        }}
      />
      <SelectField
        label={t('Versand')}
        value={v.mode}
        error={errors.mode}
        hint={MODE_HINT[v.mode]}
        onChange={(e) => void chooseMode(e.target.value as MailingListMode)}
      >
        <option value="confirm">{t('Absender bestätigt per Link')}</option>
        <option value="draft">{t('als Entwurf in HUBIplan ablegen')}</option>
        <option value="direct">{t('direkt versenden (ohne Bestätigung)')}</option>
      </SelectField>
      <Checkbox
        label={t('Verteiler eingeschaltet')}
        checked={v.is_active}
        onChange={(on) => set('is_active', on)}
        hint={t('Ausgeschaltet werden Mails an diese Adresse verworfen.')}
      />
      <fieldset className="subcard stack-sm">
        <legend>{t('Wer darf an den Verteiler schreiben?')}</legend>
        <div className="button-row">
          <label className="checkbox">
            <input
              type="radio"
              name={`absender-${initial.id}`}
              checked={!someSenders && !v.open_senders}
              onChange={() => {
                setSomeSenders(false)
                set('senders', [])
                set('open_senders', false)
              }}
            />
            <span>{t('alle mit dem Recht „Rundschreiben versenden“')}</span>
          </label>
          <label className="checkbox">
            <input
              type="radio"
              name={`absender-${initial.id}`}
              checked={someSenders && !v.open_senders}
              onChange={() => {
                setSomeSenders(true)
                set('open_senders', false)
              }}
            />
            <span>{t('nur ausgewählte')}</span>
          </label>
          <label className="checkbox">
            <input
              type="radio"
              name={`absender-${initial.id}`}
              checked={v.open_senders}
              onChange={() => void openToAll()}
            />
            <span>{t('alle, auch ohne HUBIplan-Konto')}</span>
          </label>
        </div>
        {v.open_senders && (
          <Alert kind="info">
            {t(
              'Jeder kann an diesen Verteiler schreiben, die Mail geht ohne Bestätigung an alle Empfänger. Automatische Mails, gefälschte Absender und vom Spamfilter markierte Mails werden verworfen; je fremdem Absender höchstens drei Mails am Tag.',
            )}
          </Alert>
        )}
        {someSenders && !v.open_senders && options.length === 0 && (
          <p className="muted small">
            {t('Niemand hat zurzeit das Recht „Rundschreiben versenden“.')}
          </p>
        )}
        {someSenders && !v.open_senders && options.length > 0 && v.senders.length === 0 && (
          <Alert kind="info">
            {t('Noch niemand angehakt: Bis dahin dürfen alle mit dem Recht schreiben.')}
          </Alert>
        )}
        {someSenders &&
          !v.open_senders &&
          options.map((o) => (
            <Checkbox
              key={o.id}
              label={t('{name} ({email})', { name: o.name, email: o.email })}
              checked={v.senders.includes(o.id)}
              onChange={(on) =>
                set(
                  'senders',
                  on
                    ? [...v.senders, o.id].sort((a, b) => a - b)
                    : v.senders.filter((id) => id !== o.id),
                )
              }
            />
          ))}
        {errors.senders && <p className="field-error small">{errors.senders}</p>}
        <p className="muted small">
          {t('Zur Auswahl stehen alle mit dem Recht')}
          {initial.department
            ? t(' im Verein oder in {name}', { name: initial.department.name })
            : ''}
          . Geschrieben wird von der E-Mail-Adresse des HUBIplan-Kontos; der Bestätigungslink geht
          immer an diese Adresse.
        </p>
      </fieldset>
      <div className="button-row">
        <button
          type="button"
          className="button button-danger push-right"
          onClick={() => void remove()}
        >
          {t('Verteiler löschen')}
        </button>
      </div>
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}

type RecipientValues = {
  kind: 'info' | 'notice' | 'short'
  audience: CircularAudience
  via_app: boolean
  also_mail: boolean
  filters: CircularFilters
}

function ListRecipients({
  base,
  patternId,
  options,
  initial,
}: {
  base: CircularBase
  patternId: number
  options: CircularOptions
  initial: RecipientValues
}) {
  const form = useForm<RecipientValues>(initial)
  const { values: v, errors, set } = form
  const [version, setVersion] = useState(0)
  const auto = useAutoSave(form, (changes) => circularApi.update(base, patternId, changes), {
    onSaved: () => setVersion((n) => n + 1),
  })
  const kinds = options.kinds.filter((k) => k.value !== 'short')
  return (
    <>
      <div className="card card-wide stack-sm">
        <div className="card-head">
          <h2>{t('Versand')}</h2>
          <SaveStatus auto={auto} />
        </div>
        <div className="form-row">
          <SelectField
            label={t('Art')}
            value={v.kind}
            error={errors.kind}
            hint={
              v.kind === 'info'
                ? t('Mitglieder können sich von Informationen abmelden.')
                : t('Geht an alle, auch an Abgemeldete (z. B. Einladung zur Versammlung).')
            }
            onChange={(e) => set('kind', e.target.value as RecipientValues['kind'])}
          >
            {kinds.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </SelectField>
          {options.audiences && (
            <SelectField
              label="An"
              value={v.audience}
              error={errors.audience}
              onChange={(e) => set('audience', e.target.value as RecipientValues['audience'])}
            >
              {options.audiences.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </SelectField>
          )}
        </div>
        <DeliveryField
          viaApp={v.via_app}
          alsoMail={v.also_mail}
          onChange={(change) => {
            set('via_app', change.via_app)
            set('also_mail', change.also_mail)
          }}
        />
        <p className="muted small">
          {t('Die Auswahl gilt bei jedem Eingang neu: Neue Mitglieder sind automatisch dabei.')}
        </p>
      </div>
      <RecipientPanel
        base={base}
        circularId={patternId}
        options={options}
        audience={v.audience}
        filters={v.filters}
        onFilters={(patch) => set('filters', { ...v.filters, ...patch })}
        version={version}
      />
    </>
  )
}

function Inbound({
  base,
  ml,
  simulation,
  circularsRoot,
}: {
  base: CircularBase
  ml: MailingList
  simulation: boolean
  circularsRoot: string
}) {
  const rows = useLoad(() => mailingListApi.inbound(base, ml.id), [JSON.stringify(base), ml.id])
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [notice, setNotice] = useState<{
    kind: 'error' | 'success'
    text: string
    url?: string
  } | null>(null)

  async function probe(e: FormEvent) {
    e.preventDefault()
    setNotice(null)
    try {
      const entry = await mailingListApi.probe(base, ml.id, { subject, body })
      setNotice({
        kind: entry.status === 'rejected' ? 'error' : 'success',
        text:
          entry.status === 'rejected'
            ? t('Abgewiesen: {reason}', { reason: entry.reason })
            : entry.status === 'waiting'
              ? t('Eingegangen. Die Bestätigungsmail an dich liegt im Postausgang; hier direkt:')
              : t('Eingegangen und als Entwurf abgelegt.'),
        url: entry.confirm_url,
      })
      await rows.reload()
    } catch (err) {
      setNotice({ kind: 'error', text: errorMessage(err) })
    }
  }

  return (
    <div className="card card-wide stack-sm">
      <h2>{t('Eingänge')}</h2>
      {rows.error && <LoadError message={rows.error} onRetry={rows.reload} />}
      {rows.data && rows.data.length === 0 && (
        <p className="muted">{t('Noch keine Mails eingegangen.')}</p>
      )}
      {rows.data && rows.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th scope="col">{t('Eingang')}</th>
              <th scope="col">{t('Absender')}</th>
              <th scope="col">{t('Betreff')}</th>
              <th scope="col">{t('Stand')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.data.map((r: InboundEntry) => (
              <tr key={r.id}>
                <td>{formatDateTime(r.received_at)}</td>
                <td>{r.sender}</td>
                <td>
                  {r.circular_id ? (
                    <Link to={`${circularsRoot}/${r.circular_id}`}>
                      {r.subject || '(ohne Betreff)'}
                    </Link>
                  ) : (
                    r.subject || '(ohne Betreff)'
                  )}
                </td>
                <td>
                  {r.status_label}
                  {r.reason && <span className="muted small"> · {r.reason}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {simulation && (
        <form className="subcard stack-sm" onSubmit={(e) => void probe(e)}>
          <h3>{t('Probe-Eingang')}</h3>
          <p className="muted small">
            {t('Ohne Sammelpostfach: so, als käme eine Mail von deiner Adresse an {address}.', {
              address: ml.address,
            })}
          </p>
          <Field
            label={t('Betreff')}
            value={subject}
            maxLength={200}
            onChange={(e) => setSubject(e.target.value)}
          />
          <label className="field">
            <span>{t('Text')}</span>
            <textarea rows={5} value={body} onChange={(e) => setBody(e.target.value)} />
          </label>
          <div className="button-row">
            <button type="submit" className="button button-ghost">
              {t('Probe-Eingang')}
            </button>
          </div>
          {notice && (
            <Alert kind={notice.kind}>
              {notice.text}{' '}
              {notice.url && (
                <a href={notice.url} target="_blank" rel="noreferrer">
                  {t('Bestätigungsseite öffnen')}
                </a>
              )}
            </Alert>
          )}
        </form>
      )}
    </div>
  )
}
