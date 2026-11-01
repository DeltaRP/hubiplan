import { useState } from 'react'
import { exchangeApi, waitFor } from '../api/exchange.ts'
import type { ExportJob } from '../api/exchange.ts'
import { errorMessage, formatDate, useLoad, useUnmountSignal } from './forms.ts'
import { Alert } from './ui.tsx'

/** Export der aktuell gefilterten Liste als Excel oder PDF. */
export function ExportPanel({
  orgId,
  kind,
  filters,
  onClose,
}: {
  orgId: number
  kind: 'members' | 'jubilees' | 'federation_members'
  filters: Record<string, unknown>
  onClose: () => void
}) {
  const columns = useLoad(() => exchangeApi.columns(orgId), [orgId])
  const templates = useLoad(() => exchangeApi.exportTemplates(orgId), [orgId])
  const [selected, setSelected] = useState<string[] | null>(null)
  const [format, setFormat] = useState<'xlsx' | 'pdf'>('xlsx')
  const [orientation, setOrientation] = useState<'portrait' | 'landscape'>('portrait')
  const [templateName, setTemplateName] = useState('')
  const [job, setJob] = useState<ExportJob | null>(null)
  const signal = useUnmountSignal()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const options =
    (columns.data as Record<string, { key: string; label: string }[]> | null)?.[kind] ?? []
  const chosen = selected ?? options.slice(0, kind === 'members' ? 5 : 6).map((c) => c.key)
  const ownTemplates = templates.data?.filter((tm) => tm.kind === kind) ?? []

  function toggle(key: string, on: boolean) {
    setSelected(on ? [...chosen, key] : chosen.filter((k) => k !== key))
  }

  async function start() {
    setBusy(true)
    setError(null)
    setJob(null)
    try {
      const created = await exchangeApi.startExport(orgId, {
        kind,
        file_format: format,
        orientation,
        columns: chosen,
        filters,
      })
      setJob(
        await waitFor(
          () => exchangeApi.exportJob(orgId, created.id),
          ['pending', 'running'],
          undefined,
          signal(),
        ),
      )
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function saveTemplate() {
    if (!templateName.trim()) return
    try {
      await exchangeApi.saveExportTemplate(orgId, {
        name: templateName.trim(),
        kind,
        columns: chosen,
        file_format: format,
        orientation,
      })
      setTemplateName('')
      await templates.reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="card card-wide export-panel">
      <div className="card-head">
        <h2>Exportieren</h2>
        <button type="button" className="link-button push-right" onClick={onClose}>
          schließen
        </button>
      </div>
      <p className="muted small">Exportiert wird die aktuell gefilterte und sortierte Liste.</p>
      {ownTemplates.length > 0 && (
        <div className="chips">
          {ownTemplates.map((tm) => (
            <button
              key={tm.id}
              type="button"
              className="chip"
              onClick={() => {
                setSelected(tm.columns)
                setFormat(tm.file_format as 'xlsx' | 'pdf')
                setOrientation(tm.orientation as 'portrait' | 'landscape')
              }}
            >
              {tm.name}
            </button>
          ))}
        </div>
      )}
      <fieldset className="column-picker">
        <legend className="small">Spalten</legend>
        {options.map((c) => (
          <label key={c.key} className="checkbox">
            <input
              type="checkbox"
              checked={chosen.includes(c.key)}
              onChange={(e) => toggle(c.key, e.target.checked)}
            />
            <span>{c.label}</span>
          </label>
        ))}
      </fieldset>
      <div className="filters">
        <select
          aria-label="Format"
          value={format}
          onChange={(e) => setFormat(e.target.value as 'xlsx' | 'pdf')}
        >
          <option value="xlsx">Excel</option>
          <option value="pdf">PDF</option>
        </select>
        {format === 'pdf' && (
          <select
            aria-label="Ausrichtung"
            value={orientation}
            onChange={(e) => setOrientation(e.target.value as 'portrait' | 'landscape')}
          >
            <option value="portrait">Hochformat</option>
            <option value="landscape">Querformat</option>
          </select>
        )}
        <button
          type="button"
          className="button button-primary"
          disabled={busy || chosen.length === 0}
          onClick={() => void start()}
        >
          {busy ? 'Wird erstellt …' : 'Export erstellen'}
        </button>
      </div>
      <div className="inline-add">
        <input
          aria-label="Name der Vorlage"
          placeholder="Als Vorlage speichern, z. B. Geburtstagsliste"
          value={templateName}
          onChange={(e) => setTemplateName(e.target.value)}
        />
        <button type="button" className="button button-ghost" onClick={() => void saveTemplate()}>
          Vorlage speichern
        </button>
      </div>
      {error && <Alert kind="error">{error}</Alert>}
      {job?.status === 'done' && (
        <Alert kind="success">
          Fertig: {job.row_count} Einträge.{' '}
          <a href={exchangeApi.downloadUrl(orgId, job.id)}>{job.file_name} herunterladen</a>
          {job.keep_until && ` (bis ${formatDate(job.keep_until.slice(0, 10))}, danach gelöscht)`}
        </Alert>
      )}
      {job?.status === 'failed' && <Alert kind="error">Export fehlgeschlagen: {job.error}</Alert>}
      {job && ['pending', 'running'].includes(job.status) && (
        <Alert kind="info">Der Export läuft noch im Hintergrund. Bitte später erneut öffnen.</Alert>
      )}
    </div>
  )
}
