// Rundschreiben: Liste, Editor mit Empfängerauswahl, Versand und Versandprotokoll.
// Dieselben Seiten dienen dem Vorstand (Mitglieder › Rundschreiben) und den
// Abteilungsrollen (Abteilung › Rundschreiben); nur die API-Adresse unterscheidet sich.
import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client.ts'
import { channelLabel, circularApi, emptySelections } from '../../api/circulars.ts'
import type {
  Circular,
  CircularBase,
  CircularFilters,
  CircularOptions,
  CircularSummary,
} from '../../api/circulars.ts'
import { alertDialog, confirmDialog, promptDialog } from '../dialog.ts'
import { errorMessage, formatDateTime, useAutoSave, useForm, useLoad } from '../forms.ts'
import { Alert, Field, SaveStatus, SelectField, LoadError } from '../ui.tsx'
import { MarkupEditor, MarkupPreview } from './MarkupEditor.tsx'
import { DeliveryField } from './DeliveryField.tsx'
import { RecipientPanel } from './RecipientPanel.tsx'
import { useOptionalOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'

export function CircularsArea({ base, root }: { base: CircularBase; root: string }) {
  return (
    <Routes>
      <Route index element={<CircularList base={base} root={root} />} />
      <Route path=":id" element={<CircularPage base={base} root={root} />} />
    </Routes>
  )
}

function CircularList({ base, root }: { base: CircularBase; root: string }) {
  const navigate = useNavigate()
  const list = useLoad(() => circularApi.list(base), [JSON.stringify(base)])
  const templates = useLoad(() => circularApi.templates(base), [JSON.stringify(base)])
  const [error, setError] = useState<string | null>(null)
  const [template, setTemplate] = useState('')

  async function create() {
    setError(null)
    try {
      const c = await circularApi.create(base, template ? { template: Number(template) } : {})
      navigate(`${root}/${c.id}`)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function removeTemplate(id: number, name: string) {
    if (!(await confirmDialog({ message: `Vorlage „${name}“ löschen?`, confirmLabel: 'Löschen' })))
      return
    try {
      await circularApi.removeTemplate(base, id)
      await templates.reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const drafts = (list.data ?? []).filter((c) => c.status === 'draft')
  const sent = (list.data ?? []).filter((c) => c.status !== 'draft')
  return (
    <div className="stack">
      <div className="card card-wide">
        <div className="card-head">
          <h2>Neues Rundschreiben</h2>
        </div>
        <p className="muted small">
          Mitglieder mit E-Mail-Adresse bekommen eine Mail, alle anderen einen Brief zum Drucken.
        </p>
        <div className="inline-add">
          {templates.data && templates.data.length > 0 && (
            <select
              aria-label="Vorlage"
              value={template}
              onChange={(e) => setTemplate(e.target.value)}
            >
              <option value="">ohne Vorlage</option>
              {templates.data.map((tmx) => (
                <option key={tmx.id} value={tmx.id}>
                  Vorlage: {tmx.name}
                </option>
              ))}
            </select>
          )}
          <button type="button" className="button button-primary" onClick={() => void create()}>
            Rundschreiben verfassen
          </button>
        </div>
        {error && <Alert kind="error">{error}</Alert>}
      </div>

      {list.error && <Alert kind="error">{list.error}</Alert>}
      {drafts.length > 0 && (
        <div className="card card-wide">
          <h2>Entwürfe</h2>
          <SummaryTable rows={drafts} root={root} />
        </div>
      )}
      <div className="card card-wide">
        <h2>Versendet</h2>
        {list.data && sent.length === 0 ? (
          <p className="muted">Noch keine Rundschreiben versendet.</p>
        ) : (
          <SummaryTable rows={sent} root={root} />
        )}
      </div>

      {templates.data && templates.data.length > 0 && (
        <div className="card card-wide">
          <h2>Vorlagen</h2>
          <ul className="plain-list">
            {templates.data.map((tmx) => (
              <li key={tmx.id}>
                <strong>{tmx.name}</strong>{' '}
                <span className="muted small">
                  {tmx.kind === 'notice'
                    ? 'Offizielle Mitteilung'
                    : tmx.kind === 'short'
                      ? 'Kurzmitteilung'
                      : 'Information'}
                  {tmx.subject && ` · ${tmx.subject}`}
                </span>
                <button
                  type="button"
                  className="link-button spaced"
                  onClick={() => void removeTemplate(tmx.id, tmx.name)}
                >
                  löschen
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function SummaryTable({ rows, root }: { rows: CircularSummary[]; root: string }) {
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>Betreff</th>
            <th>Art</th>
            <th className="col-optional">Absender</th>
            <th>{rows.some((r) => r.sent_at) ? 'Versendet' : 'Geändert'}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id}>
              <td>
                <Link to={`${root}/${c.id}`}>{c.subject || 'ohne Betreff'}</Link>
                {c.status === 'sending' && <span className="badge badge-open">wird versendet</span>}
              </td>
              <td>{c.kind_label}</td>
              <td className="col-optional">{c.department?.name ?? '–'}</td>
              <td className="small">
                {formatDateTime(c.sent_at ?? c.updated_at)}
                {c.sent_by && <div className="muted">{c.sent_by}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function CircularPage({ base, root }: { base: CircularBase; root: string }) {
  const id = Number(useParams().id)
  const circular = useLoad(() => circularApi.get(base, id), [JSON.stringify(base), id])
  const options = useLoad(() => circularApi.options(base), [JSON.stringify(base)])
  if (circular.error) return <LoadError message={circular.error} onRetry={circular.reload} />
  if (options.error)
    return (
      <LoadError
        message={`Die Empfängerauswahl konnte nicht geladen werden (${options.error}).`}
        onRetry={options.reload}
      />
    )
  if (!circular.data || !options.data) return <p className="muted">Wird geladen …</p>
  const back = (
    <p>
      <Link to={root}>← Alle Rundschreiben</Link>
    </p>
  )
  if (!circular.data.can_edit)
    return (
      <>
        {back}
        <SentView base={base} root={root} circular={circular.data} onReload={circular.reload} />
      </>
    )
  return (
    <>
      {back}
      <DraftEditor
        key={circular.data.id}
        base={base}
        root={root}
        initial={circular.data}
        options={options.data}
        onSent={circular.reload}
      />
    </>
  )
}

type DraftValues = {
  kind: Circular['kind']
  audience: Circular['audience']
  subject: string
  body: string
  reply_to: string
  via_app: boolean
  also_mail: boolean
  filters: CircularFilters
  mailing_list: number | null
}

function DraftEditor({
  base,
  root,
  initial,
  options,
  onSent,
}: {
  base: CircularBase
  root: string
  initial: Circular
  options: CircularOptions
  onSent: () => Promise<void>
}) {
  const navigate = useNavigate()
  const form = useForm<DraftValues>({
    kind: initial.kind,
    audience: initial.audience,
    subject: initial.subject,
    body: initial.body,
    reply_to: initial.reply_to,
    via_app: initial.via_app ?? true,
    also_mail: initial.also_mail ?? false,
    filters: initial.filters ?? {},
    mailing_list: initial.mailing_list ?? null,
  })
  const { values: v, errors, set } = form
  const [attachments, setAttachments] = useState(initial.attachments)
  const [notice, setNotice] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [preview, setPreview] = useState(false)
  // Nach jedem Speichern die Empfängerliste neu laden
  const [version, setVersion] = useState(0)
  const auto = useAutoSave(form, (changes) => circularApi.update(base, initial.id, changes), {
    onSaved: () => setVersion((n) => n + 1),
  })
  const fileInput = useRef<HTMLInputElement>(null)

  const setFilters = (patch: Partial<CircularFilters>) => set('filters', { ...v.filters, ...patch })
  const short = v.kind === 'short'
  // Gibt es Verteiler, geht ein Rundschreiben immer an einen davon (Ralf 2026-10-31)
  const lists = options.lists ?? []
  const byList = lists.length > 0
  const chosenList = lists.find((l) => l.id === v.mailing_list)
  const shortMax = options.max_short_body ?? 500

  async function act(action: () => Promise<unknown>, success?: string) {
    setNotice(null)
    try {
      if (!(await auto.flush())) {
        setNotice({
          kind: 'error',
          text: 'Die Änderungen sind noch nicht gespeichert. Erst danach geht es weiter.',
        })
        return
      }
      await action()
      if (success) setNotice({ kind: 'success', text: success })
    } catch (err) {
      if (err instanceof ApiError) form.setErrors((e) => ({ ...e, ...err.fieldErrors }))
      setNotice({ kind: 'error', text: errorMessage(err) })
    }
  }

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    await act(async () => {
      const c = await circularApi.upload(base, initial.id, file)
      setAttachments(c.attachments)
    })
  }

  async function sendNow() {
    if (byList && !v.mailing_list) {
      await alertDialog('Bitte unter „An“ einen Verteiler wählen.')
      return
    }
    if (!byList && emptySelections(v.filters).length > 0) {
      await alertDialog(
        'Bei „nur ausgewählte“ fehlt noch eine Auswahl. Bitte mindestens einen Eintrag anhaken ' +
          'oder „alle“ wählen, bevor ihr versendet.',
      )
      return
    }
    await act(async () => {
      const r = await circularApi.recipients(base, initial.id)
      const { mail, letter } = r.counts
      const app = r.counts.app ?? 0
      const portal = r.counts.portal ?? 0
      if (app + mail + letter + portal === 0) {
        await alertDialog('Für diese Auswahl gibt es keine Empfänger.')
        return
      }
      const parts = [
        app ? `${app} per App` : '',
        mail ? `${mail} ${mail === 1 ? 'E-Mail' : 'E-Mails'}` : '',
        letter ? `${letter} ${letter === 1 ? 'Brief' : 'Briefe'} zum Drucken` : '',
        portal ? `${portal} nur im Mitgliederbereich` : '',
      ].filter(Boolean)
      const ok = await confirmDialog({
        title: 'Rundschreiben versenden?',
        message: `„${v.subject}“ geht jetzt raus: ${parts.join(' und ')}. Versendete Mails lassen sich nicht zurückholen.`,
        confirmLabel: 'Jetzt versenden',
        danger: false,
      })
      if (!ok) return
      await circularApi.send(base, initial.id)
      await onSent()
    })
  }

  // Vorschau erst nach dem Speichern: sonst zeigt sie einen älteren Stand (UI-Audit NAF-01)
  async function letters() {
    setNotice(null)
    // Fenster sofort öffnen, sonst blockt der Browser es nach dem Warten
    const win = window.open('', '_blank')
    if (await auto.flush()) {
      const url = circularApi.lettersUrl(base, initial.id, true)
      if (win) win.location.href = url
      else window.location.assign(url)
    } else {
      win?.close()
      setNotice({
        kind: 'error',
        text: 'Die Vorschau wurde noch nicht erstellt. Bitte zuerst die Änderungen speichern.',
      })
    }
  }

  async function saveTemplate() {
    const name = await promptDialog({
      title: 'Als Vorlage speichern',
      label: 'Name der Vorlage',
      defaultValue: v.subject,
    })
    if (!name) return
    await act(
      () =>
        circularApi.saveTemplate(base, { name, kind: v.kind, subject: v.subject, body: v.body }),
      `Vorlage „${name}“ gespeichert.`,
    )
  }

  async function remove() {
    if (!(await confirmDialog({ message: 'Diesen Entwurf löschen?', confirmLabel: 'Löschen' })))
      return
    await act(async () => {
      await circularApi.remove(base, initial.id)
      navigate(root)
    })
  }

  return (
    <div className="stack">
      <div className="card card-wide">
        <div className="card-head">
          <h2>Rundschreiben verfassen</h2>
          <span className="push-right">
            <SaveStatus auto={auto} />
          </span>
        </div>
        <div className="grid-2">
          <SelectField
            label="Art"
            value={v.kind}
            onChange={(e) => set('kind', e.target.value as DraftValues['kind'])}
            hint={
              v.kind === 'info'
                ? 'Mitglieder können sich von Informationen abmelden.'
                : v.kind === 'short'
                  ? `Kurz und ohne Anhang (bis ${shortMax} Zeichen), z. B. „Antreten heute 18 Uhr am Zelt“. Nie als Brief.`
                  : 'Geht an alle, auch an Abgemeldete (z. B. Einladung zur Versammlung).'
            }
          >
            {options.kinds.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </SelectField>
          {byList ? (
            <SelectField
              label="An"
              value={v.mailing_list ?? ''}
              error={errors.mailing_list}
              hint={
                chosenList
                  ? 'Empfänger wie im Verteiler eingestellt.'
                  : 'Bitte einen Verteiler wählen.'
              }
              onChange={(e) => set('mailing_list', e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">Verteiler wählen …</option>
              {lists.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </SelectField>
          ) : (
            options.audiences && (
              <SelectField
                label="An"
                value={v.audience}
                error={errors.audience}
                onChange={(e) => {
                  set('audience', e.target.value as DraftValues['audience'])
                }}
              >
                {options.audiences.map((a) => (
                  <option key={a.value} value={a.value}>
                    {a.label}
                  </option>
                ))}
              </SelectField>
            )
          )}
        </div>
        <Field
          label="Betreff"
          value={v.subject}
          error={errors.subject}
          maxLength={200}
          onChange={(e) => set('subject', e.target.value)}
        />
        <div className="card-head">
          <span className="small">
            <strong>Text</strong>
          </span>
          <button
            type="button"
            className="link-button push-right"
            onClick={() => setPreview((p) => !p)}
          >
            {preview ? 'Bearbeiten' : 'Vorschau'}
          </button>
        </div>
        {preview ? (
          <MarkupPreview text={v.body} />
        ) : (
          <MarkupEditor
            value={v.body}
            onChange={(text) => set('body', text)}
            placeholders={options.placeholders}
            error={errors.body}
          />
        )}
        {short && (
          <p className={v.body.length > shortMax ? 'field-error small' : 'muted small'}>
            {v.body.length} von {shortMax} Zeichen
          </p>
        )}
        <DeliveryField
          viaApp={v.via_app}
          alsoMail={v.also_mail}
          onChange={(change) => {
            set('via_app', change.via_app)
            set('also_mail', change.also_mail)
          }}
        />
        <Field
          label="Antworten gehen an"
          type="email"
          value={v.reply_to}
          error={errors.reply_to}
          placeholder={options.reply_to}
          hint="Leer: deine E-Mail-Adresse."
          onChange={(e) => set('reply_to', e.target.value)}
        />
        {!short && <h3>Anhänge (PDF)</h3>}
        {!short && attachments.length > 0 && (
          <ul className="plain-list">
            {attachments.map((a) => (
              <li key={a.id}>
                <a href={a.url} target="_blank" rel="noreferrer">
                  {a.name}
                </a>{' '}
                <span className="muted small">{Math.max(1, Math.round(a.size / 1024))} KB</span>
                <button
                  type="button"
                  className="link-button spaced"
                  onClick={() =>
                    void act(async () => {
                      await circularApi.removeAttachment(base, initial.id, a.id)
                      setAttachments((list) => list.filter((x) => x.id !== a.id))
                    })
                  }
                >
                  entfernen
                </button>
              </li>
            ))}
          </ul>
        )}
        {!short && attachments.length < options.max_attachments && (
          <>
            <input
              ref={fileInput}
              type="file"
              accept="application/pdf"
              hidden
              aria-label="PDF anhängen"
              onChange={(e) => void upload(e)}
            />
            <button
              type="button"
              className="button button-ghost"
              onClick={() => fileInput.current?.click()}
            >
              PDF anhängen
            </button>
            <p className="muted small">
              Bis {options.max_attachment_mb} MB je Datei. In Briefen stehen Anhänge als „Anlagen“
              und werden separat gedruckt.
            </p>
          </>
        )}
      </div>

      {byList && !chosenList ? (
        <div className="card card-wide">
          <h2>Empfänger</h2>
          <p className="muted">Bitte oben unter „An“ einen Verteiler wählen.</p>
        </div>
      ) : (
        <RecipientPanel
          base={base}
          circularId={initial.id}
          options={options}
          audience={chosenList?.audience ?? v.audience}
          filters={v.filters}
          onFilters={setFilters}
          version={version}
          fixed={!!chosenList}
        />
      )}

      <div className="card card-wide">
        <div className="button-row">
          <button type="button" className="button button-primary" onClick={() => void sendNow()}>
            Versenden …
          </button>
          <button
            type="button"
            className="button button-ghost"
            onClick={() =>
              void act(async () => {
                const r = await circularApi.test(base, initial.id)
                setNotice({ kind: 'success', text: `Probemail an ${r.sent_to} geschickt.` })
              })
            }
          >
            Probemail an mich
          </button>
          <button type="button" className="button button-ghost" onClick={() => void letters()}>
            Briefvorschau (PDF)
          </button>
          <button type="button" className="button button-ghost" onClick={() => void saveTemplate()}>
            Als Vorlage speichern
          </button>
          <button
            type="button"
            className="button button-danger push-right"
            onClick={() => void remove()}
          >
            Entwurf löschen
          </button>
        </div>
        {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      </div>
    </div>
  )
}

function SentView({
  base,
  root,
  circular,
  onReload,
}: {
  base: CircularBase
  root: string
  circular: Circular
  onReload: () => Promise<void>
}) {
  const tm = useTerms()
  const activeType = useOptionalOrg()?.active?.type
  const navigate = useNavigate()
  const recipients = useLoad(
    () => circularApi.recipients(base, circular.id),
    [JSON.stringify(base), circular.id, circular.status],
  )
  const [error, setError] = useState<string | null>(null)
  const sending = circular.status === 'sending'

  // Während des Versands den Stand alle paar Sekunden neu laden
  useEffect(() => {
    if (!sending) return
    // Nie zwei Abrufe gleichzeitig (langsames Netz, Gesamtaudit 30.10. WEB-P02)
    let busy = false
    const timer = setInterval(() => {
      if (busy) return
      busy = true
      onReload()
        .catch(() => undefined)
        .finally(() => {
          busy = false
        })
    }, 4000)
    return () => clearInterval(timer)
  }, [sending, onReload])

  async function reuse() {
    try {
      const c = await circularApi.create(base, { copy_of: circular.id })
      navigate(`${root}/${c.id}`)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function resend() {
    const open = (counts?.failed ?? 0) + (counts?.unclear ?? 0)
    const question =
      (counts?.unclear ?? 0) > 0
        ? `${open} E-Mails erneut senden? Bei „Versand unklar“ ist offen, ob die Mail schon ` +
          'ankam; sie kann dann doppelt ankommen.'
        : `${open} fehlgeschlagene E-Mails erneut senden?`
    if (!(await confirmDialog({ message: question, confirmLabel: 'Erneut senden' }))) return
    try {
      await circularApi.resend(base, circular.id)
      setError(null)
      await onReload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const counts = circular.counts
  const retryable = (counts?.failed ?? 0) + (counts?.unclear ?? 0)
  return (
    <div className="stack">
      <div className="card card-wide">
        <div className="card-head">
          <h2>{circular.subject}</h2>
          <span className="badge">{circular.kind_label}</span>
          {sending && <span className="badge badge-open">wird versendet</span>}
        </div>
        <p className="muted small">
          {circular.sent_at && `Versendet am ${formatDateTime(circular.sent_at)}`}
          {circular.sent_by && ` von ${circular.sent_by}`}
          {circular.department && ` · ${circular.department.name}`}
          {circular.reply_to && ` · Antworten an ${circular.reply_to}`}
        </p>
        <MarkupPreview text={circular.body} />
        {circular.attachments.length > 0 && (
          <p>
            Anhänge:{' '}
            {circular.attachments.map((a, i) => (
              <span key={a.id}>
                {i > 0 && ', '}
                <a href={a.url} target="_blank" rel="noreferrer">
                  {a.name}
                </a>
              </span>
            ))}
          </p>
        )}
        <div className="button-row">
          {counts && counts.letter > 0 && (
            <a
              className="button button-primary"
              href={circularApi.lettersUrl(base, circular.id)}
              target="_blank"
              rel="noreferrer"
            >
              {counts.letter} {counts.letter === 1 ? 'Brief' : 'Briefe'} drucken (PDF)
            </a>
          )}
          <button type="button" className="button button-ghost" onClick={() => void reuse()}>
            Erneut verwenden
          </button>
        </div>
        {error && <Alert kind="error">{error}</Alert>}
      </div>

      <div className="card card-wide">
        <h2>Versandprotokoll</h2>
        {counts && (
          <p>
            {(counts.app ?? 0) > 0 && `${counts.app} per App · `}
            {counts.mail} E-Mails
            {counts.sent !== undefined && `: ${counts.sent} gesendet`}
            {counts.pending > 0 && ` (${counts.pending} noch offen)`}
            {counts.failed > 0 && `, ${counts.failed} fehlgeschlagen`}
            {(counts.unclear ?? 0) > 0 && `, ${counts.unclear} Versand unklar`} · {counts.letter}{' '}
            Briefe
            {(counts.portal ?? 0) > 0 && ` · ${counts.portal} nur im Mitgliederbereich`}
          </p>
        )}
        {retryable > 0 && (
          <p>
            <button type="button" className="button button-ghost" onClick={() => void resend()}>
              {retryable} {retryable === 1 ? 'E-Mail' : 'E-Mails'} erneut senden
            </button>
          </p>
        )}
        {recipients.error && <Alert kind="error">{recipients.error}</Alert>}
        {recipients.data && (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th className="col-optional">{activeType === 'federation' ? tm.Sg : tm.e_Sg}</th>
                  <th>Weg</th>
                  <th>Stand</th>
                </tr>
              </thead>
              <tbody>
                {recipients.data.items.map((r) => (
                  <tr key={r.key}>
                    <td>
                      {r.last_name}
                      {r.first_name && `, ${r.first_name}`}
                      {r.email && <div className="muted small">{r.email}</div>}
                    </td>
                    <td className="col-optional">{r.club}</td>
                    <td>{r.channel ? channelLabel[r.channel] : '–'}</td>
                    <td>
                      {r.status_label}
                      {r.error && <div className="field-error small">{r.error}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
