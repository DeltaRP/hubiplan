import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { saveBlob } from '../api/client.ts'
import { letterFileName, letterheadApi } from '../api/letterhead.ts'
import type {
  ContactKey,
  FileFormat,
  LetterNotice,
  LetterRequest,
  MyLetterheads,
  SenderContext,
} from '../api/letterhead.ts'
import { errorMessage, useLoad } from '../components/forms.ts'
import { useImageCrop } from '../components/ImageCrop.tsx'
import { Alert, Checkbox, Field, SelectField } from '../components/ui.tsx'
import { LetterPreview } from './settings/LetterheadSettingsPage.tsx'

const PRIVATE: ContactKey[] = ['own_email', 'own_phone', 'own_address']

function optionKey(ctx: string, unit: number) {
  return `${ctx}|${unit}`
}

/** Hinweise „Vorlage veraltet“ und „neue Funktion“, z. B. auf der Startseite. */
export function LetterheadNotices({
  notices,
  onDismiss,
  onPick,
}: {
  notices: LetterNotice[]
  onDismiss: (n: LetterNotice) => void
  onPick?: (n: LetterNotice) => void
}) {
  if (notices.length === 0) return null
  return (
    <>
      {notices.map((n) => (
        <Alert kind="info" key={`${n.kind}-${n.context}-${n.unit.id}`}>
          {n.kind === 'outdated' ? (
            <>
              Deine Briefvorlage für {n.unit.name} ist veraltet: {n.changes.join(', ')}{' '}
              geändert.{' '}
            </>
          ) : (
            <>
              Für deine Funktion „{n.function}“ in {n.unit.name} kannst du dir eine Briefvorlage
              erstellen.{' '}
            </>
          )}
          {onPick ? (
            <button type="button" className="link-button" onClick={() => onPick(n)}>
              {n.kind === 'outdated' ? 'Neu erstellen' : 'Jetzt erstellen'}
            </button>
          ) : (
            <Link to={`/briefvorlage?fuer=${encodeURIComponent(optionKey(n.context, n.unit.id))}`}>
              {n.kind === 'outdated' ? 'Neu erstellen' : 'Jetzt erstellen'}
            </Link>
          )}{' '}
          ·{' '}
          <button type="button" className="link-button" onClick={() => onDismiss(n)}>
            Später
          </button>
        </Alert>
      ))}
    </>
  )
}

/** Startseite: Hinweise zur Briefvorlage (nur wenn es welche gibt). */
export function HomeLetterheadNotices() {
  const { data, reload } = useLoad(() => letterheadApi.mine(), [])
  if (!data) return null
  return (
    <LetterheadNotices
      notices={data.notices}
      onDismiss={(n) => void letterheadApi.dismiss(n.unit.id, n.context).then(reload)}
    />
  )
}

function initialRequest(data: MyLetterheads, key: string | null): LetterRequest | null {
  const options = data.contexts.flatMap((c) => c.units.map((u) => ({ c, u })))
  const picked =
    options.find(({ c, u }) => optionKey(c.key, u.id) === key) ??
    options.find(({ c, u }) => data.choices.some((x) => x.unit === u.id && x.context === c.key)) ??
    options[0]
  if (!picked) return null
  return requestFor(data, picked.c, picked.u.id)
}

function requestFor(data: MyLetterheads, ctx: SenderContext, unit: number): LetterRequest {
  const choice = data.choices.find((x) => x.unit === unit && x.context === ctx.key)
  const fn = ctx.functions.find((f) => f.key === choice?.function) ?? ctx.functions[0]
  if (choice && choice.downloaded_at) {
    return {
      context: ctx.key,
      unit,
      function: fn.key,
      function_text: choice.function_text,
      title: choice.title,
      contacts: choice.contacts,
      with_logo: choice.with_logo,
      format: choice.format,
      signature: null,
    }
  }
  return {
    context: ctx.key,
    unit,
    function: fn.key,
    function_text: '',
    title: '',
    contacts: fn.contact_email ? ['unit', 'role'] : ['unit'],
    with_logo: true,
    format: 'dotx',
    signature: null,
  }
}

/** Mein Konto › Briefvorlage & Unterschrift: persönliche Word-Vorlage erzeugen. */
export function LetterheadPage() {
  const [params] = useSearchParams()
  const { data, error, reload } = useLoad(() => letterheadApi.mine(), [])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>
  return (
    <section>
      <h1>Briefvorlage erstellen</h1>
      {data.contexts.length === 0 ? (
        <div className="card card-wide">
          <p>
            Briefvorlagen erstellen Vorstandsmitglieder und Inhaber einer Rolle in einer
            Untereinheit. Du hast gerade keine solche Funktion.
          </p>
        </div>
      ) : (
        <LetterheadForm
          key={params.get('fuer') ?? ''}
          data={data}
          start={params.get('fuer')}
          reload={reload}
        />
      )}
    </section>
  )
}

function LetterheadForm({
  data,
  start,
  reload,
}: {
  data: MyLetterheads
  start: string | null
  reload: () => void
}) {
  const [req, setReq] = useState<LetterRequest>(() => initialRequest(data, start)!)
  const [preview, setPreview] = useState(0)
  // Stand der angezeigten Vorschau: jede Änderung danach macht sie sichtbar veraltet
  // (UI-Audit NAF-01)
  const [shown, setShown] = useState<LetterRequest | null>(null)
  // Dateiauswahl der Unterschrift beim Wechsel der Vorlage leeren (UI-Audit H-NAF-01)
  const [fileKey, setFileKey] = useState(0)
  const [signatureReset, setSignatureReset] = useState(false)
  const crop = useImageCrop({ title: 'Ausschnitt der Unterschrift', maxSide: 1200 })
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'info' | 'error'; text: string } | null>(null)
  const ctx = data.contexts.find((c) => c.key === req.context) ?? data.contexts[0]
  const unit = ctx.units.find((u) => u.id === req.unit) ?? ctx.units[0]
  const fn = ctx.functions.find((f) => f.key === req.function) ?? ctx.functions[0]
  const set = <K extends keyof LetterRequest>(key: K, value: LetterRequest[K]) =>
    setReq((r) => ({ ...r, [key]: value }))
  const toggle = (key: ContactKey, on: boolean) =>
    setReq((r) => ({
      ...r,
      contacts: on
        ? [...r.contacts.filter((c) => c !== key), key]
        : r.contacts.filter((c) => c !== key),
    }))
  const has = (key: ContactKey) => req.contacts.includes(key)
  const privateChosen = PRIVATE.some(has)
  const previewKey = String(preview)

  function pick(key: string) {
    const [ctxKey, unitId] = key.split('|')
    const next = data.contexts.find((c) => c.key === ctxKey)
    if (next) {
      setSignatureReset(!!req.signature)
      setReq(requestFor(data, next, Number(unitId)))
      setFileKey((n) => n + 1)
    }
    setPreview(0)
    setShown(null)
  }

  async function download() {
    setBusy(true)
    setMessage(null)
    try {
      const blob = await letterheadApi.myDownload(req)
      saveBlob(blob, letterFileName(unit.name, req.format))
      setMessage({
        kind: 'info',
        text: 'Die Vorlage ist heruntergeladen. Ändern sich später Daten der Einheit, weist HUBIplan dich darauf hin.',
      })
      reload()
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <LetterheadNotices
        notices={data.notices}
        onPick={(n) => pick(optionKey(n.context, n.unit.id))}
        onDismiss={(n) => void letterheadApi.dismiss(n.unit.id, n.context).then(reload)}
      />
      <form className="card card-wide" onSubmit={(e) => e.preventDefault()}>
        <p className="muted small">
          Briefkopf, Fußzeile, Farben und Schrift kommen aus dem Briefbogen der Einheit. Du wählst
          hier nur deine Funktion und wie man dich erreicht. Die erzeugte Datei speichert HUBIplan
          nicht.
        </p>
        <div className="grid-2">
          <SelectField
            label="Schreiben für"
            value={optionKey(req.context, req.unit)}
            onChange={(e) => pick(e.target.value)}
          >
            {data.contexts.map((c) => (
              <optgroup key={c.key} label={c.organization.name}>
                {c.units.map((u) => (
                  <option key={u.id} value={optionKey(c.key, u.id)}>
                    {u.name}
                  </option>
                ))}
              </optgroup>
            ))}
          </SelectField>
          <SelectField
            label="Deine Funktion"
            value={req.function}
            onChange={(e) => set('function', e.target.value)}
          >
            {ctx.functions.map((f) => (
              <option key={f.key} value={f.key}>
                {f.name}
              </option>
            ))}
          </SelectField>
          <Field
            label="Funktion, wie sie im Brief steht (optional)"
            value={req.function_text}
            placeholder={fn.name}
            maxLength={150}
            onChange={(e) => set('function_text', e.target.value)}
          />
          <Field
            label="Titel (optional)"
            value={req.title}
            placeholder="z. B. Dr."
            maxLength={30}
            hint={`Im Brief: ${req.title ? `${req.title} ` : ''}${ctx.name}`}
            onChange={(e) => set('title', e.target.value)}
          />
        </div>
        <fieldset>
          <legend>So erreicht man dich (im Informationsblock)</legend>
          <Checkbox
            label={`Kontakt der Einheit${
              unit.contact.phone || unit.contact.email
                ? `: ${[unit.contact.phone, unit.contact.email].filter(Boolean).join(' · ')}`
                : ' (nicht hinterlegt)'
            }`}
            checked={has('unit')}
            onChange={(on) => toggle('unit', on)}
          />
          {fn.contact_email && (
            <Checkbox
              label={`Funktionsadresse: ${fn.contact_email}`}
              checked={has('role')}
              onChange={(on) => toggle('role', on)}
            />
          )}
          <Checkbox
            label={`Meine E-Mail-Adresse: ${ctx.own.email}`}
            checked={has('own_email')}
            onChange={(on) => toggle('own_email', on)}
          />
          {ctx.own.phone && (
            <Checkbox
              label={`Meine Telefonnummer: ${ctx.own.phone}`}
              checked={has('own_phone')}
              onChange={(on) => toggle('own_phone', on)}
            />
          )}
          {ctx.own.address.length > 0 && (
            <Checkbox
              label={`Meine Anschrift als „Antwort an“: ${ctx.own.address.join(', ')}`}
              checked={has('own_address')}
              onChange={(on) => toggle('own_address', on)}
            />
          )}
          {privateChosen && (
            <p className="muted small">
              Deine privaten Angaben stehen dann in jedem Brief aus dieser Vorlage. Das entscheidest
              nur du; für andere Vorstände ändert sich nichts.
            </p>
          )}
        </fieldset>
        <div className="grid-2">
          <Checkbox
            label="mit Logo/Wappen"
            checked={req.with_logo}
            onChange={(on) => set('with_logo', on)}
          />
          <label className="field">
            <span>Unterschrift als Bild (optional, PNG oder JPEG)</span>
            <input
              key={fileKey}
              type="file"
              accept="image/png,image/jpeg"
              onChange={(e) => {
                setSignatureReset(false)
                crop.choose(e, (file) => set('signature', file))
              }}
            />
            {crop.dialog}
            {signatureReset && (
              <small className="field-error">
                Unterschrift bitte für diese Vorlage erneut auswählen.
              </small>
            )}
            <small className="muted">Wird nur in diese Datei geschrieben, nicht gespeichert.</small>
          </label>
          <SelectField
            label="Dateiformat"
            value={req.format}
            onChange={(e) => set('format', e.target.value as FileFormat)}
          >
            <option value="dotx">Word-Vorlage (.dotx): öffnet jedes Mal ein neues Dokument</option>
            <option value="docx">Word-Dokument (.docx): z. B. für Word im Browser</option>
          </SelectField>
        </div>
        <div className="button-row">
          <button
            type="button"
            className="button button-primary"
            disabled={busy}
            onClick={() => void download()}
          >
            Herunterladen
          </button>
          <button
            type="button"
            className="button"
            onClick={() => {
              setShown(req)
              setPreview((n) => n + 1)
            }}
          >
            {preview ? 'Vorschau aktualisieren' : 'Vorschau anzeigen'}
          </button>
        </div>
        {message && <Alert kind={message.kind}>{message.text}</Alert>}
        {preview > 0 && shown && (
          <>
            <p className="small" role="status">
              {shown === req
                ? 'Vorschau aktuell.'
                : 'Vorschau veraltet: Du hast seitdem etwas geändert. Bitte „Vorschau aktualisieren“.'}
            </p>
            <LetterPreview load={() => letterheadApi.myPreview(shown)} version={previewKey} />
          </>
        )}
      </form>
    </>
  )
}
