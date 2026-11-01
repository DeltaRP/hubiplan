// Wettbewerbe Schritt 6: Urkundenvorlagen verwalten, Urkunden für Platzierte drucken.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { certificatesApi, type CertificateTemplate, type Signer } from '../../api/certificates.ts'
import type { CompetitionDetail } from '../../api/competitions.ts'
import { PERM } from '../../api/orgs.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, useLoad } from '../../components/forms.ts'
import { Alert, Checkbox, Field, LoadError, SelectField } from '../../components/ui.tsx'
import { t } from '../../i18n/index.ts'
import { useActiveOrg } from '../../org/OrgContext.tsx'

/** Platzhalter im Text der Urkunde */
const placeholders = (): [string, string][] => [
  ['name', t('Name des Schützen, der Untereinheit oder Mannschaft')],
  ['einheit', t('Untereinheit (bei Einzelwertung)')],
  ['platz', t('Platz (Zahl)')],
  ['wertung', t('Name der Wertung')],
  ['wert', t('Ergebnis, z. B. 28')],
  ['mit_wert', t('„ mit 28“ (leer ohne Ergebnis)')],
  ['wettbewerb', t('Titel des Wettbewerbs')],
  ['datum', t('Datum des Wettbewerbs')],
  ['jahr', t('Jahr')],
  ['ort', t('Ort des Wettbewerbs')],
  ['verein', t('Name des Vereins')],
  ['titel', t('vergebener Titel, z. B. „Vereinsmeister 2027“')],
  ['preis', t('Preis bzw. Pfand (Vogelschießen)')],
]

export function CertificateTemplatesPage() {
  const org = useActiveOrg()
  const canManage = org.permissions.includes(PERM.competitionsManage)
  const { data, error, reload } = useLoad(() => certificatesApi.list(org.id), [org.id])
  const [name, setName] = useState('')
  const [message, setMessage] = useState<string | null>(null)

  async function add(e: FormEvent) {
    e.preventDefault()
    setMessage(null)
    try {
      await certificatesApi.create(org.id, { name })
      setName('')
      reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  return (
    <section>
      <h1>{t('Urkundenvorlagen')}</h1>
      <p className="muted">
        {t(
          'Eine Vorlage legt Text, Hintergrund, Wappen und Unterschriften der Urkunden fest. Gedruckt wird beim Wettbewerb unter „Auswertung“ › Urkunden, für alle Platzierten auf einmal.',
        )}
      </p>
      {error && <LoadError message={error} onRetry={reload} />}
      {message && <Alert kind="error">{message}</Alert>}
      {data?.map((tpl) => (
        <TemplateCard
          key={tpl.id}
          org={org.id}
          tpl={tpl}
          canManage={canManage}
          onChanged={reload}
        />
      ))}
      {data && data.length === 0 && <p>{t('Noch keine Vorlage.')}</p>}
      {canManage && (
        <form className="card card-wide" onSubmit={(e) => void add(e)}>
          <h2>{t('Neue Vorlage')}</h2>
          <div className="grid-3">
            <Field
              label={t('Name')}
              value={name}
              required
              placeholder={t('z. B. Vereinsmeisterschaft')}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <button type="submit" className="button">
            {t('Anlegen')}
          </button>
        </form>
      )}
      <details className="card card-wide">
        <summary>{t('Platzhalter im Text')}</summary>
        <ul>
          {placeholders().map(([key, label]) => (
            <li key={key}>
              <code>{`{${key}}`}</code> {label}
            </li>
          ))}
        </ul>
        <p className="muted small">
          {t(
            'Eine Zeile mit „# “ am Anfang wird groß und fett gedruckt. Eine Zeile, deren Platzhalter alle leer sind, fällt weg.',
          )}
        </p>
      </details>
    </section>
  )
}

function TemplateCard({
  org,
  tpl,
  canManage,
  onChanged,
}: {
  org: number
  tpl: CertificateTemplate
  canManage: boolean
  onChanged: () => void
}) {
  const [message, setMessage] = useState<string | null>(null)
  const [text, setText] = useState(tpl.text)

  async function update(changes: Partial<CertificateTemplate>) {
    setMessage(null)
    try {
      await certificatesApi.update(org, tpl.id, changes)
      onChanged()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  async function upload(file: File | undefined) {
    if (!file) return
    setMessage(null)
    try {
      await certificatesApi.uploadBackground(org, tpl.id, file)
      onChanged()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  async function remove() {
    const ok = await confirmDialog({
      title: t('Vorlage löschen'),
      message: t('„{name}“ löschen?', { name: tpl.name }),
      confirmLabel: t('Löschen'),
    })
    if (!ok) return
    await certificatesApi.remove(org, tpl.id)
    onChanged()
  }

  function setSigner(i: number, changes: Partial<Signer>) {
    const list = [...tpl.signers]
    while (list.length <= i) list.push({ name: '', function: '' })
    list[i] = { ...list[i], ...changes }
    void update({ signers: list })
  }

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>{tpl.name}</h2>
        <a
          className="button button-ghost push-right"
          href={certificatesApi.previewUrl(org, tpl.id)}
          target="_blank"
          rel="noreferrer"
        >
          {t('Probeurkunde (PDF)')}
        </a>
        {canManage && (
          <button type="button" className="button button-ghost" onClick={() => void remove()}>
            {t('Löschen')}
          </button>
        )}
      </div>
      {message && <Alert kind="error">{message}</Alert>}
      {canManage && (
        <>
          <div className="grid-3">
            <Field
              label={t('Überschrift')}
              defaultValue={tpl.heading}
              onBlur={(e) =>
                e.target.value !== tpl.heading && void update({ heading: e.target.value })
              }
            />
            <Field
              label={t('Ort für „Ort, Datum“')}
              defaultValue={tpl.place_line}
              hint={t('leer: Ort des Wettbewerbs')}
              onBlur={(e) =>
                e.target.value !== tpl.place_line && void update({ place_line: e.target.value })
              }
            />
            <div>
              <Checkbox
                label={t('Querformat')}
                checked={tpl.landscape}
                onChange={(on) => void update({ landscape: on })}
              />
              <Checkbox
                label={t('Wappen zeigen')}
                checked={tpl.show_logo}
                onChange={(on) => void update({ show_logo: on })}
              />
            </div>
          </div>
          <label className="field">
            <span>{t('Text')}</span>
            <textarea
              rows={9}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onBlur={() => text !== tpl.text && void update({ text })}
            />
          </label>
          <h3>{t('Unterschriften')}</h3>
          {[0, 1].map((i) => (
            <div className="grid-3" key={i}>
              <Field
                label={t('Name ({n}. Unterschrift)', { n: i + 1 })}
                defaultValue={tpl.signers[i]?.name ?? ''}
                onBlur={(e) =>
                  e.target.value !== (tpl.signers[i]?.name ?? '') &&
                  setSigner(i, { name: e.target.value })
                }
              />
              <Field
                label={t('Aufgabe')}
                placeholder={t('z. B. 1. Vorsitzender')}
                defaultValue={tpl.signers[i]?.function ?? ''}
                onBlur={(e) =>
                  e.target.value !== (tpl.signers[i]?.function ?? '') &&
                  setSigner(i, { function: e.target.value })
                }
              />
            </div>
          ))}
          <h3>{t('Hintergrundbild')}</h3>
          <p className="muted small">
            {t(
              'Ein Bild über die ganze Seite, z. B. ein Rahmen (PNG oder JPG, höchstens 10 MB). Ohne Bild bleibt die Seite weiß.',
            )}
          </p>
          <div className="button-row">
            <label className="button button-ghost">
              {tpl.has_background ? t('Anderes Bild wählen') : t('Bild wählen')}
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                hidden
                onChange={(e) => void upload(e.target.files?.[0])}
              />
            </label>
            {tpl.has_background && (
              <button
                type="button"
                className="button button-ghost"
                onClick={() =>
                  void certificatesApi
                    .removeBackground(org, tpl.id)
                    .then(onChanged)
                    .catch((err) => setMessage(errorMessage(err)))
                }
              >
                {t('Bild entfernen')}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}

/** Auswertung: Urkunden für alle Platzierten als PDF. */
export function CertificatesCard({ org, comp }: { org: number; comp: CompetitionDetail }) {
  const templates = useLoad(() => certificatesApi.list(org), [org])
  const [template, setTemplate] = useState<number | null>(comp.certificate_template ?? null)
  const [upTo, setUpTo] = useState(3)
  const [scoring, setScoring] = useState<number | null>(null)
  const [signature, setSignature] = useState(false)
  const bird = comp.form === 'vogel'
  const url = certificatesApi.certificatesUrl(org, comp.id, {
    template,
    upTo,
    scoring,
    signature,
  })
  return (
    <div className="card card-wide">
      <h2>{t('Urkunden')}</h2>
      <p className="muted small">
        {bird
          ? t('Eine Urkunde für jeden, der ein Pfand errungen hat.')
          : t('Eine Urkunde je Platzierten, Titel aus den Auszeichnungen inklusive.')}
      </p>
      <div className="grid-3">
        <SelectField
          label={t('Vorlage')}
          value={template ?? ''}
          onChange={(e) => setTemplate(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">{t('Standard')}</option>
          {templates.data?.map((tpl) => (
            <option key={tpl.id} value={tpl.id}>
              {tpl.name}
            </option>
          ))}
        </SelectField>
        {!bird && (
          <>
            <Field
              label={t('bis Platz')}
              type="number"
              min={1}
              max={100}
              value={upTo}
              onChange={(e) => setUpTo(Math.max(1, Number(e.target.value) || 1))}
            />
            <SelectField
              label={t('Wertung')}
              value={scoring ?? ''}
              onChange={(e) => setScoring(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">{t('alle Wertungen')}</option>
              {comp.scorings.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </SelectField>
          </>
        )}
      </div>
      <Checkbox
        label={t('Mit meiner hinterlegten Unterschrift')}
        hint={t('über der ersten Unterschriftszeile; hinterlegen unter Mein Konto › Unterschrift')}
        checked={signature}
        onChange={setSignature}
      />
      <div className="button-row">
        <a className="button" href={url} target="_blank" rel="noreferrer">
          {t('Urkunden erzeugen (PDF)')}
        </a>
      </div>
    </div>
  )
}

/** Einrichten: Urkundenvorlage des Wettbewerbs (vorgewählt beim Drucken). */
export function TemplateSelect({
  org,
  value,
  disabled,
  onChange,
}: {
  org: number
  value: number | null
  disabled?: boolean
  onChange: (id: number | null) => void
}) {
  const { data } = useLoad(() => certificatesApi.list(org), [org])
  return (
    <SelectField
      label={t('Urkundenvorlage')}
      value={value ?? ''}
      disabled={disabled}
      hint={t('Vorlagen unter Wettbewerbe › Urkundenvorlagen')}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
    >
      <option value="">{t('Standard')}</option>
      {(data ?? []).map((tpl) => (
        <option key={tpl.id} value={tpl.id}>
          {tpl.name}
        </option>
      ))}
    </SelectField>
  )
}
