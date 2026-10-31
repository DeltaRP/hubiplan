import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { saveBlob } from '../../api/client.ts'
import { docApi, docBase } from '../../api/documents.ts'
import type { DocFolder } from '../../api/documents.ts'
import { FONTS, letterFileName, letterheadApi } from '../../api/letterhead.ts'
import type { FileFormat, LetterheadFields, LetterheadState } from '../../api/letterhead.ts'
import { orgApi, PERM, unitName } from '../../api/orgs.ts'
import type { Department } from '../../api/orgs.ts'
import { errorMessage, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { flushAllForms } from '../../components/leaveGuard.ts'
import { Alert, Checkbox, Field, LoadError, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg, useOrg } from '../../org/OrgContext.tsx'

const FIELDS: (keyof LetterheadFields)[] = [
  'mode',
  'form',
  'logo_position',
  'tagline',
  'font',
  'salutation',
  'closing',
  'show_bank',
  'account',
  'show_email',
  'show_phone',
  'show_website',
  'show_board',
  'show_register',
  'show_social',
]

function pick(state: LetterheadState): LetterheadFields {
  return Object.fromEntries(
    FIELDS.map((k) => [k, state.letterhead[k]]),
  ) as unknown as LetterheadFields
}

/** Vorschau der ersten Seite als PDF; lädt neu, wenn sich ``version`` ändert. */
export function LetterPreview({ load, version }: { load: () => Promise<Blob>; version: string }) {
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const loader = useRef(load)
  useEffect(() => {
    loader.current = load
  })
  useEffect(() => {
    let current: string | null = null
    let cancelled = false
    loader
      .current()
      .then((blob) => {
        if (cancelled) return
        current = URL.createObjectURL(blob)
        setUrl(current)
        setError(null)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(errorMessage(err))
      })
    return () => {
      cancelled = true
      if (current) URL.revokeObjectURL(current)
    }
  }, [version])
  if (error) return <Alert kind="error">Vorschau nicht verfügbar: {error}</Alert>
  if (!url) return <p className="muted">Vorschau lädt …</p>
  return (
    <>
      {/* view=Fit (Chrome/Edge) bzw. zoom=page-fit (Firefox): ganze Seite einpassen, kein Querscrollen */}
      <iframe
        className="letter-preview"
        src={`${url}#view=Fit&zoom=page-fit`}
        title="Vorschau der ersten Seite"
      />
      <p className="small">
        <a href={url} target="_blank" rel="noreferrer">
          Vorschau in neuem Fenster öffnen
        </a>
      </p>
    </>
  )
}

function LetterheadEditor({
  state,
  editable,
  save,
  preview,
}: {
  state: LetterheadState
  editable: boolean
  save: (changes: Partial<LetterheadFields>) => Promise<LetterheadState>
  preview: () => Promise<Blob>
}) {
  const [current, setCurrent] = useState(state)
  const form = useForm(pick(state))
  const { values: v, set, errors } = form
  const auto = useAutoSave(form, (changes) => save(changes), {
    enabled: editable,
    onSaved: (saved) => setCurrent(saved as LetterheadState),
  })
  const isUnit = state.organization.type === 'unit'
  const inherits = isUnit && (!current.may_have_own || v.mode === 'inherit')

  return (
    <form className="card card-wide" onSubmit={(e) => e.preventDefault()}>
      {editable && <SaveStatus auto={auto} />}
      <h2>Briefbogen {state.organization.name}</h2>
      <p className="muted small">
        Vorstandsmitglieder erzeugen daraus unter{' '}
        <Link to="/briefvorlage">Briefvorlage erstellen</Link> ihre eigene Word-Vorlage mit Funktion
        und Kontaktweg. Gespeichert werden die erzeugten Dateien nicht.
      </p>
      {isUnit && (
        <SelectField
          label="Briefbogen"
          value={current.may_have_own ? v.mode : 'inherit'}
          disabled={!editable || !current.may_have_own}
          error={errors.mode}
          hint={
            current.may_have_own
              ? undefined
              : 'Einen eigenen Briefbogen gibt es nur mit eigenem Arbeitsbereich.'
          }
          onChange={(e) => set('mode', e.target.value as LetterheadFields['mode'])}
        >
          <option value="inherit">
            wie {current.owner.is_self ? 'darüber' : current.owner.name}, mit eigenem Namen als
            Zusatzzeile
          </option>
          <option value="own">eigener Briefbogen</option>
        </SelectField>
      )}
      {inherits ? (
        <p className="muted">
          Es gilt der Briefbogen von {current.owner.name}. Der Name {state.organization.name}{' '}
          erscheint im Kopf als Zusatzzeile; Logo/Wappen ist das eigene, falls hinterlegt.
        </p>
      ) : (
        <fieldset disabled={!editable}>
          <div className="grid-2">
            <SelectField
              label="Aufbau"
              value={v.form}
              onChange={(e) => set('form', e.target.value as LetterheadFields['form'])}
            >
              <option value="b">DIN 5008 Form B (Anschriftfeld 45 mm von oben)</option>
              <option value="a">DIN 5008 Form A (Anschriftfeld 27 mm von oben)</option>
            </SelectField>
            <SelectField
              label="Logo/Wappen"
              value={v.logo_position}
              onChange={(e) =>
                set('logo_position', e.target.value as LetterheadFields['logo_position'])
              }
            >
              <option value="right">rechts im Kopf</option>
              <option value="left">links im Kopf</option>
              <option value="none">ohne Logo/Wappen</option>
            </SelectField>
            <Field
              label="Zusatzzeile im Kopf"
              value={v.tagline}
              error={errors.tagline}
              placeholder="z. B. gegründet 1920"
              onChange={(e) => set('tagline', e.target.value)}
            />
            <SelectField
              label="Schriftart"
              value={v.font}
              hint="Überall vorhandene Schriften; die Vorlage bettet keine Schrift ein."
              onChange={(e) => set('font', e.target.value)}
            >
              {FONTS.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </SelectField>
            <Field
              label="Anrede"
              value={v.salutation}
              error={errors.salutation}
              onChange={(e) => set('salutation', e.target.value)}
            />
            <Field
              label="Grußformel"
              value={v.closing}
              error={errors.closing}
              onChange={(e) => set('closing', e.target.value)}
            />
          </div>
          <h3>Fußzeile</h3>
          <Checkbox
            label="Bankverbindung"
            checked={v.show_bank}
            onChange={(val) => set('show_bank', val)}
          />
          {v.show_bank && (
            <SelectField
              label="Bankkonto"
              value={v.account ?? ''}
              error={errors.account}
              hint={
                current.accounts.length === 0
                  ? 'Es gibt noch kein aktives Bankkonto mit IBAN (Finanzen › Einrichtung › Konten).'
                  : undefined
              }
              onChange={(e) => set('account', e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">erstes aktives Bankkonto</option>
              {current.accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.iban})
                </option>
              ))}
            </SelectField>
          )}
          <Checkbox
            label="Telefon der Einheit"
            checked={v.show_phone}
            onChange={(val) => set('show_phone', val)}
          />
          <Checkbox
            label="E-Mail der Einheit"
            checked={v.show_email}
            onChange={(val) => set('show_email', val)}
          />
          <Checkbox
            label="Webseite"
            checked={v.show_website}
            onChange={(val) => set('show_website', val)}
          />
          <Checkbox
            label="Social-Media-Kanäle (Einstellungen › Organisation)"
            checked={v.show_social}
            onChange={(val) => set('show_social', val)}
          />
          <Checkbox
            label="Vorstand: Vertretungsberechtigte und Rollen mit „auf dem Briefbogen nennen“"
            checked={v.show_board}
            onChange={(val) => set('show_board', val)}
          />
          {v.show_board && (
            <p className="muted small">
              {current.board.length > 0
                ? `Heute: ${current.board.map((b) => (b.role ? `${b.name} (${b.role})` : b.name)).join(', ')}.`
                : 'Heute steht dort niemand.'}{' '}
              Welche Rollen erscheinen, legst du unter{' '}
              <Link to="/einstellungen/rollen">Rollen &amp; Benutzer</Link> fest; private
              Kontaktdaten anderer erscheinen nie.
            </p>
          )}
          <Checkbox
            label="Registerangaben und USt-IdNr. aus dem Impressum"
            checked={v.show_register}
            onChange={(val) => set('show_register', val)}
          />
        </fieldset>
      )}
      {current.hints.length > 0 && (
        <Alert kind="info">
          <ul className="plain-list">
            {current.hints.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
        </Alert>
      )}
      <h3>Vorschau</h3>
      {/* Vorschau zeigt den gespeicherten Stand; offene Änderungen kenntlich machen (NAF-01) */}
      {editable && auto.state !== 'saved' && auto.state !== 'idle' && (
        <p className="small" role="status">
          {auto.state === 'error'
            ? 'Vorschau veraltet: Die letzten Änderungen sind noch nicht gespeichert.'
            : 'Änderungen werden gespeichert, danach erneuert sich die Vorschau.'}
        </p>
      )}
      <LetterPreview load={preview} version={current.letterhead.updated_at} />
    </form>
  )
}

function NeutralCard({
  orgId,
  unit,
  unitLabel,
}: {
  orgId: number
  unit: number | null
  unitLabel: string
}) {
  const { active, can } = useOrg()
  const withDocs = !!active?.modules.includes('documents') && can(PERM.docsManage)
  const folders = useLoad(
    () =>
      withDocs
        ? docApi.overview(docBase.org(orgId)).then((o) => o.folders)
        : Promise.resolve([] as DocFolder[]),
    [orgId, withDocs],
  )
  const [folder, setFolder] = useState<number | ''>('')
  const [format, setFormat] = useState<FileFormat>('dotx')
  const [message, setMessage] = useState<{ kind: 'info' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  // Erzeugt wird aus dem gespeicherten Stand: erst alles speichern (UI-Audit NAF-01)
  async function saved(): Promise<boolean> {
    if (await flushAllForms()) return true
    setMessage({
      kind: 'error',
      text: 'Die Vorlage wurde noch nicht erstellt. Bitte zuerst die Änderungen speichern.',
    })
    return false
  }

  async function download() {
    setMessage(null)
    if (!(await saved())) return
    try {
      saveBlob(await letterheadApi.neutral(orgId, format, unit), letterFileName(unitLabel, format))
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  async function publish() {
    if (!folder) return
    setBusy(true)
    setMessage(null)
    try {
      if (!(await saved())) return
      const res = await letterheadApi.publish(orgId, folder, format, unit)
      setMessage({
        kind: 'info',
        text: res.created
          ? `„${res.title}“ liegt jetzt in der Dokumentenablage.`
          : `„${res.title}“ hat eine neue Fassung bekommen.`,
      })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      <h2>Neutrale Vorlage</h2>
      <p className="muted small">
        Ohne persönliche Angaben: Name, Funktion und Kontakt sind Felder zum Ausfüllen in Word. So
        finden alle Vorstände dieselbe Grundvorlage.
      </p>
      <SelectField
        label="Dateiformat"
        value={format}
        onChange={(e) => setFormat(e.target.value as FileFormat)}
      >
        <option value="dotx">Word-Vorlage (.dotx): öffnet jedes Mal ein neues Dokument</option>
        <option value="docx">Word-Dokument (.docx): z. B. für Word im Browser</option>
      </SelectField>
      <div className="button-row">
        <button type="button" className="button" onClick={() => void download()}>
          Herunterladen
        </button>
      </div>
      {withDocs && (
        <div className="grid-2">
          <SelectField
            label="In der Dokumentenablage ablegen"
            value={folder}
            onChange={(e) => setFolder(e.target.value ? Number(e.target.value) : '')}
          >
            <option value="">Ordner wählen …</option>
            {(folders.data ?? []).map((f) => (
              <option key={f.id} value={f.id}>
                {f.name} ({f.visibility_label})
              </option>
            ))}
          </SelectField>
          {folders.error && (
            <LoadError
              message={`Die Ordner konnten nicht geladen werden. Deine Eingaben bleiben erhalten. ${folders.error}`}
              onRetry={() => void folders.reload()}
            />
          )}
          {folders.data?.length === 0 && (
            <p className="muted small">
              Noch kein Ordner vorhanden. <Link to="/dokumente">Dokumentenablage öffnen</Link>
            </p>
          )}
          <div className="button-row">
            <button
              type="button"
              className="button"
              disabled={!folder || busy}
              onClick={() => void publish()}
            >
              Ablegen
            </button>
          </div>
        </div>
      )}
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
    </div>
  )
}

/** Einstellungen › Briefbogen: die Einheit selbst und ihre Untereinheiten. */
export function LetterheadSettingsPage() {
  const org = useActiveOrg()
  const { can } = useOrg()
  const editable = can(PERM.orgEdit)
  const [unitId, setUnitId] = useState<number | null>(null)
  const units = useLoad(
    () => (org.type === 'club' ? orgApi.departments(org.id) : Promise.resolve([] as Department[])),
    [org.id],
  )
  const state = useLoad(
    () => (unitId ? letterheadApi.unit(org.id, unitId) : letterheadApi.get(org.id)),
    [org.id, unitId],
  )
  const list = units.data ?? []
  const unitLabel = unitId ? (list.find((d) => d.id === unitId)?.name ?? org.name) : org.name

  return (
    <>
      {units.error && (
        <LoadError
          message={`Die ${org.department_label_plural} konnten nicht geladen werden; ihre Briefbögen sind deshalb gerade nicht wählbar. ${units.error}`}
          onRetry={() => void units.reload()}
        />
      )}
      {list.length > 0 && (
        <div className="card card-wide">
          <SelectField
            label="Briefbogen für"
            value={unitId ?? ''}
            hint={`${org.department_label_plural} übernehmen standardmäßig den Briefbogen von ${org.name}.`}
            onChange={(e) => setUnitId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">{org.name}</option>
            {list.map((d) => (
              <option key={d.id} value={d.id}>
                {unitName(d)}
              </option>
            ))}
          </SelectField>
        </div>
      )}
      {state.error && <Alert kind="error">{state.error}</Alert>}
      {!state.data && !state.error && <p className="muted">Lädt …</p>}
      {state.data && state.data.organization.id === (unitId ?? org.id) && (
        <>
          <LetterheadEditor
            key={state.data.organization.id}
            state={state.data}
            editable={editable}
            save={(changes) =>
              unitId
                ? letterheadApi.updateUnit(org.id, unitId, changes)
                : letterheadApi.update(org.id, changes)
            }
            preview={() => letterheadApi.preview(org.id, unitId)}
          />
          <NeutralCard orgId={org.id} unit={unitId} unitLabel={unitLabel} />
        </>
      )}
    </>
  )
}
