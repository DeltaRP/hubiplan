// Finanzen › Veranstaltungen: Einnahmen und Ausgaben einer Veranstaltung bündeln,
// Termine verknüpfen und das Ergebnis auswerten; Reihen über mehrere Jahre vergleichen.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { euro, financeApi } from '../../api/finance.ts'
import type {
  Booking,
  Project,
  ProjectEvaluation,
  ProjectEvent,
  ProjectSeries,
  ProjectStatus,
} from '../../api/finance.ts'
import { orgApi, PERM, unitName } from '../../api/orgs.ts'
import { confirmDialog, promptDialog } from '../../components/dialog.ts'
import {
  errorMessage,
  formatDate,
  formatDateTime,
  useAutoSave,
  useForm,
  useLoad,
} from '../../components/forms.ts'
import { Alert, Field, LoadError, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'
import { berlin } from '../../components/calendar/time.ts'

const STATUS: { value: ProjectStatus; label: string }[] = [
  { value: 'planned', label: 'geplant' },
  { value: 'running', label: 'laufend' },
  { value: 'done', label: 'abgeschlossen' },
]

function period(starts: string, ends: string | null): string {
  return ends && ends !== starts
    ? `${formatDate(starts)} bis ${formatDate(ends)}`
    : formatDate(starts)
}

function Result({ value }: { value: string }) {
  const n = Number(value)
  return <span className={n < 0 ? 'amount-out' : n > 0 ? 'amount-in' : ''}>{euro(value)}</span>
}

/** Routen unter /finanzen/veranstaltungen */
export function ProjectsArea() {
  return (
    <Routes>
      <Route index element={<ProjectList />} />
      <Route path="reihen" element={<SeriesPage />} />
      <Route path=":id" element={<ProjectDetail />} />
      <Route path="*" element={<Navigate to="/finanzen/veranstaltungen" replace />} />
    </Routes>
  )
}

function ProjectList() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.financeEdit)
  const navigate = useNavigate()
  const [status, setStatus] = useState('')
  const [reihe, setReihe] = useState('')
  const [creating, setCreating] = useState(false)
  const list = useLoad(
    () => financeApi.projects(org.id, { status, reihe }),
    [org.id, status, reihe],
  )
  const series = useLoad(() => financeApi.series(org.id), [org.id])

  if (list.error) return <Alert kind="error">{list.error}</Alert>
  return (
    <div className="stack">
      {canEdit && !creating && (
        <div className="button-row">
          <button type="button" className="button button-primary" onClick={() => setCreating(true)}>
            Neue Veranstaltung
          </button>
        </div>
      )}
      {creating && (
        <ProjectForm
          project={null}
          series={series.data ?? []}
          onSeriesAdded={() => void series.reload()}
          onSaved={(p) => navigate(`/finanzen/veranstaltungen/${p.id}`)}
          onClose={() => setCreating(false)}
        />
      )}
      <div className="card card-wide filters">
        <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">alle Status</option>
          {STATUS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        {(series.data?.length ?? 0) > 0 && (
          <select aria-label="Reihe" value={reihe} onChange={(e) => setReihe(e.target.value)}>
            <option value="">alle Reihen</option>
            {series.data!.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        )}
      </div>
      <div className="card card-wide">
        {!list.data ? (
          <p className="muted">Lädt …</p>
        ) : list.data.length === 0 ? (
          <div className="empty-state">
            <p>Noch keine Veranstaltung.</p>
            <p className="muted small">
              Lege zum Beispiel das Schützenfest als Veranstaltung an und ordne ihm im Kassenbuch
              Einnahmen und Ausgaben zu. Die Buchungen bleiben ganz normal im Kassenbuch.
            </p>
          </div>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Veranstaltung</th>
                  <th>Zeitraum</th>
                  <th className="num">Einnahmen</th>
                  <th className="num">Ausgaben</th>
                  <th className="num">Ergebnis</th>
                </tr>
              </thead>
              <tbody>
                {list.data.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link to={`/finanzen/veranstaltungen/${p.id}`}>{p.name}</Link>
                      <div className="muted small">
                        {[p.status_label, p.series_name, p.department_name]
                          .filter(Boolean)
                          .join(' · ')}
                      </div>
                    </td>
                    <td>{period(p.starts_on, p.ends_on)}</td>
                    <td className="num">{euro(p.income)}</td>
                    <td className="num">{euro(p.expense)}</td>
                    <td className="num">
                      <strong>
                        <Result value={p.result} />
                      </strong>
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

function ProjectForm({
  project,
  series,
  onSeriesAdded,
  onSaved,
  onClose,
}: {
  project: Project | ProjectEvaluation | null
  series: ProjectSeries[]
  onSeriesAdded: () => void
  onSaved: (p: Project, done: boolean) => void
  onClose: () => void
}) {
  const org = useActiveOrg()
  const tm = useTerms()
  const departments = useLoad(
    () => (org.type === 'club' ? orgApi.departments(org.id) : Promise.resolve([])),
    [org.id, org.type],
  )
  const [extraSeries, setExtraSeries] = useState<ProjectSeries[]>([])
  const allSeries = [...series, ...extraSeries.filter((x) => !series.some((s) => s.id === x.id))]
  const form = useForm({
    name: project?.name ?? '',
    starts_on: project?.starts_on ?? '',
    ends_on: project?.ends_on ?? '',
    status: project?.status ?? 'planned',
    series: String(project?.series ?? ''),
    department: String(project && 'department' in project ? (project.department ?? '') : ''),
    description: project?.description ?? '',
  })
  const { values: v, errors, set } = form

  async function addSeries() {
    const name = await promptDialog({
      title: 'Neue Reihe',
      message: 'Eine Reihe fasst wiederkehrende Veranstaltungen zusammen, z. B. „Schützenfest“.',
      label: 'Name der Reihe',
      confirmLabel: 'Anlegen',
      danger: false,
    })
    if (!name?.trim()) return
    try {
      const s = await financeApi.createSeries(org.id, name.trim())
      setExtraSeries((prev) => [...prev, s])
      set('series', String(s.id))
      onSeriesAdded()
    } catch (err) {
      form.setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  function payloadOf(x: typeof v) {
    return {
      name: x.name,
      starts_on: x.starts_on,
      ends_on: x.ends_on || null,
      status: x.status,
      series: x.series ? Number(x.series) : null,
      department: x.department ? Number(x.department) : null,
      description: x.description,
    }
  }

  // Bestehende Veranstaltungen speichern automatisch, neue erst mit „Anlegen“
  const auto = useAutoSave(
    form,
    (_changes, values) => financeApi.updateProject(org.id, project!.id, payloadOf(values)),
    { enabled: project !== null, onSaved: (saved) => onSaved(saved as Project, false) },
  )

  async function save(e: FormEvent) {
    e.preventDefault()
    if (project) {
      if (!(await auto.flush())) return
      onClose()
      return
    }
    const saved = await form.submit(() => financeApi.createProject(org.id, payloadOf(v)))
    if (saved) onSaved(saved as Project, true)
  }

  return (
    <div className="card card-wide">
      <form onSubmit={save}>
        <div className="card-head">
          <h2>{project ? 'Veranstaltung bearbeiten' : 'Neue Veranstaltung'}</h2>
          {project && <SaveStatus auto={auto} />}
          <button
            type="button"
            className="button button-ghost push-right"
            onClick={() =>
              void (project ? auto.flush() : Promise.resolve(true)).then((ok) => ok && onClose())
            }
          >
            {project ? 'Schließen' : 'Abbrechen'}
          </button>
        </div>
        <fieldset disabled={!project && form.busy}>
          <div className="grid-3">
            <Field
              label="Name"
              required
              placeholder="z. B. Schützenfest 2026"
              value={v.name}
              error={errors.name}
              onChange={(e) => set('name', e.target.value)}
            />
            <Field
              label="Beginn"
              type="date"
              required
              value={v.starts_on}
              error={errors.starts_on}
              onChange={(e) => set('starts_on', e.target.value)}
            />
            <Field
              label="Ende (optional)"
              type="date"
              value={v.ends_on}
              error={errors.ends_on}
              onChange={(e) => set('ends_on', e.target.value)}
            />
            <SelectField
              label="Status"
              value={v.status}
              error={errors.status}
              onChange={(e) => set('status', e.target.value as ProjectStatus)}
            >
              {STATUS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </SelectField>
            <SelectField
              label="Reihe (optional)"
              value={v.series}
              error={errors.series}
              hint="Für den Vergleich über die Jahre"
              onChange={(e) => {
                if (e.target.value === '+') void addSeries()
                else set('series', e.target.value)
              }}
            >
              <option value="">keine</option>
              {allSeries.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
              <option value="+">+ neue Reihe …</option>
            </SelectField>
            {(departments.data?.length ?? 0) > 0 && (
              <SelectField
                label={`${tm.sg} (optional)`}
                value={v.department}
                error={errors.department}
                onChange={(e) => set('department', e.target.value)}
              >
                <option value="">keine</option>
                {departments.data!.map((d) => (
                  <option key={d.id} value={d.id}>
                    {unitName(d)}
                  </option>
                ))}
              </SelectField>
            )}
          </div>
          <label className="field">
            <span>Beschreibung (optional)</span>
            <textarea
              rows={3}
              value={v.description}
              onChange={(e) => set('description', e.target.value)}
            />
          </label>
        </fieldset>
        {form.message?.kind === 'error' && <Alert kind="error">{form.message.text}</Alert>}
        {!project && (
          <div className="button-row">
            <button type="submit" className="button button-primary" disabled={form.busy}>
              Anlegen
            </button>
          </div>
        )}
      </form>
    </div>
  )
}

function ProjectDetail() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.financeEdit)
  const navigate = useNavigate()
  const id = Number(useParams().id)
  const ev = useLoad(() => financeApi.projectEvaluation(org.id, id), [org.id, id])
  const series = useLoad(() => financeApi.series(org.id), [org.id])
  const project = useLoad(
    () => financeApi.projects(org.id).then((all) => all.find((p) => p.id === id) ?? null),
    [org.id, id],
  )
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (ev.error) return <Alert kind="error">{ev.error}</Alert>
  if (!ev.data) return <p className="muted">Lädt …</p>
  const d = ev.data
  const reload = () => {
    void ev.reload()
    void project.reload()
  }

  async function remove() {
    if (
      !(await confirmDialog({
        title: `„${d.name}“ löschen?`,
        message:
          'Verknüpfte Termine bleiben im Kalender. Zugeordnete Buchungen müssen vorher gelöst werden.',
        confirmLabel: 'Löschen',
      }))
    )
      return
    try {
      await financeApi.deleteProject(org.id, d.id)
      navigate('/finanzen/veranstaltungen')
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function unassign(bookingId: number) {
    try {
      await financeApi.unassignBookings(org.id, d.id, [bookingId])
      reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const tm = d.totals
  return (
    <div className="stack">
      <p className="small">
        <Link to="/finanzen/veranstaltungen">← alle Veranstaltungen</Link>
      </p>
      <div className="card card-wide">
        <div className="card-head">
          <div>
            <h2>{d.name}</h2>
            <p className="muted small">
              {[
                period(d.starts_on, d.ends_on),
                d.status_label,
                d.department_name,
                d.series_name ? `Reihe ${d.series_name}` : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
          </div>
          <div className="button-row push-right">
            <a
              className="button button-ghost"
              href={financeApi.projectReportUrl(org.id, d.id, 'pdf')}
              target="_blank"
              rel="noreferrer"
            >
              PDF
            </a>
            <a
              className="button button-ghost"
              href={financeApi.projectReportUrl(org.id, d.id, 'xlsx')}
            >
              Excel
            </a>
            {canEdit && (
              <button
                type="button"
                className="button button-ghost"
                onClick={() => setEditing(true)}
              >
                Bearbeiten
              </button>
            )}
            {canEdit && (
              <button type="button" className="button button-danger" onClick={() => void remove()}>
                Löschen
              </button>
            )}
          </div>
        </div>
        {d.description && <p>{d.description}</p>}
        {error && <Alert kind="error">{error}</Alert>}
      </div>

      {editing && project.data && (
        <ProjectForm
          project={project.data}
          series={series.data ?? []}
          onSeriesAdded={() => void series.reload()}
          onSaved={(_p, done) => {
            if (done) setEditing(false)
            reload()
          }}
          onClose={() => {
            setEditing(false)
            reload()
          }}
        />
      )}

      <div className="tiles tiles-figures">
        <div className="card tile">
          <h2>Einnahmen</h2>
          <p className="amount-big amount-in">{euro(tm.income)}</p>
        </div>
        <div className="card tile">
          <h2>Ausgaben</h2>
          <p className="amount-big amount-out">{euro(tm.expense)}</p>
        </div>
        <div className="card tile">
          <h2>{Number(tm.result) < 0 ? 'Fehlbetrag' : 'Überschuss'}</h2>
          <p className={`amount-big ${Number(tm.result) < 0 ? 'amount-out' : 'amount-in'}`}>
            {euro(tm.result)}
          </p>
          <span className="muted small">{d.booking_count} Buchungen</span>
        </div>
      </div>
      {d.open_invoices.count > 0 && (
        <Alert kind="info">
          Noch offen:{' '}
          {d.open_invoices.count === 1 ? 'eine Rechnung' : `${d.open_invoices.count} Rechnungen`}{' '}
          über {euro(d.open_invoices.outstanding)}. Sie zählen erst mit dem Zahlungseingang.{' '}
          <Link to={`/finanzen/rechnungen?veranstaltung=${d.id}`}>Ansehen</Link>
        </Alert>
      )}

      <div className="card card-wide">
        <h2>Nach Kategorie</h2>
        {d.categories.length === 0 ? (
          <p className="muted">Noch keine Einnahmen oder Ausgaben zugeordnet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Kategorie</th>
                <th className="num">Einnahmen</th>
                <th className="num">Ausgaben</th>
                <th className="num">Saldo</th>
              </tr>
            </thead>
            <tbody>
              {d.categories.map((c) => (
                <tr key={c.id ?? 0}>
                  <td>{c.name}</td>
                  <td className="num">{euro(c.income)}</td>
                  <td className="num">{euro(c.expense)}</td>
                  <td className="num">
                    <Result value={c.result} />
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th>Summe</th>
                <th className="num">{euro(tm.income)}</th>
                <th className="num">{euro(tm.expense)}</th>
                <th className="num">
                  <Result value={tm.result} />
                </th>
              </tr>
            </tfoot>
          </table>
        )}
      </div>

      {d.tax_areas_enabled && d.tax_areas.length > 0 && (
        <div className="card card-wide">
          <h2>Nach steuerlichem Bereich</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Bereich</th>
                <th className="num">Einnahmen</th>
                <th className="num">Ausgaben</th>
                <th className="num">Ergebnis</th>
              </tr>
            </thead>
            <tbody>
              {d.tax_areas.map((a) => (
                <tr key={a.area || 'ohne'}>
                  <td>{a.label}</td>
                  <td className="num">{euro(a.income)}</td>
                  <td className="num">{euro(a.expense)}</td>
                  <td className="num">
                    <Result value={a.result} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card card-wide">
        <div className="card-head">
          <h2>Buchungen</h2>
          <Link
            className="small push-right"
            to={`/finanzen/kassenbuch?veranstaltung=${d.id}&jahr=alle`}
          >
            im Kassenbuch ansehen
          </Link>
        </div>
        {d.bookings.length === 0 ? (
          <p className="muted small">
            Noch keine Buchung. Im Kassenbuch kannst du bei jeder Einnahme oder Ausgabe die
            Veranstaltung wählen, oder du ordnest hier vorhandene Buchungen zu.
          </p>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Nr.</th>
                  <th>Datum</th>
                  <th>Text</th>
                  <th>Kategorie</th>
                  <th className="num">Betrag</th>
                  {canEdit && <th />}
                </tr>
              </thead>
              <tbody>
                {d.bookings.map((b) => (
                  <tr key={b.id}>
                    <td>{b.display_number}</td>
                    <td>{formatDate(b.date)}</td>
                    <td>
                      {b.text}
                      <div className="muted small">
                        {[
                          b.reference,
                          b.account_name,
                          b.receipt_count ? `📎 ${b.receipt_count}` : '',
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      </div>
                    </td>
                    <td>{b.category_name}</td>
                    <td className={`num ${b.kind === 'expense' ? 'amount-out' : 'amount-in'}`}>
                      {euro(b.kind === 'expense' ? -Number(b.amount) : Number(b.amount))}
                    </td>
                    {canEdit && (
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => void unassign(b.id)}
                        >
                          Zuordnung lösen
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {canEdit && <AssignBookings project={d} onDone={reload} />}
      </div>

      <EventsCard project={d} canEdit={canEdit} onChange={(data) => ev.setData(data)} />
    </div>
  )
}

function shiftDays(date: string, days: number): string {
  const d = new Date(`${date}T12:00:00`)
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

/** Vorhandene Buchungen ohne Veranstaltung rund um den Zeitraum zuordnen. */
function AssignBookings({ project, onDone }: { project: ProjectEvaluation; onDone: () => void }) {
  const org = useActiveOrg()
  const [open, setOpen] = useState(false)
  const [von, setVon] = useState(shiftDays(project.starts_on, -30))
  const [bis, setBis] = useState(shiftDays(project.ends_on ?? project.starts_on, 30))
  const [suche, setSuche] = useState('')
  // Sammeln über Filter hinweg bleibt möglich, die Auswahl ist aber immer sichtbar
  // (UI-Audit NAF-05)
  const [picked, setPicked] = useState<Map<number, Booking>>(new Map())
  const [error, setError] = useState<string | null>(null)
  const candidates = useLoad(
    () =>
      open
        ? financeApi.bookings(org.id, {
            veranstaltung: '-',
            von,
            bis,
            suche,
            page_size: 200,
          })
        : Promise.resolve(null),
    [org.id, open, von, bis, suche],
  )

  if (!open)
    return (
      <div className="button-row">
        <button type="button" className="button button-ghost" onClick={() => setOpen(true)}>
          Vorhandene Buchungen zuordnen
        </button>
      </div>
    )

  const rows = (candidates.data?.results ?? []).filter((b: Booking) => b.kind !== 'transfer')
  const visible = new Set(rows.map((b) => b.id))
  const outside = [...picked.keys()].filter((id) => !visible.has(id)).length
  function toggle(b: Booking) {
    setPicked((prev) => {
      const next = new Map(prev)
      if (next.has(b.id)) next.delete(b.id)
      else next.set(b.id, b)
      return next
    })
  }
  function cancel() {
    setPicked(new Map())
    setError(null)
    setOpen(false)
  }
  async function assign() {
    try {
      await financeApi.assignBookings(org.id, project.id, [...picked.keys()])
      setPicked(new Map())
      setOpen(false)
      onDone()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="subcard">
      <h3>Buchungen ohne Veranstaltung</h3>
      <div className="filters">
        <Field label="von" type="date" value={von} onChange={(e) => setVon(e.target.value)} />
        <Field label="bis" type="date" value={bis} onChange={(e) => setBis(e.target.value)} />
        <Field
          label="Suche"
          type="search"
          value={suche}
          placeholder="Text, Beleg, Betrag"
          onChange={(e) => setSuche(e.target.value)}
        />
      </div>
      {candidates.error && (
        <LoadError message={candidates.error} onRetry={() => void candidates.reload()} />
      )}
      {candidates.data && candidates.data.count > candidates.data.results.length && (
        <Alert kind="info">
          Gezeigt werden die ersten {candidates.data.results.length} von {candidates.data.count}{' '}
          Buchungen. Bitte Zeitraum oder Suche eingrenzen.
        </Alert>
      )}
      {!candidates.data ? (
        !candidates.error && <p className="muted">Lädt …</p>
      ) : rows.length === 0 ? (
        <p className="muted small">Keine passenden Buchungen in diesem Zeitraum.</p>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <tbody>
              {rows.map((b) => (
                <tr key={b.id}>
                  <td>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={picked.has(b.id)}
                        onChange={() => toggle(b)}
                        aria-label={`Buchung ${b.display_number} zuordnen`}
                      />
                      <span>{b.display_number}</span>
                    </label>
                  </td>
                  <td>{formatDate(b.date)}</td>
                  <td>{b.text}</td>
                  <td>{b.category_name}</td>
                  <td className={`num ${b.kind === 'expense' ? 'amount-out' : 'amount-in'}`}>
                    {euro(b.kind === 'expense' ? -Number(b.amount) : Number(b.amount))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {picked.size > 0 && (
        <div className="subcard stack-sm" aria-live="polite">
          <p className="small">
            <strong>{picked.size} ausgewählt</strong>
            {outside > 0 && `, davon ${outside} außerhalb des Filters`}
          </p>
          <ul className="plain-list small">
            {[...picked.values()].map((b) => (
              <li key={b.id}>
                {b.display_number} · {formatDate(b.date)} · {b.text} ·{' '}
                {euro(b.kind === 'expense' ? -Number(b.amount) : Number(b.amount))}{' '}
                <button type="button" className="link-button" onClick={() => toggle(b)}>
                  entfernen
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className="link-button" onClick={() => setPicked(new Map())}>
            Auswahl leeren
          </button>
        </div>
      )}
      {error && <Alert kind="error">{error}</Alert>}
      <div className="button-row">
        <button
          type="button"
          className="button button-primary"
          disabled={picked.size === 0}
          onClick={() => void assign()}
        >
          {picked.size === 1 ? '1 Buchung zuordnen' : `${picked.size} Buchungen zuordnen`}
        </button>
        <button type="button" className="button button-ghost" onClick={cancel}>
          Abbrechen
        </button>
      </div>
    </div>
  )
}

function eventWhen(e: ProjectEvent): string {
  const when = e.all_day ? formatDate(e.starts_at) : formatDateTime(e.starts_at)
  return e.is_series ? `${when} (Serie)` : when
}

/** Termine im Kalender, die zur Veranstaltung gehören. */
function EventsCard({
  project,
  canEdit,
  onChange,
}: {
  project: ProjectEvaluation
  canEdit: boolean
  onChange: (data: ProjectEvaluation) => void
}) {
  const org = useActiveOrg()
  const calendar = org.modules.includes('events')
  const [open, setOpen] = useState(false)
  const [suche, setSuche] = useState('')
  const [error, setError] = useState<string | null>(null)
  const candidates = useLoad(
    () => (open ? financeApi.eventCandidates(org.id, project.id, suche) : Promise.resolve(null)),
    [org.id, project.id, open, suche],
  )
  if (!calendar && project.events.length === 0) return null

  async function change(data: { events?: number[]; unlink?: number[] }) {
    try {
      onChange(await financeApi.linkEvents(org.id, project.id, data))
      void candidates.reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const free = (candidates.data ?? []).filter((e) => !e.linked)
  return (
    <div className="card card-wide">
      <h2>Termine im Kalender</h2>
      {project.events.length === 0 ? (
        <p className="muted small">
          Kein Termin verknüpft. Die Veranstaltung erscheint nur im Kalender, wenn du Termine
          verknüpfst.
        </p>
      ) : (
        <ul className="plain-list">
          {project.events.map((e) => (
            <li key={e.id}>
              <Link to={`/termine?termin=${e.id}&datum=${berlin(e.starts_at).date}`}>
                {e.title}
              </Link>{' '}
              <span className="muted small">
                {eventWhen(e)}
                {e.is_cancelled ? ' · abgesagt' : ''}
              </span>
              {canEdit && (
                <button
                  type="button"
                  className="link-button"
                  onClick={() => void change({ unlink: [e.id] })}
                >
                  lösen
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {error && <Alert kind="error">{error}</Alert>}
      {canEdit && calendar && !open && (
        <div className="button-row">
          <button type="button" className="button button-ghost" onClick={() => setOpen(true)}>
            Termin verknüpfen
          </button>
        </div>
      )}
      {canEdit && open && (
        <div className="subcard">
          <h3>Termin verknüpfen</h3>
          <Field
            label="Suche"
            type="search"
            value={suche}
            placeholder="Titel des Termins (ohne Suche: Termine rund um den Zeitraum)"
            onChange={(e) => setSuche(e.target.value)}
          />
          {candidates.error ? (
            <LoadError message={candidates.error} onRetry={() => void candidates.reload()} />
          ) : !candidates.data ? (
            <p className="muted">Lädt …</p>
          ) : free.length === 0 ? (
            <p className="muted small">
              Keine passenden Termine. Neue Termine legst du im <Link to="/termine">Kalender</Link>{' '}
              an.
            </p>
          ) : (
            <ul className="plain-list">
              {free.map((e) => (
                <li key={e.id}>
                  {e.title} <span className="muted small">{eventWhen(e)}</span>{' '}
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => void change({ events: [e.id] })}
                  >
                    verknüpfen
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="button-row">
            <button type="button" className="button button-ghost" onClick={() => setOpen(false)}>
              Schließen
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/** Reihen: anlegen, umbenennen, löschen und die Jahre vergleichen. */
function SeriesPage() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.financeEdit)
  const list = useLoad(() => financeApi.series(org.id), [org.id])
  const [selected, setSelected] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const current = selected ?? list.data?.[0]?.id ?? null
  const comparison = useLoad(
    () => (current ? financeApi.seriesComparison(org.id, current) : Promise.resolve(null)),
    [org.id, current],
  )

  async function create() {
    const name = await promptDialog({
      title: 'Neue Reihe',
      message: 'z. B. „Schützenfest“ – danach die Veranstaltungen der einzelnen Jahre zuordnen.',
      label: 'Name',
      confirmLabel: 'Anlegen',
      danger: false,
    })
    if (!name?.trim()) return
    try {
      const s = await financeApi.createSeries(org.id, name.trim())
      await list.reload()
      setSelected(s.id)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function rename(s: ProjectSeries) {
    const name = await promptDialog({
      title: 'Reihe umbenennen',
      label: 'Name',
      defaultValue: s.name,
      confirmLabel: 'Speichern',
      danger: false,
    })
    if (!name?.trim() || name.trim() === s.name) return
    try {
      await financeApi.updateSeries(org.id, s.id, name.trim())
      await list.reload()
      void comparison.reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function remove(s: ProjectSeries) {
    if (
      !(await confirmDialog({
        title: `Reihe „${s.name}“ löschen?`,
        message: 'Die Veranstaltungen und ihre Buchungen bleiben erhalten.',
        confirmLabel: 'Löschen',
      }))
    )
      return
    try {
      await financeApi.deleteSeries(org.id, s.id)
      setSelected(null)
      await list.reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  if (list.error) return <Alert kind="error">{list.error}</Alert>
  if (!list.data) return <p className="muted">Lädt …</p>
  const sel = list.data.find((s) => s.id === current) ?? null
  const c = comparison.data
  return (
    <div className="stack">
      {error && <Alert kind="error">{error}</Alert>}
      <div className="card card-wide filters">
        {list.data.length > 0 && (
          <select
            aria-label="Reihe"
            value={current ?? ''}
            onChange={(e) => setSelected(Number(e.target.value))}
          >
            {list.data.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.project_count})
              </option>
            ))}
          </select>
        )}
        {sel && (
          <>
            <a
              className="button button-ghost"
              href={financeApi.seriesReportUrl(org.id, sel.id, 'pdf')}
              target="_blank"
              rel="noreferrer"
            >
              PDF
            </a>
            <a
              className="button button-ghost"
              href={financeApi.seriesReportUrl(org.id, sel.id, 'xlsx')}
            >
              Excel
            </a>
          </>
        )}
        {canEdit && sel && (
          <>
            <button type="button" className="button button-ghost" onClick={() => void rename(sel)}>
              Umbenennen
            </button>
            <button type="button" className="button button-ghost" onClick={() => void remove(sel)}>
              Löschen
            </button>
          </>
        )}
        {canEdit && (
          <button
            type="button"
            className="button button-primary push-right"
            onClick={() => void create()}
          >
            Neue Reihe
          </button>
        )}
      </div>
      {list.data.length === 0 ? (
        <div className="card empty-state">
          <p>Noch keine Reihe.</p>
          <p className="muted small">
            Mit einer Reihe vergleichst du wiederkehrende Veranstaltungen, z. B. das Schützenfest
            über mehrere Jahre.
          </p>
        </div>
      ) : !c ? (
        <p className="muted">Lädt …</p>
      ) : c.projects.length === 0 ? (
        <div className="card empty-state">
          <p>Zu dieser Reihe gehört noch keine Veranstaltung.</p>
          <p className="muted small">Wähle die Reihe beim Bearbeiten einer Veranstaltung.</p>
        </div>
      ) : (
        <div className="card card-wide">
          <h2>Vergleich {c.name}</h2>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Kategorie (Saldo)</th>
                  {c.projects.map((p) => (
                    <th key={p.id} className="num">
                      <Link to={`/finanzen/veranstaltungen/${p.id}`}>{p.name}</Link>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {c.categories.map((cat) => (
                  <tr key={cat.id ?? 0}>
                    <td>{cat.name}</td>
                    {cat.values.map((v, i) => (
                      <td key={c.projects[i].id} className="num">
                        <Result value={v.result} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th>Einnahmen</th>
                  {c.projects.map((p) => (
                    <th key={p.id} className="num">
                      {euro(p.income)}
                    </th>
                  ))}
                </tr>
                <tr>
                  <th>Ausgaben</th>
                  {c.projects.map((p) => (
                    <th key={p.id} className="num">
                      {euro(p.expense)}
                    </th>
                  ))}
                </tr>
                <tr>
                  <th>Ergebnis</th>
                  {c.projects.map((p) => (
                    <th key={p.id} className="num">
                      <Result value={p.result} />
                    </th>
                  ))}
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
