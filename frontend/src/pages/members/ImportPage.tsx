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
import { t } from '../../i18n/index.ts'

const EXIT_REASONS = [
  { value: 'exit', label: t('Austritt') },
  { value: 'exclusion', label: t('Ausschluss') },
  { value: 'strike_off', label: t('Streichung') },
  { value: 'death', label: t('Tod') },
  { value: 'transfer', label: t('Wechsel in {e_einen_anderen}') },
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
        {t(
          'Excel- oder CSV-Datei mit einer Zeile je Person. Gespeichert wird erst nach der Prüfung. Frühere Zeiträume gehen als zusätzliche Spalten (Eintritt 2, Austritt 2 …) oder als weitere Zeile derselben Person.',
        )}
      </p>
      {error && <Alert kind="error">{error}</Alert>}

      {!job ? (
        <div className="stack">
          <div className="card card-wide">
            <h2>{t('1. Datei hochladen')}</h2>
            <label className="button button-primary">
              {busy ? t('Wird gelesen …') : t('Datei wählen (.xlsx, .csv)')}
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
              <h2>{t('Bisherige Importe')}</h2>
              <ul className="plain-list">
                {history.data.map((j) => (
                  <li key={j.id}>
                    <button type="button" className="link-button" onClick={() => setJob(j)}>
                      {j.file_name}
                    </button>{' '}
                    <span className="muted small">
                      · {j.status_label} · {formatDateTime(j.created_at)}
                      {j.counts.imported !== undefined &&
                        t(' · {imported} importiert', { imported: j.counts.imported })}
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
      setTemplateMsg({ kind: 'success', text: t('Vorlage gespeichert.') })
      await templates.reload()
    } catch (err) {
      setTemplateMsg({
        kind: 'error',
        text: t('Vorlage nicht gespeichert: {x}', { x: errorMessage(err) }),
      })
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
        title: t('{ok} Personen importieren?', { ok: job.counts.ok }),
        confirmLabel: t('Importieren'),
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
            {job.row_count} {t('Zeilen ·')} {job.status_label}
          </span>
          <button
            type="button"
            className="link-button push-right"
            onClick={() => void confirmDiscard(guard.dirty).then((ok) => ok && onClose())}
          >
            {t('zur Übersicht')}
          </button>
        </div>
        {job.error && <Alert kind="error">{job.error}</Alert>}
      </div>

      {editable && (
        <div className="card card-wide">
          <h2>{t('2. Spalten zuordnen')}</h2>
          {targets.error && (
            <LoadError
              message={t(
                'Die Felder von HUBIplan konnten nicht geladen werden ({error}). Deine Zuordnung bleibt erhalten.',
                { error: targets.error },
              )}
              onRetry={() => void targets.reload()}
            />
          )}
          {templates.error && (
            <LoadError
              message={t('Die gespeicherten Vorlagen konnten nicht geladen werden ({error}).', {
                error: templates.error,
              })}
              onRetry={() => void templates.reload()}
            />
          )}
          {templates.data && templates.data.length > 0 && (
            <div className="chips">
              {templates.data.map((tmx) => (
                <button
                  key={tmx.id}
                  type="button"
                  className="chip"
                  onClick={() => {
                    setMapping(tmx.mapping)
                    setValueMapping(tmx.value_mapping)
                  }}
                >
                  {t('Vorlage:')} {tmx.name}
                </button>
              ))}
            </div>
          )}
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('Spalte in der Datei')}</th>
                  <th>{t('Beispielwerte')}</th>
                  <th>{t('Feld in HUBIplan')}</th>
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
                        aria-label={t('Feld für {h}', { h })}
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
                        <option value="">{t('– nicht importieren –')}</option>
                        {(targets.data ?? []).map((tmx) => (
                          <option
                            key={tmx.key}
                            value={tmx.key}
                            disabled={mappedTargets.has(tmx.key) && mapping[String(i)] !== tmx.key}
                          >
                            {tmx.label}
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
              aria-label={t('Name der Vorlage')}
              placeholder={t('Zuordnung als Vorlage speichern')}
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
            />
            <button
              type="button"
              className="button button-ghost"
              disabled={templateBusy || !templateName.trim()}
              onClick={() => void saveTemplate()}
            >
              {templateBusy ? t('Wird gespeichert …') : t('Vorlage speichern')}
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
          <h2>{t('4. Prüfen')}</h2>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={linkDuplicates}
              onChange={(e) => setLinkDuplicates(e.target.checked)}
            />
            <span>
              {terms.dv_has
                ? t('Gefundene Personen {dv_im} verknüpfen (Verbandsnummer bleibt erhalten)', {
                    dv_im: terms.dv_im,
                  })
                : t('Gefundene Personen verknüpfen')}
            </span>
          </label>
          <button
            type="button"
            className="button button-primary"
            disabled={busy}
            onClick={() => void validate()}
          >
            {busy ? t('Wird geprüft …') : t('Prüfen')}
          </button>
        </div>
      )}

      {stale && (
        <Alert kind="error">
          {t(
            'Zuordnung geändert – bitte erneut prüfen. Die Vorschau unten zeigt noch den alten Stand.',
          )}
        </Alert>
      )}

      {job.preview.length > 0 && <Preview job={job} />}

      {job.status === 'validated' && (
        <div className="card card-wide">
          <h2>{t('5. Importieren')}</h2>
          {stale && <p className="muted">{t('Erst nach erneutem Prüfen möglich.')}</p>}
          <p>
            {job.counts.ok} {t('Personen werden importiert')}
            {job.counts.errors
              ? t(', {errors} mit Fehlern nicht', { errors: job.counts.errors })
              : ''}
            .
          </p>
          <button
            type="button"
            className="button button-primary"
            disabled={busy || stale || !job.counts.ok}
            onClick={() => void startImport()}
          >
            {busy ? t('Wird importiert …') : t('Jetzt importieren')}
          </button>
        </div>
      )}

      {job.status === 'imported' && (
        <div className="card card-wide">
          <h2>{t('Ergebnis')}</h2>
          <p>
            {job.counts.imported} {t('Personen importiert')}
            {job.imported_at && t(' am {x}', { x: formatDateTime(job.imported_at) })}.
            {job.keep_until &&
              t(' Protokoll und „Rückgängig“ bleiben bis {x}.', {
                x: formatDateTime(job.keep_until),
              })}
          </p>
          {job.has_error_file && (
            <p>
              <a href={exchangeApi.errorFileUrl(orgId, job.id)}>{t('Fehlerliste herunterladen')}</a>{' '}
              {t('– zum Nachbearbeiten und erneuten Import.')}
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
                    title: t('Import vollständig rückgängig machen?'),
                    confirmLabel: t('Rückgängig machen'),
                  })
                ) {
                  void run(() => exchangeApi.undo(orgId, job.id))
                }
              }}
            >
              {t('Import rückgängig machen')}
            </button>
          ) : (
            <p className="muted small">
              {t('Rückgängig nicht mehr möglich:')} {job.undo_blockers.join(' ')}
            </p>
          )}
        </div>
      )}
      {job.status === 'undone' && (
        <Alert kind="info">{t('Dieser Import wurde rückgängig gemacht.')}</Alert>
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
  const mapped = new Set(Object.values(mapping).map((tmx) => tmx.replace(/_\d$/, '')))
  const needed = targets.filter((tmx) => tmx.value_mapped && mapped.has(tmx.key))
  const types = useLoad(() => memberApi.types(orgId), [orgId])
  const departments = useLoad(() => orgApi.departments(orgId), [orgId])
  const roles = useLoad(() => orgApi.roles(orgId).catch(() => []), [orgId])
  if (needed.length === 0) return null
  const choices: Record<string, { value: string; label: string }[]> = {
    member_type: (types.data ?? []).map((tmx) => ({ value: String(tmx.id), label: tmx.name })),
    departments: (departments.data ?? []).map((d) => ({
      value: String(d.id),
      label: unitName(d),
    })),
    exit_reason: EXIT_REASONS.map((r) => ({ ...r, label: fillTerms(r.label, tm) })),
    board_role: (roles.data ?? []).map((r) => ({ value: String(r.id), label: r.name })),
  }
  return (
    <div className="card card-wide">
      <h2>{t('3. Werte zuordnen')}</h2>
      <p className="muted small">
        {t('Bezeichnungen aus der Datei den Werten in HUBIplan zuordnen, z. B. „Akt.“ → „aktiv“.')}
      </p>
      {needed.map((tmx) => (
        <ValueTable
          key={tmx.key}
          orgId={orgId}
          jobId={job.id}
          target={tmx.key}
          label={tmx.key === 'departments' ? departmentLabel : tmx.label}
          choices={choices[tmx.key] ?? []}
          values={valueMapping[tmx.key] ?? {}}
          onChange={(raw, value) =>
            setValueMapping((vm) => ({
              ...vm,
              [tmx.key]: { ...(vm[tmx.key] ?? {}), [raw]: value },
            }))
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
                  aria-label={t('{label}: {v}', { label, v })}
                  value={values[v] ?? ''}
                  onChange={(e) => onChange(v, e.target.value)}
                >
                  <option value="">{t('– gleichnamig / unbekannt –')}</option>
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
      <h2>{t('Vorschau')}</h2>
      <p>
        {job.counts.persons} {t('Personen aus {rows} Zeilen ·', { rows: job.counts.rows })}{' '}
        <strong>{job.counts.ok} fehlerfrei</strong>{' '}
        {t('· {errors} mit Fehlern ·  {duplicates} schon', {
          errors: job.counts.errors,
          duplicates: job.counts.duplicates,
        })}{' '}
        {terms.dv_has ? `${terms.dv_im} ` : ''}vorhanden
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
        <span>{t('nur Fehler und Dubletten zeigen')}</span>
      </label>
      {problems.length > 0 && (
        <p>
          <button
            type="button"
            className="link-button"
            onClick={() =>
              downloadCsv(t('Pruefliste-{x}.csv', { x: job.file_name.replace(/\.[^.]+$/, '') }), [
                [t('Zeile'), t('Person'), t('Geburtsdatum'), t('Ergebnis')],
                ...problems.map((p) => [
                  p.rows.join(', '),
                  p.name,
                  p.birth_date ? formatDate(p.birth_date) : '',
                  p.messages.join(' '),
                ]),
              ])
            }
          >
            {t('Prüfliste herunterladen (CSV, {n} Einträge)', { n: problems.length })}
          </button>
        </p>
      )}
      {rows.length === 0 && <p className="muted">{t('Keine Einträge.')}</p>}
      <table className="table">
        <thead>
          <tr>
            <th>{t('Zeile')}</th>
            <th>{t('Person')}</th>
            <th>{t('Ergebnis')}</th>
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
        noun={t('Einträgen')}
      />
    </div>
  )
}
