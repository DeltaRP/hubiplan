import { useState } from 'react'
import type { ChangeEvent } from 'react'
import { exchangeApi, waitFor } from '../../api/exchange.ts'
import type { ImportJob, ImportTarget } from '../../api/exchange.ts'
import { memberApi } from '../../api/members.ts'
import { orgApi, unitName } from '../../api/orgs.ts'
import {
  errorMessage,
  formatDate,
  formatDateTime,
  useLoad,
  useUnmountSignal,
} from '../../components/forms.ts'
import { Alert, LoadError } from '../../components/ui.tsx'
import { RangePager } from '../../components/ListControls.tsx'
import { downloadCsv } from '../../components/csv.ts'
import { confirmDiscard, useChangesGuard } from '../../components/leaveGuard.ts'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { fillTerms, useTerms } from '../../org/terms.ts'
import { confirmDialog } from '../../components/dialog.ts'

const EXIT_REASONS = [
  { value: 'exit', label: 'Austritt' },
  { value: 'exclusion', label: 'Ausschluss' },
  { value: 'strike_off', label: 'Streichung' },
  { value: 'death', label: 'Tod' },
  { value: 'transfer', label: 'Wechsel in {e_einen_anderen}' },
]

/** Import von Altdaten in Schritten: Datei → Spalten → Werte → Prüfen → Importieren. */
export function ImportPage() {
  const org = useActiveOrg()
  const history = useLoad(() => exchangeApi.imports(org.id), [org.id])
  const [job, setJob] = useState<ImportJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(action: () => Promise<ImportJob>) {
    setBusy(true)
    setError(null)
    try {
      setJob(await action())
      await history.reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (file) await run(() => exchangeApi.upload(org.id, file))
  }

  return (
    <>
      <p className="muted">
        Excel- oder CSV-Datei mit einer Zeile je Person. Gespeichert wird erst nach der Prüfung.
        Frühere Zeiträume gehen als zusätzliche Spalten (Eintritt 2, Austritt 2 …) oder als weitere
        Zeile derselben Person.
      </p>
      {error && <Alert kind="error">{error}</Alert>}

      {!job ? (
        <div className="stack">
          <div className="card card-wide">
            <h2>1. Datei hochladen</h2>
            <label className="button button-primary">
              {busy ? 'Wird gelesen …' : 'Datei wählen (.xlsx, .csv)'}
              <input
                type="file"
                accept=".xlsx,.csv,.txt"
                className="file-input"
                disabled={busy}
                onChange={upload}
              />
            </label>
          </div>
          {history.data && history.data.length > 0 && (
            <div className="card card-wide">
              <h2>Bisherige Importe</h2>
              <ul className="plain-list">
                {history.data.map((j) => (
                  <li key={j.id}>
                    <button type="button" className="link-button" onClick={() => setJob(j)}>
                      {j.file_name}
                    </button>{' '}
                    <span className="muted small">
                      · {j.status_label} · {formatDateTime(j.created_at)}
                      {j.counts.imported !== undefined && ` · ${j.counts.imported} importiert`}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <ImportWizard
          orgId={org.id}
          job={job}
          busy={busy}
          run={run}
          onClose={() => setJob(null)}
          departmentLabel={org.department_label_plural}
        />
      )}
    </>
  )
}

function ImportWizard({
  orgId,
  job,
  busy,
  run,
  onClose,
  departmentLabel,
}: {
  orgId: number
  job: ImportJob
  busy: boolean
  run: (action: () => Promise<ImportJob>) => Promise<void>
  onClose: () => void
  departmentLabel: string
}) {
  const terms = useTerms()
  const targets = useLoad(() => exchangeApi.targets(orgId), [orgId])
  const templates = useLoad(() => exchangeApi.importTemplates(orgId), [orgId])
  const [mapping, setMapping] = useState(job.mapping)
  const [valueMapping, setValueMapping] = useState(job.value_mapping)
  const [linkDuplicates, setLinkDuplicates] = useState(job.options.link_duplicates ?? true)
  const [templateName, setTemplateName] = useState('')
  const editable = ['uploaded', 'validated', 'failed'].includes(job.status)
  const mappedTargets = new Set(Object.values(mapping))
  // Vorschau und Import gehören zu genau der geprüften Zuordnung: jede Änderung
  // danach verlangt eine neue Prüfung.
  const configKey = JSON.stringify([mapping, valueMapping, linkDuplicates])
  const [checkedKey, setCheckedKey] = useState(configKey)
  const signal = useUnmountSignal()
  const stale = job.status === 'validated' && configKey !== checkedKey
  // Ungeprüfte Zuordnung nicht unbemerkt verlieren (UX-Audit 31.10. W01)
  const guard = useChangesGuard(configKey, editable)
  const [templateBusy, setTemplateBusy] = useState(false)
  const [templateMsg, setTemplateMsg] = useState<{
    kind: 'error' | 'success'
    text: string
  } | null>(null)

  async function saveTemplate() {
    if (!templateName.trim()) return
    setTemplateBusy(true)
    setTemplateMsg(null)
    try {
      await exchangeApi.saveImportTemplate(orgId, {
        name: templateName.trim(),
        mapping,
        value_mapping: valueMapping,
      })
      setTemplateName('')
      setTemplateMsg({ kind: 'success', text: 'Vorlage gespeichert.' })
      await templates.reload()
    } catch (err) {
      setTemplateMsg({ kind: 'error', text: `Vorlage nicht gespeichert: ${errorMessage(err)}` })
    } finally {
      setTemplateBusy(false)
    }
  }

  async function validate() {
    const key = configKey
    await run(async () => {
      await exchangeApi.configure(orgId, job.id, {
        mapping,
        value_mapping: valueMapping,
        options: { link_duplicates: linkDuplicates },
      })
      await exchangeApi.validate(orgId, job.id)
      const checked = await waitFor(
        () => exchangeApi.importJob(orgId, job.id),
        ['validating'],
        undefined,
        signal(),
      )
      setCheckedKey(key)
      guard.markSaved()
      return checked
    })
  }

  async function startImport() {
    if (
      !(await confirmDialog({
        title: `${job.counts.ok} Personen importieren?`,
        confirmLabel: 'Importieren',
        danger: false,
      }))
    )
      return
    await run(async () => {
      await exchangeApi.run(orgId, job.id)
      return waitFor(() => exchangeApi.importJob(orgId, job.id), ['importing'], 600000, signal())
    })
  }

  return (
    <div className="stack">
      <div className="card card-wide">
        <div className="card-head">
          <h2>{job.file_name}</h2>
          <span className="muted small">
            {job.row_count} Zeilen · {job.status_label}
          </span>
          <button
            type="button"
            className="link-button push-right"
            onClick={() => void confirmDiscard(guard.dirty).then((ok) => ok && onClose())}
          >
            zur Übersicht
          </button>
        </div>
        {job.error && <Alert kind="error">{job.error}</Alert>}
      </div>

      {editable && (
        <div className="card card-wide">
          <h2>2. Spalten zuordnen</h2>
          {targets.error && (
            <LoadError
              message={`Die Felder von HUBIplan konnten nicht geladen werden (${targets.error}). Deine Zuordnung bleibt erhalten.`}
              onRetry={() => void targets.reload()}
            />
          )}
          {templates.error && (
            <LoadError
              message={`Die gespeicherten Vorlagen konnten nicht geladen werden (${templates.error}).`}
              onRetry={() => void templates.reload()}
            />
          )}
          {templates.data && templates.data.length > 0 && (
            <div className="chips">
              {templates.data.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className="chip"
                  onClick={() => {
                    setMapping(t.mapping)
                    setValueMapping(t.value_mapping)
                  }}
                >
                  Vorlage: {t.name}
                </button>
              ))}
            </div>
          )}
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Spalte in der Datei</th>
                  <th>Beispielwerte</th>
                  <th>Feld in HUBIplan</th>
                </tr>
              </thead>
              <tbody>
                {job.headers.map((h, i) => (
                  <tr key={i}>
                    <td>
                      <strong>{h}</strong>
                    </td>
                    <td className="small muted">
                      {job.sample
                        .map((r) => r[i])
                        .filter((v) => v !== null && v !== '')
                        .slice(0, 3)
                        .map(String)
                        .join(' · ')}
                    </td>
                    <td>
                      <select
                        aria-label={`Feld für ${h}`}
                        disabled={!targets.data}
                        value={mapping[String(i)] ?? ''}
                        onChange={(e) =>
                          setMapping((m) => {
                            const next = { ...m }
                            if (e.target.value) next[String(i)] = e.target.value
                            else delete next[String(i)]
                            return next
                          })
                        }
                      >
                        <option value="">– nicht importieren –</option>
                        {(targets.data ?? []).map((t) => (
                          <option
                            key={t.key}
                            value={t.key}
                            disabled={mappedTargets.has(t.key) && mapping[String(i)] !== t.key}
                          >
                            {t.label}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="inline-add">
            <input
              aria-label="Name der Vorlage"
              placeholder="Zuordnung als Vorlage speichern"
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
            />
            <button
              type="button"
              className="button button-ghost"
              disabled={templateBusy || !templateName.trim()}
              onClick={() => void saveTemplate()}
            >
              {templateBusy ? 'Wird gespeichert …' : 'Vorlage speichern'}
            </button>
          </div>
          {templateMsg && (
            <p
              className={templateMsg.kind === 'error' ? 'alert alert-error' : 'muted small'}
              role={templateMsg.kind === 'error' ? 'alert' : 'status'}
            >
              {templateMsg.text}
            </p>
          )}
        </div>
      )}

      {editable && targets.data && (
        <ValueMappings
          orgId={orgId}
          job={job}
          mapping={mapping}
          targets={targets.data}
          valueMapping={valueMapping}
          setValueMapping={setValueMapping}
          departmentLabel={departmentLabel}
        />
      )}

      {editable && (
        <div className="card card-wide">
          <h2>4. Prüfen</h2>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={linkDuplicates}
              onChange={(e) => setLinkDuplicates(e.target.checked)}
            />
            <span>
              {terms.dv_has
                ? `Gefundene Personen ${terms.dv_im} verknüpfen (Verbandsnummer bleibt erhalten)`
                : 'Gefundene Personen verknüpfen'}
            </span>
          </label>
          <button
            type="button"
            className="button button-primary"
            disabled={busy}
            onClick={() => void validate()}
          >
            {busy ? 'Wird geprüft …' : 'Prüfen'}
          </button>
        </div>
      )}

      {stale && (
        <Alert kind="error">
          Zuordnung geändert – bitte erneut prüfen. Die Vorschau unten zeigt noch den alten Stand.
        </Alert>
      )}

      {job.preview.length > 0 && <Preview job={job} />}

      {job.status === 'validated' && (
        <div className="card card-wide">
          <h2>5. Importieren</h2>
          {stale && <p className="muted">Erst nach erneutem Prüfen möglich.</p>}
          <p>
            {job.counts.ok} Personen werden importiert
            {job.counts.errors ? `, ${job.counts.errors} mit Fehlern nicht` : ''}.
          </p>
          <button
            type="button"
            className="button button-primary"
            disabled={busy || stale || !job.counts.ok}
            onClick={() => void startImport()}
          >
            {busy ? 'Wird importiert …' : 'Jetzt importieren'}
          </button>
        </div>
      )}

      {job.status === 'imported' && (
        <div className="card card-wide">
          <h2>Ergebnis</h2>
          <p>
            {job.counts.imported} Personen importiert
            {job.imported_at && ` am ${formatDateTime(job.imported_at)}`}.
            {job.keep_until &&
              ` Protokoll und „Rückgängig“ bleiben bis ${formatDateTime(job.keep_until)}.`}
          </p>
          {job.has_error_file && (
            <p>
              <a href={exchangeApi.errorFileUrl(orgId, job.id)}>Fehlerliste herunterladen</a> – zum
              Nachbearbeiten und erneuten Import.
            </p>
          )}
          {job.undo_blockers.length === 0 ? (
            <button
              type="button"
              className="button button-danger"
              disabled={busy}
              onClick={async () => {
                if (
                  await confirmDialog({
                    title: 'Import vollständig rückgängig machen?',
                    confirmLabel: 'Rückgängig machen',
                  })
                ) {
                  void run(() => exchangeApi.undo(orgId, job.id))
                }
              }}
            >
              Import rückgängig machen
            </button>
          ) : (
            <p className="muted small">
              Rückgängig nicht mehr möglich: {job.undo_blockers.join(' ')}
            </p>
          )}
        </div>
      )}
      {job.status === 'undone' && (
        <Alert kind="info">Dieser Import wurde rückgängig gemacht.</Alert>
      )}
    </div>
  )
}

function ValueMappings({
  orgId,
  job,
  mapping,
  targets,
  valueMapping,
  setValueMapping,
  departmentLabel,
}: {
  orgId: number
  job: ImportJob
  mapping: Record<string, string>
  targets: ImportTarget[]
  valueMapping: Record<string, Record<string, string>>
  setValueMapping: (
    fn: (v: Record<string, Record<string, string>>) => Record<string, Record<string, string>>,
  ) => void
  departmentLabel: string
}) {
  const tm = useTerms()
  const mapped = new Set(Object.values(mapping).map((t) => t.replace(/_\d$/, '')))
  const needed = targets.filter((t) => t.value_mapped && mapped.has(t.key))
  const types = useLoad(() => memberApi.types(orgId), [orgId])
  const departments = useLoad(() => orgApi.departments(orgId), [orgId])
  const roles = useLoad(() => orgApi.roles(orgId).catch(() => []), [orgId])
  if (needed.length === 0) return null
  const choices: Record<string, { value: string; label: string }[]> = {
    member_type: (types.data ?? []).map((t) => ({ value: String(t.id), label: t.name })),
    departments: (departments.data ?? []).map((d) => ({
      value: String(d.id),
      label: unitName(d),
    })),
    exit_reason: EXIT_REASONS.map((r) => ({ ...r, label: fillTerms(r.label, tm) })),
    board_role: (roles.data ?? []).map((r) => ({ value: String(r.id), label: r.name })),
  }
  return (
    <div className="card card-wide">
      <h2>3. Werte zuordnen</h2>
      <p className="muted small">
        Bezeichnungen aus der Datei den Werten in HUBIplan zuordnen, z. B. „Akt.“ → „aktiv“.
      </p>
      {needed.map((t) => (
        <ValueTable
          key={t.key}
          orgId={orgId}
          jobId={job.id}
          target={t.key}
          label={t.key === 'departments' ? departmentLabel : t.label}
          choices={choices[t.key] ?? []}
          values={valueMapping[t.key] ?? {}}
          onChange={(raw, value) =>
            setValueMapping((vm) => ({ ...vm, [t.key]: { ...(vm[t.key] ?? {}), [raw]: value } }))
          }
        />
      ))}
    </div>
  )
}

function ValueTable({
  orgId,
  jobId,
  target,
  label,
  choices,
  values,
  onChange,
}: {
  orgId: number
  jobId: number
  target: string
  label: string
  choices: { value: string; label: string }[]
  values: Record<string, string>
  onChange: (raw: string, value: string) => void
}) {
  const raw = useLoad(() => exchangeApi.values(orgId, jobId, target), [orgId, jobId, target])
  if (!raw.data || raw.data.length === 0) return null
  return (
    <>
      <h3>{label}</h3>
      <table className="table">
        <tbody>
          {raw.data.map((v) => (
            <tr key={v}>
              <td>„{v}“</td>
              <td>
                <select
                  aria-label={`${label}: ${v}`}
                  value={values[v] ?? ''}
                  onChange={(e) => onChange(v, e.target.value)}
                >
                  <option value="">– gleichnamig / unbekannt –</option>
                  {choices.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function Preview({ job }: { job: ImportJob }) {
  const terms = useTerms()
  const [onlyProblems, setOnlyProblems] = useState(true)
  const [page, setPage] = useState(1)
  const rows = onlyProblems ? job.preview.filter((p) => p.status !== 'ok') : job.preview
  // Alle Zeilen erreichbar, seitenweise statt still nach 300 abgeschnitten (UX-Audit 31.10. W04)
  const size = 50
  const lastPage = Math.max(1, Math.ceil(rows.length / size))
  const current = Math.min(page, lastPage)
  const problems = job.preview.filter((p) => p.status !== 'ok')
  return (
    <div className="card card-wide">
      <h2>Vorschau</h2>
      <p>
        {job.counts.persons} Personen aus {job.counts.rows} Zeilen ·{' '}
        <strong>{job.counts.ok} fehlerfrei</strong> · {job.counts.errors} mit Fehlern ·{' '}
        {job.counts.duplicates} schon {terms.dv_has ? `${terms.dv_im} ` : ''}vorhanden
      </p>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={onlyProblems}
          onChange={(e) => {
            setOnlyProblems(e.target.checked)
            setPage(1)
          }}
        />
        <span>nur Fehler und Dubletten zeigen</span>
      </label>
      {problems.length > 0 && (
        <p>
          <button
            type="button"
            className="link-button"
            onClick={() =>
              downloadCsv(`Pruefliste-${job.file_name.replace(/\.[^.]+$/, '')}.csv`, [
                ['Zeile', 'Person', 'Geburtsdatum', 'Ergebnis'],
                ...problems.map((p) => [
                  p.rows.join(', '),
                  p.name,
                  p.birth_date ? formatDate(p.birth_date) : '',
                  p.messages.join(' '),
                ]),
              ])
            }
          >
            Prüfliste herunterladen (CSV, {problems.length} Einträge)
          </button>
        </p>
      )}
      {rows.length === 0 && <p className="muted">Keine Einträge.</p>}
      <table className="table">
        <thead>
          <tr>
            <th>Zeile</th>
            <th>Person</th>
            <th>Ergebnis</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice((current - 1) * size, current * size).map((p) => (
            <tr key={p.rows.join('-')} className={`preview-${p.status}`}>
              <td>{p.rows.join(', ')}</td>
              <td>
                {p.name}
                {p.birth_date && <span className="muted small"> · {formatDate(p.birth_date)}</span>}
              </td>
              <td className="small">{p.status === 'ok' ? 'ok' : p.messages.join(' ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <RangePager
        page={current}
        size={size}
        total={rows.length}
        onPage={setPage}
        noun="Einträgen"
      />
    </div>
  )
}
