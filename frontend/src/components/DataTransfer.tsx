// Vollständiger Export (JSON oder ZIP) und Import aus einer Exportdatei.
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { FormEvent } from 'react'
import { waitFor } from '../api/exchange.ts'
import { displayName, unitName } from '../api/orgs.ts'
import { transferApi } from '../api/datatransfer.ts'
import type { ImportPreview, TransferBase, TransferJob } from '../api/datatransfer.ts'
import { errorMessage, formatDateTime, useForm, useLoad, useUnmountSignal } from './forms.ts'
import { Alert, Checkbox, Field, LoadError, SelectField } from './ui.tsx'
import { fillTerms, useTerms } from '../org/terms.ts'

const RUNNING = ['pending', 'running']

function size(bytes: number): string {
  if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

/** Export erstellen und frühere Exporte herunterladen. */
export function ExportSection({
  base,
  departments,
  organizations,
}: {
  base: TransferBase
  /** Verein: Abteilungen, die sich einzeln exportieren lassen */
  departments?: { id: number; name: string; display_name?: string }[]
  /** Plattform: Organisationen zur Auswahl */
  organizations?: { id: number; name: string; display_name?: string; type_label: string }[]
}) {
  const t = useTerms()
  const jobs = useLoad(() => transferApi.exports(base), [JSON.stringify(base)])
  const [withFiles, setWithFiles] = useState(false)
  const [target, setTarget] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [last, setLast] = useState<TransferJob | null>(null)
  const signal = useUnmountSignal()

  async function start() {
    setBusy(true)
    setError(null)
    setLast(null)
    try {
      const data: Record<string, unknown> = { with_files: withFiles }
      if (organizations) data.organization = Number(target)
      else if (target) {
        data.kind = 'department'
        data.department = Number(target)
      }
      const created = await transferApi.startExport(base, data as never)
      setLast(
        await waitFor(() => transferApi.exportJob(base, created.id), RUNNING, 300000, signal()),
      )
      await jobs.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      <h2>Vollständiger Export</h2>
      <p className="muted small">
        Alle Daten als eine Datei: Stammdaten, Rollen, Mitgliedsarten, Zusatzfelder, {t.pl},
        Mitglieder mit allen Zeiträumen, Kasse, Beiträge und Rechnungen sowie die Satzung.
        Benutzerkonten und Passwörter sind nicht enthalten. Jeder Export wird protokolliert, die
        Datei wird nach 7 Tagen gelöscht.
      </p>
      <div className="filters">
        {organizations && (
          <select
            aria-label="Organisation"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          >
            <option value="">Einheit wählen …</option>
            {organizations.map((o) => (
              <option key={o.id} value={o.id}>
                {displayName(o)} ({o.type_label})
              </option>
            ))}
          </select>
        )}
        {departments && departments.length > 0 && (
          <select aria-label="Umfang" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">
              ganz{t.e_adj} {t.e_sg}
            </option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                nur {t.sg} {unitName(d)}
              </option>
            ))}
          </select>
        )}
        <Checkbox
          label="mit Dateien (Logos, Belege, Fotos, Satzung) als ZIP"
          checked={withFiles}
          onChange={setWithFiles}
        />
        <button
          type="button"
          className="button button-primary"
          disabled={busy || (!!organizations && !target)}
          onClick={() => void start()}
        >
          {busy ? 'Wird erstellt …' : 'Export erstellen'}
        </button>
      </div>
      {error && <Alert kind="error">{error}</Alert>}
      {last?.status === 'done' && (
        <Alert kind="success">
          Fertig.{' '}
          <a href={transferApi.downloadUrl(base, last.id)}>{last.file_name} herunterladen</a>
        </Alert>
      )}
      {last?.status === 'failed' && <Alert kind="error">Export fehlgeschlagen: {last.error}</Alert>}
      {last && RUNNING.includes(last.status) && (
        <Alert kind="info">Der Export läuft noch im Hintergrund. Die Liste unten zeigt ihn.</Alert>
      )}
      {jobs.error && (
        <LoadError
          message={`Die bisherigen Exporte konnten nicht geladen werden: ${jobs.error}`}
          onRetry={() => void jobs.reload()}
        />
      )}
      {jobs.data && jobs.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Erstellt</th>
              <th>Inhalt</th>
              <th>Datei</th>
            </tr>
          </thead>
          <tbody>
            {jobs.data.map((j) => (
              <tr key={j.id}>
                <td className="small">
                  {formatDateTime(j.created_at)}
                  <div className="muted">{j.created_by}</div>
                </td>
                <td className="small">
                  {j.subject?.name ?? j.department?.name ?? 'ganze Organisation'}
                  {j.with_files ? ' · mit Dateien' : ''}
                </td>
                <td className="small">
                  {j.status === 'done' && j.has_file ? (
                    <a href={transferApi.downloadUrl(base, j.id)}>
                      {j.file_name} ({size(j.size)})
                    </a>
                  ) : j.status === 'done' ? (
                    <span className="muted">gelöscht</span>
                  ) : (
                    <span className="muted">{j.status_label}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

const TARGET_TEXT = {
  platform: {
    title: 'Einheit importieren',
    hint: 'Aus der Exportdatei einer Einheit (mit ihren Untereinheiten) entsteht eine neue Einheit direkt unter der Plattform.',
  },
  federation: {
    title: '{Sg} aus Datei anlegen',
    hint: 'Aus der Exportdatei entsteht {ein} {e_im}. Personen, die es {e_im} schon gibt, werden erkannt.',
  },
  club: {
    title: '{Sg} aus Datei anlegen',
    hint: 'Aus der Exportdatei entsteht {ein} mit Rollen und Mitgliedern. Wer schon Mitglied {e_im} ist, wird nur zugeordnet.',
  },
}

const SUMMARY_LABELS: Record<string, string> = {
  clubs: '{Pl}',
  departments: 'Untereinheiten',
  roles: 'Rollen',
  role_assignments: 'Rollenbesetzungen',
  persons: 'Personen',
  memberships: 'Mitgliedschaften',
  already_members: 'schon Mitglied {e_im}',
  table_rows: 'Kasse, Beiträge und Satzung (Einträge)',
  files: 'Dateien',
}

/** Datei hochladen, Vorschau prüfen, Dubletten entscheiden, übernehmen. */
export function ImportSection({
  base,
  target,
  onImported,
}: {
  base: TransferBase
  target: 'platform' | 'federation' | 'club'
  onImported?: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [invite, setInvite] = useState(false)
  const [boardEmail, setBoardEmail] = useState('')
  const [address, setAddress] = useState<Address>(NO_ADDRESS)
  const [job, setJob] = useState<TransferJob | null>(null)
  const [choices, setChoices] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const t = useTerms()
  const text = TARGET_TEXT[target]
  const title = fillTerms(text.title, t)
  const signal = useUnmountSignal()
  // Auftrag in der Adresse merken: nach Neuladen oder Rückkehr wieder erreichbar
  // (UI-Audit NAF-04)
  const [params, setParams] = useSearchParams()
  const jobParam = Number(params.get('import')) || null
  const openJobs = useLoad(() => transferApi.imports(base), [JSON.stringify(base)])

  function rememberJob(id: number | null) {
    setParams(
      (p) => {
        const next = new URLSearchParams(p)
        if (id) next.set('import', String(id))
        else next.delete('import')
        return next
      },
      { replace: true },
    )
  }

  // Nur beim Öffnen mit Auftrag in der Adresse fortsetzen; spätere Änderungen der
  // Adresse kommen von hier selbst und dürfen die Entscheidungen nicht zurücksetzen
  const initialJob = useRef(jobParam)
  useEffect(() => {
    const id = initialJob.current
    initialJob.current = null
    if (id) void act(() => transferApi.importJob(base, id))
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const preview = job?.preview && 'kind' in job.preview ? (job.preview as ImportPreview) : null

  async function wait(id: number) {
    return waitFor(() => transferApi.importJob(base, id), RUNNING, 600000, signal())
  }

  async function act(action: () => Promise<TransferJob>) {
    setBusy(true)
    setError(null)
    let started: TransferJob | null = null
    try {
      started = await action()
      // Den Auftrag sofort merken: auch wenn das Nachfragen scheitert, bleibt er erreichbar
      setJob(started)
      rememberJob(started.id)
      const finished = await wait(started.id)
      setJob(finished)
      const p = finished.preview as ImportPreview
      if (p && 'duplicates' in p) {
        const next: Record<string, string> = {}
        for (const d of p.duplicates) if (!d.fixed) next[String(d.person)] = d.choice
        setChoices(next)
      }
      if (finished.status === 'done') onImported?.()
    } catch (err) {
      setError(
        started
          ? `Die Verbindung wurde unterbrochen (${errorMessage(err)}). Der Auftrag kann trotzdem weiterlaufen; frag den Stand unten erneut ab.`
          : errorMessage(err),
      )
    } finally {
      setBusy(false)
    }
  }

  function options() {
    return {
      name: name.trim(),
      invite,
      board_email: boardEmail.trim(),
      ...trimmed(address),
      persons: choices,
    }
  }

  function reset() {
    rememberJob(null)
    void openJobs.reload()
    setJob(null)
    setFile(null)
    setName('')
    setBoardEmail('')
    setAddress(NO_ADDRESS)
    setInvite(false)
  }

  if (job?.status === 'done') {
    const result = job.summary as {
      organization?: { name: string }
      department?: { name: string }
      new_members?: number
      invited?: number
      renumbered?: number
      skipped_assignments?: number
    }
    return (
      <div className="card card-wide">
        <h2>{title}</h2>
        <Alert kind="success">
          „{result.organization?.name ?? result.department?.name}“ wurde angelegt.
          {result.new_members ? ` ${result.new_members} neue Mitglieder ${t.e_im}.` : ''}
          {result.invited ? ` ${result.invited} Einladungen verschickt.` : ''}
          {result.renumbered ? ` ${result.renumbered} Verbandsnummern neu vergeben.` : ''}
          {result.skipped_assignments
            ? ` ${result.skipped_assignments} Rollenbesetzungen ohne Konto entfielen.`
            : ''}
        </Alert>
        <button type="button" className="button button-ghost" onClick={reset}>
          Weitere Datei importieren
        </button>
      </div>
    )
  }

  return (
    <div className="card card-wide">
      <h2>{title}</h2>
      <p className="muted small">{fillTerms(text.hint, t)}</p>
      {job && RUNNING.includes(job.status) && (
        <div className="stack-sm">
          <Alert kind="info">
            Auftrag {job.id} wird noch bearbeitet. Du kannst den Stand jederzeit erneut abfragen;
            dabei entsteht kein neuer Auftrag.
          </Alert>
          <div className="button-row">
            <button
              type="button"
              className="button button-ghost"
              disabled={busy}
              onClick={() => void act(() => transferApi.importJob(base, job.id))}
            >
              {busy ? 'Wird abgefragt …' : 'Stand erneut abfragen'}
            </button>
          </div>
        </div>
      )}
      {!job && (openJobs.data ?? []).some((j) => j.status !== 'done' && j.status !== 'failed') && (
        <div className="subcard stack-sm">
          <h3>Offene Aufträge</h3>
          <ul className="plain-list">
            {(openJobs.data ?? [])
              .filter((j) => j.status !== 'done' && j.status !== 'failed')
              .map((j) => (
                <li key={j.id}>
                  {j.file_name || `Auftrag ${j.id}`}{' '}
                  <span className="muted small">
                    {formatDateTime(j.created_at)} · {j.status_label}
                  </span>{' '}
                  <button
                    type="button"
                    className="link-button"
                    disabled={busy}
                    onClick={() => void act(() => transferApi.importJob(base, j.id))}
                  >
                    {j.status === 'checked' ? 'Auftrag weiter prüfen' : 'Stand ansehen'}
                  </button>
                </li>
              ))}
          </ul>
        </div>
      )}
      {!job && openJobs.error && (
        <LoadError
          message={`Offene Aufträge konnten nicht geladen werden. ${openJobs.error}`}
          onRetry={() => void openJobs.reload()}
        />
      )}
      {!job && (
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            if (file) void act(() => transferApi.upload(base, file, options()))
          }}
        >
          <label className="field">
            <span>Exportdatei (.json oder .zip)</span>
            <input
              type="file"
              accept=".json,.zip,application/json,application/zip"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <button type="submit" className="button button-primary" disabled={!file || busy}>
            {busy ? 'Wird geprüft …' : 'Hochladen und prüfen'}
          </button>
        </form>
      )}
      {job?.status === 'failed' && (
        <>
          <Alert kind="error">{job.error}</Alert>
          <button type="button" className="button button-ghost" onClick={reset}>
            Andere Datei wählen
          </button>
        </>
      )}
      {preview && job && (
        <ImportPreviewView
          preview={preview}
          target={target}
          choices={choices}
          setChoices={setChoices}
          name={name}
          setName={setName}
          invite={invite}
          setInvite={setInvite}
          boardEmail={boardEmail}
          setBoardEmail={setBoardEmail}
          address={address}
          setAddress={setAddress}
          busy={busy}
          runError={job.error}
          onRecheck={() => void act(() => transferApi.recheck(base, job.id, options()))}
          onRun={() =>
            void act(async () => {
              // Geänderte Angaben zuerst prüfen lassen, dann übernehmen
              const checked = await wait((await transferApi.recheck(base, job.id, options())).id)
              setJob(checked)
              const p = checked.preview as ImportPreview
              if (checked.status !== 'checked' || p.error_count) return checked
              return transferApi.run(base, job.id)
            })
          }
          onCancel={reset}
        />
      )}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}

type Address = { street: string; postal_code: string; city: string }
const NO_ADDRESS: Address = { street: '', postal_code: '', city: '' }

/** Nur ausgefüllte Felder schicken: leere übernehmen die Anschrift aus der Datei. */
function trimmed(a: Address): Partial<Address> {
  return Object.fromEntries(
    Object.entries(a)
      .map(([k, v]) => [k, v.trim()])
      .filter(([, v]) => v),
  )
}

function ImportPreviewView({
  preview,
  target,
  choices,
  setChoices,
  name,
  setName,
  invite,
  setInvite,
  boardEmail,
  setBoardEmail,
  address,
  setAddress,
  busy,
  runError,
  onRecheck,
  onRun,
  onCancel,
}: {
  preview: ImportPreview
  target: 'platform' | 'federation' | 'club'
  choices: Record<string, string>
  setChoices: (c: Record<string, string>) => void
  name: string
  setName: (v: string) => void
  invite: boolean
  setInvite: (v: boolean) => void
  boardEmail: string
  setBoardEmail: (v: string) => void
  address: Address
  setAddress: (a: Address) => void
  busy: boolean
  runError: string
  onRecheck: () => void
  onRun: () => void
  onCancel: () => void
}) {
  const t = useTerms()
  const open = preview.duplicates.filter((d) => !d.fixed)
  const fixed = preview.duplicates.filter((d) => d.fixed)
  const counts = Object.entries(preview.summary).filter(
    ([key, value]) => SUMMARY_LABELS[key] && value,
  )
  return (
    <div className="import-preview">
      <p>
        Datei von <strong>{preview.source.name}</strong>
        {preview.exported_at ? `, exportiert am ${formatDateTime(preview.exported_at)}` : ''}.
      </p>
      <ul className="small">
        {counts.map(([key, value]) => (
          <li key={key}>
            {fillTerms(
              key === 'departments' && target === 'club' ? '{Pl}' : (SUMMARY_LABELS[key] ?? key),
              t,
            )}
            : {value}
          </li>
        ))}
      </ul>
      {preview.classes && Object.keys(preview.classes).length > 0 && (
        <details className="small">
          <summary>Je Datenklasse</summary>
          <ul>
            {Object.entries(preview.classes).map(([label, n]) => (
              <li key={label}>
                {label}: {n}
              </li>
            ))}
          </ul>
        </details>
      )}
      {preview.not_included && preview.not_included.length > 0 && (
        <p className="small muted">Nicht übernommen: {preview.not_included.join(', ')}.</p>
      )}
      <Field
        label={target === 'club' ? `Name ${t.gen}` : 'Name der neuen Einheit'}
        value={name}
        placeholder={preview.name}
        onChange={(e) => setName(e.target.value)}
        hint="Leer lassen, um den Namen aus der Datei zu übernehmen."
      />
      {preview.kind === 'unit' && (
        <>
          <Alert kind="info">
            Die Datei enthält eine Untereinheit. Sie wird hier eine eigene Einheit mit eigenen
            Mitgliedern. Die Kennungen der Mitgliedschaften bleiben erhalten, damit der abgebende
            Verein sie im Verbund wieder zuordnen kann.
          </Alert>
          <p className="muted small">
            Anschrift der neuen Einheit. Leer lassen, um die des abgebenden Vereins zu übernehmen.
          </p>
          <Field
            label="Straße und Hausnummer"
            value={address.street}
            onChange={(e) => setAddress({ ...address, street: e.target.value })}
          />
          <Field
            label="PLZ"
            value={address.postal_code}
            onChange={(e) => setAddress({ ...address, postal_code: e.target.value })}
          />
          <Field
            label="Ort"
            value={address.city}
            onChange={(e) => setAddress({ ...address, city: e.target.value })}
          />
        </>
      )}
      {target !== 'club' && (
        <>
          <Field
            label="Erster Vorstand (E-Mail, optional)"
            type="email"
            value={boardEmail}
            onChange={(e) => setBoardEmail(e.target.value)}
            hint="Bekommt die Rolle „Vorstand“. Ohne Konto wird eine Einladung verschickt."
          />
          {preview.users.total > 0 && (
            <Checkbox
              label={`Rollenbesetzungen: ${preview.users.existing} von ${preview.users.total} E-Mail-Adressen haben schon ein Konto. Für die übrigen ${preview.users.new} Einladungen verschicken`}
              checked={invite}
              onChange={setInvite}
            />
          )}
        </>
      )}
      {fixed.length > 0 && (
        <Alert kind="info">
          Schon Mitglied {t.e_im}, werden nur zugeordnet: {fixed.map((d) => d.name).join('; ')}
        </Alert>
      )}
      {open.length > 0 && (
        <>
          <h3>Mögliche Dubletten ({open.length})</h3>
          <p className="muted small">
            Diese Personen gibt es schon (gleicher Name, Vorname und Geburtsdatum). Zusammenführen
            ist meist richtig.
          </p>
          <table className="table">
            <tbody>
              {open.map((d) => (
                <tr key={d.person}>
                  <td>
                    <strong>{d.name}</strong>
                    <div className="small muted">geb. {d.birth_date}</div>
                  </td>
                  <td>
                    <SelectField
                      label="Übernehmen als"
                      value={choices[String(d.person)] ?? d.choice}
                      onChange={(e) =>
                        setChoices({ ...choices, [String(d.person)]: e.target.value })
                      }
                    >
                      {d.candidates.map((c) => (
                        <option key={c.id} value={String(c.id)}>
                          zusammenführen mit {c.name}
                          {c.member_number ? ` (Nr. ${c.member_number})` : ''}
                          {c.clubs.length ? ` – ${c.clubs.map((x) => x.name).join(', ')}` : ''}
                        </option>
                      ))}
                      <option value="new">als neue Person anlegen</option>
                    </SelectField>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {preview.error_count > 0 && (
        <Alert kind="error">
          {preview.error_count} Fehler, so wird nichts angelegt:
          <br />
          {preview.errors.map((e) => (
            <span key={e}>
              • {e}
              <br />
            </span>
          ))}
        </Alert>
      )}
      {preview.warning_count > 0 && (
        <Alert kind="info">
          {preview.warning_count} Hinweise:
          <br />
          {preview.warnings.map((w) => (
            <span key={w}>
              • {w}
              <br />
            </span>
          ))}
        </Alert>
      )}
      {runError && <Alert kind="error">{runError}</Alert>}
      <div className="button-row">
        <button type="button" className="button button-ghost" disabled={busy} onClick={onRecheck}>
          Erneut prüfen
        </button>
        <button type="button" className="button button-primary" disabled={busy} onClick={onRun}>
          {busy ? 'Bitte warten …' : 'Übernehmen'}
        </button>
        <button type="button" className="link-button" disabled={busy} onClick={onCancel}>
          Ansicht schließen (der geprüfte Auftrag bleibt unter „Offene Aufträge“)
        </button>
      </div>
    </div>
  )
}

/** Dachverband legt einen Verein von Hand an. */
export function ClubCreateForm({
  federationId,
  onDone,
}: {
  federationId: number
  onDone: () => void
}) {
  const t = useTerms()
  const form = useForm({
    name: '',
    founding_year: '',
    street: '',
    postal_code: '',
    city: '',
    contact_email: '',
    board_email: '',
  })
  const v = form.values

  async function save(e: FormEvent) {
    e.preventDefault()
    const result = await form.submit(
      () =>
        transferApi.createClub(federationId, {
          ...v,
          founding_year: v.founding_year ? Number(v.founding_year) : null,
        }),
      fillTerms('{Nom} wurde angelegt.', t),
    )
    if (result) {
      form.setValues({
        name: '',
        founding_year: '',
        street: '',
        postal_code: '',
        city: '',
        contact_email: '',
        board_email: '',
      })
      onDone()
    }
  }

  return (
    <form className="card card-wide" onSubmit={(e) => void save(e)}>
      <h2>{t.Sg} von Hand anlegen</h2>
      <div className="grid-2">
        <Field
          label="Name"
          value={v.name}
          error={form.errors.name}
          onChange={(e) => form.set('name', e.target.value)}
          required
        />
        <Field
          label="Gründungsjahr"
          inputMode="numeric"
          value={v.founding_year}
          error={form.errors.founding_year}
          onChange={(e) => form.set('founding_year', e.target.value)}
          required
        />
        <Field
          label="Straße und Hausnummer"
          value={v.street}
          error={form.errors.street}
          onChange={(e) => form.set('street', e.target.value)}
          required
        />
        <Field
          label="PLZ"
          value={v.postal_code}
          error={form.errors.postal_code}
          onChange={(e) => form.set('postal_code', e.target.value)}
          required
        />
        <Field
          label="Ort"
          value={v.city}
          error={form.errors.city}
          onChange={(e) => form.set('city', e.target.value)}
          required
        />
        <Field
          label={`E-Mail ${t.gen}`}
          type="email"
          value={v.contact_email}
          error={form.errors.contact_email}
          onChange={(e) => form.set('contact_email', e.target.value)}
        />
        <Field
          label="Erster Vorstand (E-Mail, optional)"
          type="email"
          value={v.board_email}
          error={form.errors.board_email}
          onChange={(e) => form.set('board_email', e.target.value)}
          hint="Bekommt die Rolle „Vorstand“. Ohne Konto wird eine Einladung verschickt."
        />
      </div>
      {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
      <button type="submit" className="button button-primary" disabled={form.busy}>
        {t.Sg} anlegen
      </button>
    </form>
  )
}
