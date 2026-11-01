// Meldungen Schritt 3: Ausschreibung an die eigenen Untereinheiten. Der Veranstalter sieht
// den Eingang je Untereinheit, bestätigt, fragt nach und erinnert; die Untereinheiten melden
// in ihrem Bereich (Abteilungsrecht „dept.entries.submit“).
import { useState } from 'react'
import { Link, Route, Routes, useParams } from 'react-router-dom'
import {
  deptScope,
  entriesApi,
  unitScope,
  type Call,
  type CallDetail,
  type EntryOptions,
  type UnitRow,
} from '../../api/entries.ts'
import { DataTable } from '../../components/DataTable.tsx'
import { errorMessage, formatDate, formatDateTime, useLoad } from '../../components/forms.ts'
import { Alert, LoadError } from '../../components/ui.tsx'
import { EntryPanel } from './EntriesPage.tsx'

/** Eingang des Veranstalters: je angeschriebene Untereinheit der Stand der Meldung. */
export function UnitsPanel({ org, call }: { org: number; call: CallDetail }) {
  const rows = useLoad(() => entriesApi.units(org, call.id), [org, call.id])
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  if (rows.error) return <LoadError message={rows.error} onRetry={rows.reload} />
  if (!rows.data) return <p className="muted">Wird geladen …</p>
  const open = rows.data.filter((r) => r.status !== 'abgegeben' && r.status !== 'bestaetigt')

  async function remind() {
    setBusy(true)
    try {
      const res = await entriesApi.remind(org, call.id)
      const parts = []
      if (res.reminded.length) parts.push(`Erinnert: ${res.reminded.join(', ')}.`)
      if (res.without_contact.length)
        parts.push(`Ohne Ansprechperson mit Zugang: ${res.without_contact.join(', ')}.`)
      setMessage({ kind: 'success', text: parts.join(' ') || 'Niemand zu erinnern.' })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="card card-wide">
        <p className="muted">
          {rows.data.length - open.length} von {rows.data.length} Untereinheiten haben gemeldet.
          {call.deadline ? ` Meldeschluss ${formatDate(call.deadline)}.` : ''} Ihr könnt jede
          Meldung auch selbst eintragen, etwa für Untereinheiten ohne eigenen Zugang.
        </p>
        <div className="button-row">
          {open.length > 0 && (
            <button type="button" className="button button-ghost" disabled={busy} onClick={remind}>
              Fehlende erinnern (Mail)
            </button>
          )}
          <a className="button button-ghost" href={entriesApi.unitsListUrl(org, call.id, 'xlsx')}>
            Meldeliste (Excel)
          </a>
          <a className="button button-ghost" href={entriesApi.unitsListUrl(org, call.id, 'csv')}>
            CSV
          </a>
        </div>
        {message && <Alert kind={message.kind}>{message.text}</Alert>}
      </div>
      <DataTable<UnitRow>
        label="Eingang"
        rows={rows.data}
        rowKey={(r) => r.unit}
        emptyText="Keine Untereinheit angeschrieben."
        columns={[
          {
            key: 'name',
            label: 'Untereinheit',
            value: (r) => r.name,
            render: (r) => <Link to={`einheit/${r.unit}`}>{r.name}</Link>,
          },
          {
            key: 'status',
            label: 'Meldung',
            value: (r) => r.status_label,
            render: (r) => (
              <>
                {r.status_label}
                {r.changed && r.status !== 'entwurf' ? ', geändert' : ''}
                {r.hints > 0 && <span className="muted small"> · {r.hints} Hinweise</span>}
              </>
            ),
            filter: true,
          },
          { key: 'teams', label: 'Mannschaften', value: (r) => r.teams },
          { key: 'persons', label: 'Personen', value: (r) => r.persons },
          {
            key: 'submitted_at',
            label: 'Zuletzt abgegeben',
            value: (r) => r.submitted_at ?? '',
            render: (r) => (r.submitted_at ? formatDateTime(r.submitted_at) : '—'),
            optional: true,
          },
          {
            key: 'contacts',
            label: 'Ansprechpersonen',
            value: (r) => r.contacts,
            render: (r) => (r.contacts ? r.contacts : <span className="muted">keine</span>),
            optional: true,
          },
        ]}
      />
    </>
  )
}

/** Veranstalter bearbeitet oder bestätigt die Meldung einer Untereinheit. */
export function UnitEntryPage({
  org,
  call,
  options,
}: {
  org: number
  call: CallDetail
  options: EntryOptions
}) {
  const unit = Number(useParams().unit)
  const scope = unitScope(org, unit)
  const entry = useLoad(() => entriesApi.entry(scope, call.id), [scope, call.id])
  const rows = useLoad(() => entriesApi.units(org, call.id), [org, call.id])
  const name = rows.data?.find((r) => r.unit === unit)?.name ?? ''
  if (entry.error) return <LoadError message={entry.error} onRetry={entry.reload} />
  if (entry.loading && entry.data === null) return <p className="muted">Wird geladen …</p>
  return (
    <>
      <p>
        <Link to={`/meldungen/${call.id}`}>← Eingang</Link>
      </p>
      <h2>Meldung {name}</h2>
      <EntryPanel
        org={scope}
        call={call}
        entry={entry.data ?? null}
        options={options}
        setEntry={(e) => entry.setData(e)}
        organizer
      />
    </>
  )
}

// --- Bereich der Untereinheit ---

/** „Meldungen“ im Bereich einer Untereinheit: Ausschreibungen von oben und die eigene Meldung. */
export function DeptEntries({ deptId }: { deptId: number }) {
  return (
    <Routes>
      <Route index element={<DeptCallList deptId={deptId} />} />
      <Route path=":id" element={<DeptCall deptId={deptId} />} />
    </Routes>
  )
}

function deptStatus(c: Call): string {
  if (!c.entry_status) return 'noch nicht gemeldet'
  if (c.entry_status === 'rueckfrage') return 'Rückfrage'
  const label = { entwurf: 'Entwurf', abgegeben: 'abgegeben', bestaetigt: 'bestätigt' }[
    c.entry_status as string
  ]
  return (
    (label ?? c.entry_status) +
    (c.entry_changed && c.entry_status !== 'entwurf' ? ', geändert' : '')
  )
}

function DeptCallList({ deptId }: { deptId: number }) {
  const scope = deptScope(deptId)
  const { data, error, reload } = useLoad(() => entriesApi.list(scope), [scope])
  if (error) return <LoadError message={error} onRetry={reload} />
  if (!data) return <p className="muted">Wird geladen …</p>
  return (
    <>
      <p className="muted">
        Ausschreibungen von oben, zu denen ihr eure Mitglieder meldet, etwa Schützen für ein
        Preisschießen.
      </p>
      <DataTable<Call>
        label="Ausschreibungen"
        rows={data}
        rowKey={(c) => c.id}
        initialSort={{ key: 'deadline', dir: 'asc' }}
        emptyText="Zurzeit gibt es keine Ausschreibung für euch."
        columns={[
          {
            key: 'deadline',
            label: 'Meldeschluss',
            value: (c) => c.deadline ?? '',
            render: (c) => (c.deadline ? formatDate(c.deadline) : '—'),
          },
          {
            key: 'title',
            label: 'Ausschreibung',
            value: (c) => c.title,
            render: (c) => <Link to={`/abteilung/meldungen/${c.id}`}>{c.title}</Link>,
          },
          {
            key: 'date',
            label: 'Datum',
            value: (c) => c.date ?? '',
            render: (c) => (c.date ? formatDate(c.date) : '—'),
            optional: true,
          },
          { key: 'status', label: 'Meldung', value: deptStatus, filter: true },
        ]}
      />
    </>
  )
}

function DeptCall({ deptId }: { deptId: number }) {
  const scope = deptScope(deptId)
  const id = Number(useParams().id)
  const call = useLoad(() => entriesApi.get(scope, id), [scope, id])
  const entry = useLoad(() => entriesApi.entry(scope, id), [scope, id])
  const options = useLoad(() => entriesApi.options(scope), [scope])
  const error = call.error || entry.error || options.error
  if (error) return <LoadError message={error} onRetry={() => void call.reload()} />
  if (!call.data || !options.data || (entry.loading && entry.data === null))
    return <p className="muted">Wird geladen …</p>
  const c = call.data
  return (
    <>
      <p>
        <Link to="/abteilung/meldungen">← Alle Ausschreibungen</Link>
      </p>
      <h2>{c.title}</h2>
      <p className="muted">
        {c.organizer}
        {c.date ? ` · ${formatDate(c.date)}` : ''}
        {c.location ? ` · ${c.location}` : ''}
        {c.deadline ? ` · Meldeschluss ${formatDate(c.deadline)}` : ''}
      </p>
      {c.description && <p className="event-description">{c.description}</p>}
      <EntryPanel
        org={scope}
        call={c}
        entry={entry.data ?? null}
        options={options.data}
        setEntry={(e) => {
          entry.setData(e)
          void call.reload()
        }}
      />
    </>
  )
}
