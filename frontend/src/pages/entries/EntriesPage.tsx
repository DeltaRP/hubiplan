// Meldungen: Ausschreibungen erfassen, Mannschaften und Personen melden, Fassungen.
// Konzept: konzepte/meldungen.md, Doku docs/meldungen.md.
import { useCallback, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import {
  BLOCK_LABELS,
  CHANNEL_LABELS,
  STATUS_LABELS,
  entriesApi,
  type BlockKind,
  type BlockSettings,
  type Call,
  type CallBlock,
  type CallDetail,
  type Candidate,
  type Channel,
  type Conditions,
  type Entry,
  type EntryOptions,
  type EntryPerson,
  type EntryTeam,
} from '../../api/entries.ts'
import type { PickedMember } from '../../api/members.ts'
import { DataTable } from '../../components/DataTable.tsx'
import { MemberPicker } from '../../components/MemberPicker.tsx'
import { confirmDialog, promptDialog } from '../../components/dialog.ts'
import { errorMessage, formatDate, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import {
  Alert,
  Checkbox,
  Field,
  LoadError,
  SaveStatus,
  SelectField,
  Tabs,
} from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'

export function EntriesPage() {
  return (
    <Routes>
      <Route index element={<CallList />} />
      <Route path=":id/*" element={<CallArea />} />
    </Routes>
  )
}

function statusText(c: Call): string {
  if (!c.entry_status) return 'noch nicht gemeldet'
  const label = STATUS_LABELS[c.entry_status]
  return c.entry_changed && c.entry_status !== 'entwurf' ? `${label}, geändert` : label
}

function CallList() {
  const org = useActiveOrg()
  const navigate = useNavigate()
  const { data, error, reload } = useLoad(() => entriesApi.list(org.id), [org.id])
  const [creating, setCreating] = useState(false)
  return (
    <section>
      <h1>Meldungen</h1>
      <p className="muted">
        Mannschaften, Personen und Angaben an einen Veranstalter melden, etwa zu einem
        Vergleichsschießen oder einem Verbandsfest. Die Meldung geht als Brief auf eurem Briefbogen,
        per E-Mail oder als Tabelle hinaus; Änderungen werden als neue Fassung festgehalten.
      </p>
      {error && <LoadError message={error} onRetry={reload} />}
      {!creating && (
        <div className="button-row">
          <button type="button" className="button" onClick={() => setCreating(true)}>
            Neue Ausschreibung erfassen
          </button>
        </div>
      )}
      {creating && (
        <NewCall
          org={org.id}
          onClose={() => setCreating(false)}
          onCreated={(id) => navigate(`/meldungen/${id}/ausschreibung`)}
        />
      )}
      {data && (
        <DataTable<Call>
          label="Ausschreibungen"
          rows={data}
          rowKey={(c) => c.id}
          initialSort={{ key: 'deadline', dir: 'desc' }}
          emptyText="Noch keine Ausschreibungen."
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
              render: (c) => <Link to={`/meldungen/${c.id}`}>{c.title}</Link>,
            },
            { key: 'organizer', label: 'Veranstalter', value: (c) => c.organizer },
            {
              key: 'date',
              label: 'Datum',
              value: (c) => c.date ?? '',
              render: (c) => (c.date ? formatDate(c.date) : '—'),
              optional: true,
            },
            { key: 'status', label: 'Meldung', value: statusText, filter: true },
          ]}
        />
      )}
    </section>
  )
}

function NewCall({
  org,
  onClose,
  onCreated,
}: {
  org: number
  onClose: () => void
  onCreated: (id: number) => void
}) {
  const form = useForm({
    title: '',
    organizer: '',
    date: '',
    deadline: '',
    template: 'mannschaften',
  })
  const { values: v, set, errors } = form

  async function save(e: FormEvent) {
    e.preventDefault()
    const created = await form.submit(() =>
      entriesApi.create(org, {
        title: v.title,
        organizer: v.organizer,
        date: v.date || null,
        deadline: v.deadline || null,
        template: v.template,
      }),
    )
    if (created) onCreated((created as CallDetail).id)
  }

  return (
    <div className="card card-wide">
      <form onSubmit={save}>
        <div className="card-head">
          <h2>Neue Ausschreibung</h2>
          <button type="button" className="button button-ghost push-right" onClick={onClose}>
            Abbrechen
          </button>
        </div>
        <p className="muted">
          Übertragt hier die Ausschreibung, die ihr per Brief oder Mail bekommen habt. Bei
          jährlichen Anlässen könnt ihr später die Ausschreibung des Vorjahres kopieren.
        </p>
        <div className="grid-3">
          <Field
            label="Titel"
            required
            placeholder="z. B. Vergleichsschießen 2027"
            value={v.title}
            error={errors.title}
            onChange={(e) => set('title', e.target.value)}
          />
          <Field
            label="Veranstalter"
            required
            placeholder="z. B. Bürger-Schützenverein"
            value={v.organizer}
            error={errors.organizer}
            onChange={(e) => set('organizer', e.target.value)}
          />
          <SelectField
            label="Vorlage"
            value={v.template}
            onChange={(e) => set('template', e.target.value)}
          >
            <option value="mannschaften">Mannschaften melden</option>
            <option value="">leer (Bausteine selbst anlegen)</option>
          </SelectField>
          <Field
            label="Datum des Anlasses"
            type="date"
            value={v.date}
            error={errors.date}
            onChange={(e) => set('date', e.target.value)}
          />
          <Field
            label="Meldeschluss"
            type="date"
            value={v.deadline}
            error={errors.deadline}
            onChange={(e) => set('deadline', e.target.value)}
          />
        </div>
        {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
        <div className="button-row">
          <button type="submit" className="button" disabled={form.busy}>
            Anlegen
          </button>
        </div>
      </form>
    </div>
  )
}

function CallArea() {
  const org = useActiveOrg()
  const id = Number(useParams().id)
  const call = useLoad(() => entriesApi.get(org.id, id), [org.id, id])
  const entry = useLoad(() => entriesApi.entry(org.id, id), [org.id, id])
  const options = useLoad(() => entriesApi.options(org.id), [org.id])
  const error = call.error || entry.error || options.error
  if (error)
    return (
      <LoadError
        message={error}
        onRetry={() => {
          void call.reload()
          void entry.reload()
          void options.reload()
        }}
      />
    )
  if (!call.data || !options.data || (entry.loading && entry.data === null))
    return <p className="muted">Wird geladen …</p>
  const c = call.data
  const base = `/meldungen/${id}`
  return (
    <section>
      <p>
        <Link to="/meldungen">← Alle Meldungen</Link>
      </p>
      <h1>{c.title}</h1>
      <p className="muted">
        Veranstalter: {c.organizer}
        {c.date ? ` · ${formatDate(c.date)}` : ''}
        {c.location ? ` · ${c.location}` : ''}
        {c.deadline ? ` · Meldeschluss ${formatDate(c.deadline)}` : ''}
      </p>
      <Tabs
        items={[
          { to: base, label: 'Meldung' },
          { to: `${base}/ausschreibung`, label: 'Ausschreibung' },
          { to: `${base}/fassungen`, label: 'Fassungen' },
        ]}
      />
      <Routes>
        <Route
          index
          element={
            <EntryPanel
              org={org.id}
              call={c}
              entry={entry.data ?? null}
              options={options.data}
              setEntry={(e) => {
                entry.setData(e)
                void call.reload()
              }}
            />
          }
        />
        <Route
          path="ausschreibung"
          element={
            <CallEditor
              org={org.id}
              call={c}
              options={options.data}
              onChanged={(d) => call.setData(d)}
              reload={() => {
                void call.reload()
                void entry.reload()
              }}
            />
          }
        />
        <Route
          path="fassungen"
          element={<VersionsPanel org={org.id} call={c} entry={entry.data ?? null} />}
        />
      </Routes>
    </section>
  )
}

// --- Meldung zusammenstellen ---

function EntryPanel({
  org,
  call,
  entry,
  options,
  setEntry,
}: {
  org: number
  call: CallDetail
  entry: Entry | null
  options: EntryOptions
  setEntry: (e: Entry | null) => void
}) {
  const [message, setMessage] = useState<string | null>(null)
  const run = useCallback(
    async (action: () => Promise<Entry | unknown>) => {
      setMessage(null)
      try {
        const result = await action()
        if (result && typeof result === 'object' && 'status' in result) setEntry(result as Entry)
        return true
      } catch (err) {
        setMessage(errorMessage(err))
        return false
      }
    },
    [setEntry],
  )

  if (!entry) {
    return (
      <div className="card card-wide">
        <p>Zu dieser Ausschreibung gibt es noch keine Meldung.</p>
        {call.blocks.length === 0 && (
          <Alert kind="info">
            Die Ausschreibung hat noch keine Bausteine. Legt unter „Ausschreibung“ fest, was
            gemeldet wird, z. B. Mannschaften.
          </Alert>
        )}
        {message && <Alert kind="error">{message}</Alert>}
        <div className="button-row">
          <button
            type="button"
            className="button"
            onClick={() => void run(() => entriesApi.createEntry(org, call.id))}
          >
            Meldung zusammenstellen
          </button>
        </div>
      </div>
    )
  }

  const withdrawn = entry.status === 'zurueckgezogen'
  const locked = withdrawn
  return (
    <>
      <div className="card card-wide">
        <div className="card-head">
          <h2>
            Meldung: {entry.status_label}
            {entry.changed && entry.status !== 'entwurf' ? ' (geändert, noch nicht gemeldet)' : ''}
          </h2>
        </div>
        {entry.confirmed_note && <p className="muted">Bestätigung: {entry.confirmed_note}</p>}
        {entry.after_deadline && !withdrawn && (
          <Alert kind="info">
            Der Meldeschluss ist vorbei.{' '}
            {call.changes_after_deadline === 'frei'
              ? 'Änderungen sind bis zum Anlass möglich.'
              : call.changes_after_deadline === 'ersatz'
                ? 'Möglich ist nur noch der Ersatz von Personen.'
                : 'Änderungen sind nicht mehr vorgesehen.'}
          </Alert>
        )}
        {entry.hints.length > 0 && (
          <div className="alert alert-info" role="status">
            <strong>Bitte prüfen</strong> (Abgeben bleibt möglich):
            <ul>
              {entry.hints.map((h, i) => (
                <li key={i}>{h.text}</li>
              ))}
            </ul>
          </div>
        )}
        {entry.competition && (
          <p>
            Zur Meldung gehört der Wettbewerb{' '}
            <Link to={`/wettbewerbe/${entry.competition}`}>{call.title}</Link>; dort tragt ihr
            später eure Plätze ein.
          </p>
        )}
        {message && <Alert kind="error">{message}</Alert>}
      </div>
      {call.blocks.map((b) => (
        <BlockEntry
          key={b.id}
          org={org}
          call={call}
          block={b}
          entry={entry}
          locked={locked}
          run={run}
        />
      ))}
      {!locked && <NoteCard org={org} call={call} entry={entry} setEntry={setEntry} />}
      {!locked && (
        <SubmitCard
          org={org}
          call={call}
          entry={entry}
          options={options}
          run={run}
          onDiscarded={() => setEntry(null)}
        />
      )}
    </>
  )
}

type Run = (action: () => Promise<Entry | unknown>) => Promise<boolean>

function BlockEntry({
  org,
  call,
  block,
  entry,
  locked,
  run,
}: {
  org: number
  call: CallDetail
  block: CallBlock
  entry: Entry
  locked: boolean
  run: Run
}) {
  const s = block.settings
  if (block.kind === 'mannschaften') {
    const teams = entry.teams.filter((t) => t.block === block.id)
    return (
      <div className="card card-wide">
        <div className="card-head">
          <h2>{block.label}</h2>
        </div>
        {block.help_text && <p className="muted">{block.help_text}</p>}
        <p className="muted small">
          {rangeText(s.min_teams, s.max_teams, 'Mannschaft', 'Mannschaften')}
          {s.min_size || s.max_size
            ? ` · je ${rangeText(s.min_size, s.max_size, 'Person', 'Personen')}`
            : ''}
          {s.substitutes ? ` · bis ${s.substitutes} Ersatz` : ''}
        </p>
        {teams.map((t) => (
          <TeamCard
            key={t.id}
            org={org}
            call={call}
            block={block}
            team={t}
            entry={entry}
            locked={locked}
            run={run}
          />
        ))}
        {!locked && (
          <div className="button-row">
            <button
              type="button"
              className="button button-ghost"
              onClick={() => void run(() => entriesApi.addTeam(org, call.id, block.id))}
            >
              Mannschaft hinzufügen
            </button>
          </div>
        )}
      </div>
    )
  }
  if (block.kind === 'personen') {
    const persons = entry.persons.filter((p) => p.block === block.id)
    return (
      <div className="card card-wide">
        <div className="card-head">
          <h2>{block.label}</h2>
        </div>
        {block.help_text && <p className="muted">{block.help_text}</p>}
        <PersonList
          org={org}
          call={call}
          block={block}
          persons={persons}
          entry={entry}
          locked={locked}
          run={run}
        />
        {!locked && (
          <PersonAdder org={org} call={call} block={block} team={null} entry={entry} run={run} />
        )}
      </div>
    )
  }
  return (
    <div className="card card-wide">
      <AnswerField
        key={`${block.id}-${JSON.stringify(entry.answers[String(block.id)] ?? null)}`}
        org={org}
        call={call}
        block={block}
        value={entry.answers[String(block.id)]}
        locked={locked}
        run={run}
      />
    </div>
  )
}

function rangeText(min: number | undefined, max: number | undefined, one: string, many: string) {
  const word = (n: number) => (n === 1 ? one : many)
  if (min && max != null && min === max) return `genau ${min} ${word(min)}`
  if (min && max != null) return `${min} bis ${max} ${many}`
  if (min) return `mindestens ${min} ${word(min)}`
  if (max != null) return `höchstens ${max} ${word(max)}`
  return `beliebig viele ${many}`
}

function TeamCard({
  org,
  call,
  block,
  team,
  entry,
  locked,
  run,
}: {
  org: number
  call: CallDetail
  block: CallBlock
  team: EntryTeam
  entry: Entry
  locked: boolean
  run: Run
}) {
  const [name, setName] = useState(team.name)
  const persons = entry.persons.filter((p) => p.team === team.id)

  async function remove() {
    const ok = await confirmDialog({
      title: 'Mannschaft entfernen',
      message: `„${team.name}“ mit ${persons.length} Personen aus der Meldung nehmen?`,
      confirmLabel: 'Entfernen',
      danger: true,
    })
    if (ok) await run(() => entriesApi.removeTeam(org, call.id, team.id))
  }

  return (
    <div className="card">
      <div className="card-head">
        {locked ? (
          <h3>{team.name}</h3>
        ) : (
          <Field
            label="Name der Mannschaft"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => {
              if (name.trim() && name !== team.name)
                void run(() => entriesApi.updateTeam(org, call.id, team.id, { name }))
            }}
          />
        )}
        {!locked && (
          <button type="button" className="button button-ghost push-right" onClick={remove}>
            Mannschaft entfernen
          </button>
        )}
      </div>
      <PersonList
        org={org}
        call={call}
        block={block}
        persons={persons}
        entry={entry}
        locked={locked}
        run={run}
      />
      {!locked && (
        <PersonAdder org={org} call={call} block={block} team={team} entry={entry} run={run} />
      )}
    </div>
  )
}

function PersonList({
  org,
  call,
  block,
  persons,
  entry,
  locked,
  run,
}: {
  org: number
  call: CallDetail
  block: CallBlock
  persons: EntryPerson[]
  entry: Entry
  locked: boolean
  run: Run
}) {
  const [replacing, setReplacing] = useState<number | null>(null)
  const positions = block.settings.positions ?? []
  if (persons.length === 0) return <p className="muted">Noch niemand gemeldet.</p>
  const hintsFor = (p: EntryPerson) => entry.hints.filter((h) => h.person === p.id)
  return (
    <table className="table">
      <thead>
        <tr>
          <th scope="col">Nr.</th>
          <th scope="col">Name</th>
          {positions.length > 0 && <th scope="col">Aufgabe</th>}
          {block.kind === 'mannschaften' && <th scope="col">Ersatz</th>}
          {!locked && <th scope="col">Aktionen</th>}
        </tr>
      </thead>
      <tbody>
        {persons.map((p, i) => (
          <tr key={p.id}>
            <td>{i + 1}</td>
            <td>
              {p.name}
              {p.club && <span className="muted"> ({p.club})</span>}
              {p.guest && <span className="muted small"> · Gast</span>}
              {hintsFor(p).map((h, j) => (
                <div key={j} className="muted small">
                  ⚠ {h.text}
                </div>
              ))}
              {replacing === p.id && (
                <MemberChooser
                  org={org}
                  call={call}
                  label="Ersatz: neues Mitglied auf diesem Platz"
                  onPick={async (m) => {
                    const ok = await run(() =>
                      entriesApi.updatePerson(org, call.id, p.id, { membership: m }),
                    )
                    if (ok) setReplacing(null)
                  }}
                />
              )}
            </td>
            {positions.length > 0 && (
              <td>
                <select
                  aria-label={`Aufgabe von ${p.name}`}
                  value={p.position}
                  disabled={locked}
                  onChange={(e) =>
                    void run(() =>
                      entriesApi.updatePerson(org, call.id, p.id, { position: e.target.value }),
                    )
                  }
                >
                  <option value="">—</option>
                  {positions.map((pos) => (
                    <option key={pos} value={pos}>
                      {pos}
                    </option>
                  ))}
                </select>
              </td>
            )}
            {block.kind === 'mannschaften' && (
              <td>
                <input
                  type="checkbox"
                  aria-label={`${p.name} als Ersatz`}
                  checked={p.substitute}
                  disabled={locked}
                  onChange={(e) =>
                    void run(() =>
                      entriesApi.updatePerson(org, call.id, p.id, {
                        substitute: e.target.checked,
                      }),
                    )
                  }
                />
              </td>
            )}
            {!locked && (
              <td>
                {entry.can_pick_members && (
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => setReplacing(replacing === p.id ? null : p.id)}
                  >
                    {replacing === p.id ? 'kein Ersatz' : 'ersetzen'}
                  </button>
                )}{' '}
                <button
                  type="button"
                  className="link-button"
                  onClick={() => void run(() => entriesApi.removePerson(org, call.id, p.id))}
                >
                  streichen
                </button>
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

type PickedCandidate = PickedMember & { candidate: Candidate }

/** Mitglied aus der kompletten Mitgliederliste wählen (Ralf 2026-11-01), auf Wunsch auch
 *  Ausgetretene. */
function MemberChooser({
  org,
  call,
  label,
  onPick,
}: {
  org: number
  call: CallDetail
  label: string
  onPick: (membership: number) => void
}) {
  const [all, setAll] = useState(false)
  const search = useCallback(
    (term: string) =>
      entriesApi.candidates(org, call.id, term, all).then((rows) =>
        rows.map((r): PickedCandidate => ({
          id: r.membership,
          first_name: r.first_name,
          last_name: r.last_name,
          email: [
            r.unit_name,
            r.birth_year ? `geb. ${r.birth_year}` : '',
            r.active ? '' : 'nicht aktiv',
            r.taken ? 'schon gemeldet' : '',
          ]
            .filter(Boolean)
            .join(' · '),
          candidate: r,
        })),
      ),
    [org, call.id, all],
  )
  return (
    <div>
      <MemberPicker<PickedCandidate>
        orgId={org}
        label={label}
        value={null}
        search={search}
        onChange={(m) => m && onPick(m.id)}
      />
      <Checkbox label="auch ausgetretene Mitglieder" checked={all} onChange={setAll} />
    </div>
  )
}

function PersonAdder({
  org,
  call,
  block,
  team,
  entry,
  run,
}: {
  org: number
  call: CallDetail
  block: CallBlock
  team: EntryTeam | null
  entry: Entry
  run: Run
}) {
  const [guest, setGuest] = useState(false)
  const [name, setName] = useState('')
  const [club, setClub] = useState('')
  const target = { block: block.id, team: team?.id ?? null }
  return (
    <div className="grid-3">
      {entry.can_pick_members && !guest && (
        <MemberChooser
          org={org}
          call={call}
          label="Mitglied hinzufügen"
          onPick={(m) =>
            void run(() => entriesApi.addPerson(org, call.id, { ...target, membership: m }))
          }
        />
      )}
      {(guest || !entry.can_pick_members) && (
        <>
          <Field label="Name des Gastes" value={name} onChange={(e) => setName(e.target.value)} />
          <Field label="Verein" value={club} onChange={(e) => setClub(e.target.value)} />
          <div className="button-row">
            <button
              type="button"
              className="button button-ghost"
              disabled={!name.trim()}
              onClick={async () => {
                const ok = await run(() =>
                  entriesApi.addPerson(org, call.id, { ...target, name, club }),
                )
                if (ok) {
                  setName('')
                  setClub('')
                }
              }}
            >
              Gast hinzufügen
            </button>
          </div>
        </>
      )}
      {entry.can_pick_members && (
        <Checkbox label="Gast (kein Mitglied)" checked={guest} onChange={setGuest} />
      )}
    </div>
  )
}

function AnswerField({
  org,
  call,
  block,
  value,
  locked,
  run,
}: {
  org: number
  call: CallDetail
  block: CallBlock
  value: unknown
  locked: boolean
  run: Run
}) {
  const initial =
    value == null ? '' : Array.isArray(value) ? value.map(String) : String(value as string)
  const [current, setCurrent] = useState<string | string[]>(initial)
  const save = (v: unknown) => void run(() => entriesApi.answer(org, call.id, block.id, v))
  const label = block.required ? `${block.label} (Pflicht)` : block.label
  if (block.kind === 'auswahl') {
    const opts = block.settings.options ?? []
    if (block.settings.multiple) {
      const chosen = Array.isArray(current) ? current : current ? [current] : []
      return (
        <fieldset disabled={locked}>
          <legend>{label}</legend>
          {opts.map((o) => (
            <Checkbox
              key={o}
              label={o}
              checked={chosen.includes(o)}
              onChange={(on) => {
                const next = on ? [...chosen, o] : chosen.filter((x) => x !== o)
                setCurrent(next)
                save(next)
              }}
            />
          ))}
        </fieldset>
      )
    }
    return (
      <SelectField
        label={label}
        value={typeof current === 'string' ? current : ''}
        disabled={locked}
        hint={block.help_text || undefined}
        onChange={(e) => {
          setCurrent(e.target.value)
          save(e.target.value)
        }}
      >
        <option value="">—</option>
        {opts.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </SelectField>
    )
  }
  if (block.kind === 'text' && block.settings.multiline) {
    return (
      <label className="field">
        <span>{label}</span>
        <textarea
          rows={3}
          disabled={locked}
          value={typeof current === 'string' ? current : ''}
          onChange={(e) => setCurrent(e.target.value)}
          onBlur={() => current !== initial && save(current)}
        />
      </label>
    )
  }
  return (
    <Field
      label={label}
      type={block.kind === 'zahl' ? 'number' : 'text'}
      disabled={locked}
      hint={block.help_text || undefined}
      value={typeof current === 'string' ? current : ''}
      onChange={(e) => setCurrent(e.target.value)}
      onBlur={() => current !== initial && save(current)}
    />
  )
}

function NoteCard({
  org,
  call,
  entry,
  setEntry,
}: {
  org: number
  call: CallDetail
  entry: Entry
  setEntry: (e: Entry) => void
}) {
  const [note, setNote] = useState(entry.note)
  return (
    <div className="card card-wide">
      <label className="field">
        <span>Interne Notiz (geht nicht an den Veranstalter)</span>
        <textarea
          rows={2}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onBlur={async () => {
            if (note !== entry.note) setEntry(await entriesApi.updateEntry(org, call.id, { note }))
          }}
        />
      </label>
    </div>
  )
}

function SubmitCard({
  org,
  call,
  entry,
  options,
  run,
  onDiscarded,
}: {
  org: number
  call: CallDetail
  entry: Entry
  options: EntryOptions
  run: Run
  onDiscarded: () => void
}) {
  const [channel, setChannel] = useState<Channel>(call.organizer_email ? 'email' : 'brief')
  const [email, setEmail] = useState(call.organizer_email)
  const [sentTo, setSentTo] = useState('')
  const [fn, setFn] = useState(options.functions[0] ?? '')
  const [busy, setBusy] = useState(false)
  const first = entry.versions.length === 0
  const nothingNew = !first && !entry.changed
  const preview = (fmt: 'pdf' | 'xlsx' | 'csv') => entriesApi.previewUrl(org, call.id, fmt)

  async function submit() {
    setBusy(true)
    await run(() =>
      entriesApi.submit(org, call.id, {
        channel,
        email: channel === 'email' ? email : undefined,
        sent_to: channel === 'sonstiges' ? sentTo : undefined,
        function: fn,
      }),
    )
    setBusy(false)
  }

  async function withdraw() {
    const reason = await promptDialog({
      title: 'Meldung zurückziehen',
      message:
        'Die Rückzugserklärung wird als neue Fassung festgehalten und über den gewählten Meldeweg verschickt bzw. als Brief erstellt.',
      label: 'Grund (optional)',
      confirmLabel: 'Zurückziehen',
      danger: true,
    })
    if (reason === null) return
    await run(() =>
      entriesApi.submit(org, call.id, {
        channel,
        email: channel === 'email' ? email : undefined,
        sent_to: channel === 'sonstiges' ? sentTo : undefined,
        function: fn,
        withdraw: true,
        reason,
      }),
    )
  }

  async function confirmed() {
    const note = await promptDialog({
      title: 'Bestätigung vermerken',
      label: 'Wie und wann bestätigt?',
      defaultValue: `per Mail am ${new Date().toLocaleDateString('de-DE')}`,
    })
    if (note !== null) await run(() => entriesApi.confirm(org, call.id, note))
  }

  async function discard() {
    const ok = await confirmDialog({
      title: 'Entwurf verwerfen',
      message: 'Alle Mannschaften, Personen und Angaben dieses Entwurfs löschen?',
      confirmLabel: 'Verwerfen',
      danger: true,
    })
    if (ok && (await run(() => entriesApi.discard(org, call.id)))) onDiscarded()
  }

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>{first ? 'Meldung abgeben' : 'Änderung melden'}</h2>
      </div>
      <p>
        Vorschau:{' '}
        <a href={preview('pdf')} target="_blank" rel="noreferrer">
          Brief (PDF)
        </a>{' '}
        · <a href={preview('xlsx')}>Tabelle (Excel)</a> · <a href={preview('csv')}>CSV</a>
      </p>
      {nothingNew ? (
        <p className="muted">Seit der letzten Fassung hat sich nichts geändert.</p>
      ) : (
        <>
          <div className="grid-3">
            <SelectField
              label="Meldeweg"
              value={channel}
              onChange={(e) => setChannel(e.target.value as Channel)}
            >
              {(Object.keys(CHANNEL_LABELS) as Channel[]).map((k) => (
                <option key={k} value={k}>
                  {CHANNEL_LABELS[k]}
                </option>
              ))}
            </SelectField>
            {channel === 'email' && (
              <Field
                label="E-Mail des Veranstalters"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            )}
            {channel === 'sonstiges' && (
              <Field
                label="Vermerk"
                placeholder="z. B. persönlich übergeben"
                value={sentTo}
                onChange={(e) => setSentTo(e.target.value)}
              />
            )}
            {options.functions.length > 0 && (
              <SelectField
                label="Unterschrift als"
                value={fn}
                onChange={(e) => setFn(e.target.value)}
              >
                {options.functions.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </SelectField>
            )}
          </div>
          <p className="muted small">
            Unterzeichnet von {options.signer}. Im Brief bleibt Platz für die eigenhändige
            Unterschrift.
            {channel === 'brief' &&
              ' Nach dem Abgeben findet ihr den Brief unter „Fassungen“ zum Drucken.'}
            {channel === 'email' && ' Ihr bekommt eine Kopie an eure eigene Adresse.'}
          </p>
          <div className="button-row">
            <button type="button" className="button" disabled={busy} onClick={submit}>
              {first ? 'Meldung abgeben' : 'Änderung melden'}
            </button>
          </div>
        </>
      )}
      <div className="button-row">
        {entry.status === 'abgegeben' && (
          <button type="button" className="button button-ghost" onClick={confirmed}>
            Bestätigung des Veranstalters vermerken
          </button>
        )}
        {entry.status === 'bestaetigt' && (
          <button
            type="button"
            className="button button-ghost"
            onClick={() => void run(() => entriesApi.unconfirm(org, call.id))}
          >
            Bestätigung zurücknehmen
          </button>
        )}
        {!first && (
          <button type="button" className="button button-ghost" onClick={withdraw}>
            Meldung zurückziehen
          </button>
        )}
        {first && (
          <button type="button" className="button button-ghost" onClick={discard}>
            Entwurf verwerfen
          </button>
        )}
      </div>
    </div>
  )
}

// --- Fassungen ---

function VersionsPanel({
  org,
  call,
  entry,
}: {
  org: number
  call: CallDetail
  entry: Entry | null
}) {
  if (!entry || entry.versions.length === 0) return <p className="muted">Noch nichts abgegeben.</p>
  const url = (n: number, fmt: 'pdf' | 'xlsx' | 'csv') =>
    entriesApi.versionUrl(org, call.id, n, fmt)
  return (
    <div className="card card-wide">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Fassung</th>
            <th scope="col">Abgegeben</th>
            <th scope="col">Meldeweg</th>
            <th scope="col">Inhalt</th>
            <th scope="col">Belege</th>
          </tr>
        </thead>
        <tbody>
          {[...entry.versions].reverse().map((v) => (
            <tr key={v.id}>
              <td>
                {v.number} · {v.kind_label}
              </td>
              <td>
                {new Date(v.created_at).toLocaleString('de-DE', {
                  dateStyle: 'short',
                  timeStyle: 'short',
                })}
                <div className="muted small">{v.signed_by}</div>
              </td>
              <td>
                {v.channel_label}
                {v.sent_to && <div className="muted small">{v.sent_to}</div>}
              </td>
              <td>
                {v.changes.length > 0 ? (
                  <ul>
                    {v.changes.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                ) : (
                  'vollständige Meldung'
                )}
                {v.reason && <div className="muted small">Grund: {v.reason}</div>}
                {v.shortened && (
                  <div className="muted small">nach Ablauf der Frist auf Namen gekürzt</div>
                )}
              </td>
              <td>
                <a href={url(v.number, 'pdf')} target="_blank" rel="noreferrer">
                  Brief
                </a>{' '}
                · <a href={url(v.number, 'xlsx')}>Excel</a> · <a href={url(v.number, 'csv')}>CSV</a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// --- Ausschreibung bearbeiten ---

function numOrNull(raw: string): number | null {
  if (raw.trim() === '') return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}

function CallEditor({
  org,
  call,
  options,
  onChanged,
  reload,
}: {
  org: number
  call: CallDetail
  options: EntryOptions
  onChanged: (c: CallDetail) => void
  reload: () => void
}) {
  const navigate = useNavigate()
  const form = useForm({
    title: call.title,
    organizer: call.organizer,
    organizer_address: call.organizer_address,
    organizer_email: call.organizer_email,
    salutation: call.salutation,
    description: call.description,
    date: call.date ?? '',
    location: call.location,
    deadline: call.deadline ?? '',
    reference_date: call.reference_date ?? '',
    person_fields: call.person_fields,
    conditions: call.conditions,
    fee_amount: call.fee_amount ?? '',
    fee_per: call.fee_per,
    changes_after_deadline: call.changes_after_deadline,
    create_competition: call.create_competition,
  })
  const { values: v, set, errors } = form
  const auto = useAutoSave(
    form,
    (changes) => {
      const data: Record<string, unknown> = { ...changes }
      for (const k of ['date', 'deadline', 'reference_date', 'fee_amount'] as const)
        if (k in data && data[k] === '') data[k] = null
      return entriesApi.update(org, call.id, data as Partial<Call>)
    },
    { onSaved: (saved) => onChanged(saved as CallDetail) },
  )
  const cond = v.conditions
  const setCond = (c: Partial<Conditions>) => set('conditions', { ...cond, ...c })
  const toggle = (list: number[] | undefined, id: number, on: boolean) =>
    on ? [...(list ?? []), id] : (list ?? []).filter((x) => x !== id)

  async function copy() {
    const created = await entriesApi.copy(org, call.id)
    navigate(`/meldungen/${created.id}/ausschreibung`)
  }

  async function remove() {
    const ok = await confirmDialog({
      title: 'Ausschreibung löschen',
      message: `„${call.title}“ samt Entwurf löschen?`,
      confirmLabel: 'Löschen',
      danger: true,
    })
    if (!ok) return
    try {
      await entriesApi.remove(org, call.id)
      navigate('/meldungen')
    } catch (err) {
      form.setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  return (
    <>
      <div className="card card-wide">
        <div className="card-head">
          <h2>Ausschreibung</h2>
          <SaveStatus auto={auto} />
        </div>
        <div className="grid-3">
          <Field
            label="Titel"
            value={v.title}
            error={errors.title}
            onChange={(e) => set('title', e.target.value)}
          />
          <Field
            label="Datum des Anlasses"
            type="date"
            value={v.date}
            error={errors.date}
            onChange={(e) => set('date', e.target.value)}
          />
          <Field
            label="Ort"
            value={v.location}
            error={errors.location}
            onChange={(e) => set('location', e.target.value)}
          />
          <Field
            label="Meldeschluss"
            type="date"
            value={v.deadline}
            error={errors.deadline}
            onChange={(e) => set('deadline', e.target.value)}
          />
          <SelectField
            label="Nach Meldeschluss"
            value={v.changes_after_deadline}
            onChange={(e) =>
              set('changes_after_deadline', e.target.value as Call['changes_after_deadline'])
            }
          >
            <option value="ersatz">nur Ersatz von Personen</option>
            <option value="keine">keine Änderungen</option>
            <option value="frei">Änderungen bis zum Anlass</option>
          </SelectField>
          <Field
            label="Stichtag für Alter und Mitgliedschaft"
            type="date"
            hint="leer: Datum des Anlasses"
            value={v.reference_date}
            error={errors.reference_date}
            onChange={(e) => set('reference_date', e.target.value)}
          />
        </div>
        <h3>Veranstalter</h3>
        <div className="grid-3">
          <Field
            label="Name"
            value={v.organizer}
            error={errors.organizer}
            onChange={(e) => set('organizer', e.target.value)}
          />
          <label className="field">
            <span>Anschrift (ohne Name)</span>
            <textarea
              rows={3}
              value={v.organizer_address}
              onChange={(e) => set('organizer_address', e.target.value)}
            />
          </label>
          <Field
            label="E-Mail"
            type="email"
            value={v.organizer_email}
            error={errors.organizer_email}
            onChange={(e) => set('organizer_email', e.target.value)}
          />
          <Field
            label="Anrede im Brief"
            value={v.salutation}
            error={errors.salutation}
            onChange={(e) => set('salutation', e.target.value)}
          />
        </div>
        <label className="field">
          <span>Beschreibung (z. B. Auszug aus der Ausschreibung)</span>
          <textarea
            rows={3}
            value={v.description}
            onChange={(e) => set('description', e.target.value)}
          />
        </label>
        <h3>Meldegebühr</h3>
        <div className="grid-3">
          <Field
            label="Betrag (€)"
            inputMode="decimal"
            value={v.fee_amount}
            error={errors.fee_amount}
            onChange={(e) => set('fee_amount', e.target.value)}
          />
          <SelectField
            label="berechnet"
            value={v.fee_per}
            onChange={(e) => set('fee_per', e.target.value as Call['fee_per'])}
          >
            <option value="mannschaft">je Mannschaft</option>
            <option value="person">je Person</option>
            <option value="pauschal">pauschal</option>
          </SelectField>
        </div>
        <h3>Angaben je Person</h3>
        <p className="muted small">
          Nur angekreuzte Angaben gehen an den Veranstalter. Der Name steht immer drin.
        </p>
        <div className="grid-3">
          {options.person_fields.map((f) => (
            <Checkbox
              key={f.key}
              label={f.label}
              checked={v.person_fields.includes(f.key)}
              onChange={(on) =>
                set(
                  'person_fields',
                  on ? [...v.person_fields, f.key] : v.person_fields.filter((k) => k !== f.key),
                )
              }
            />
          ))}
        </div>
        <h3>Bedingungen</h3>
        <p className="muted small">
          HUBIplan weist auf Verstöße hin; abgeben bleibt möglich, der Veranstalter entscheidet.
        </p>
        <div className="grid-3">
          <Checkbox
            label="nur aktive Mitglieder am Stichtag"
            checked={!!cond.active}
            onChange={(on) => setCond({ active: on })}
          />
          <Checkbox
            label="Gäste (Nichtmitglieder) erlaubt"
            checked={!!cond.guests}
            onChange={(on) => setCond({ guests: on })}
          />
          <Checkbox
            label="jede Person nur in einer Mannschaft"
            checked={!!cond.one_team}
            onChange={(on) => setCond({ one_team: on })}
          />
          <Field
            label="Mindestalter"
            type="number"
            min={0}
            value={cond.min_age ?? ''}
            error={errors.min_age}
            onChange={(e) => setCond({ min_age: numOrNull(e.target.value) ?? undefined })}
          />
          <Field
            label="Höchstalter"
            type="number"
            min={0}
            value={cond.max_age ?? ''}
            error={errors.max_age}
            onChange={(e) => setCond({ max_age: numOrNull(e.target.value) ?? undefined })}
          />
        </div>
        {options.member_types.length > 0 && (
          <fieldset>
            <legend>nur diese Mitgliedsarten (keine Auswahl: alle)</legend>
            {options.member_types.map((t) => (
              <Checkbox
                key={t.id}
                label={t.name}
                checked={(cond.member_types ?? []).includes(t.id)}
                onChange={(on) => setCond({ member_types: toggle(cond.member_types, t.id, on) })}
              />
            ))}
          </fieldset>
        )}
        {options.units.length > 0 && (
          <fieldset>
            <legend>nur aus diesen {options.unit_label}-Einheiten (keine Auswahl: alle)</legend>
            {options.units.map((u) => (
              <Checkbox
                key={u.id}
                label={u.name}
                checked={(cond.units ?? []).includes(u.id)}
                onChange={(on) => setCond({ units: toggle(cond.units, u.id, on) })}
              />
            ))}
          </fieldset>
        )}
        {options.competitions_enabled && (
          <Checkbox
            label="beim Abgeben einen fremden Wettbewerb mit den Mannschaften anlegen"
            hint="dort tragt ihr später eure Plätze ein"
            checked={v.create_competition}
            onChange={(on) => set('create_competition', on)}
          />
        )}
        {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
        <div className="button-row">
          <button type="button" className="button button-ghost" onClick={copy}>
            Für das nächste Jahr kopieren
          </button>
          {!call.has_versions && (
            <button type="button" className="button button-ghost" onClick={remove}>
              Ausschreibung löschen
            </button>
          )}
        </div>
      </div>
      <BlocksEditor org={org} call={call} reload={reload} />
    </>
  )
}

function BlocksEditor({
  org,
  call,
  reload,
}: {
  org: number
  call: CallDetail
  reload: () => void
}) {
  const [kind, setKind] = useState<BlockKind>('mannschaften')
  const [message, setMessage] = useState<string | null>(null)
  async function add() {
    setMessage(null)
    try {
      await entriesApi.addBlock(org, call.id, {
        kind,
        label: BLOCK_LABELS[kind],
        settings: kind === 'auswahl' ? { options: ['ja', 'nein'] } : {},
      })
      reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }
  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>Was gemeldet wird</h2>
      </div>
      <p className="muted">
        Bausteine des Meldeformulars: Mannschaften, eine Personenliste (z. B. Delegierte), eine Zahl
        (z. B. Teilnehmer am Umzug), eine Auswahl oder ein Text.
      </p>
      {call.blocks.map((b) => (
        <BlockCard key={b.id} org={org} call={call} block={b} reload={reload} />
      ))}
      {message && <Alert kind="error">{message}</Alert>}
      <div className="grid-3">
        <SelectField
          label="Baustein"
          value={kind}
          onChange={(e) => setKind(e.target.value as BlockKind)}
        >
          {(Object.keys(BLOCK_LABELS) as BlockKind[]).map((k) => (
            <option key={k} value={k}>
              {BLOCK_LABELS[k]}
            </option>
          ))}
        </SelectField>
        <div className="button-row">
          <button type="button" className="button button-ghost" onClick={add}>
            Baustein hinzufügen
          </button>
        </div>
      </div>
    </div>
  )
}

function BlockCard({
  org,
  call,
  block,
  reload,
}: {
  org: number
  call: CallDetail
  block: CallBlock
  reload: () => void
}) {
  const form = useForm({
    label: block.label,
    help_text: block.help_text,
    required: block.required,
    settings: block.settings,
  })
  const { values: v, set, errors } = form
  const auto = useAutoSave(form, (changes) =>
    entriesApi.updateBlock(org, call.id, block.id, changes),
  )
  const s = v.settings
  const setS = (x: Partial<BlockSettings>) => set('settings', { ...s, ...x })
  const num = (key: keyof BlockSettings, label: string) => (
    <Field
      label={label}
      type="number"
      min={0}
      value={(s[key] as number | undefined) ?? ''}
      error={errors[key]}
      onChange={(e) => setS({ [key]: numOrNull(e.target.value) ?? undefined })}
    />
  )
  const list = (key: 'positions' | 'options', label: string, hint: string) => (
    <Field
      label={label}
      hint={hint}
      value={(s[key] ?? []).join(', ')}
      error={errors[key]}
      onChange={(e) =>
        setS({
          [key]: e.target.value
            .split(',')
            .map((x) => x.trim())
            .filter(Boolean),
        })
      }
    />
  )

  async function remove() {
    const ok = await confirmDialog({
      title: 'Baustein entfernen',
      message: `„${block.label}“ samt den Einträgen der Meldung entfernen?`,
      confirmLabel: 'Entfernen',
      danger: true,
    })
    if (!ok) return
    try {
      await entriesApi.removeBlock(org, call.id, block.id)
      reload()
    } catch (err) {
      form.setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>{BLOCK_LABELS[block.kind]}</h3>
        <SaveStatus auto={auto} />
        <button type="button" className="button button-ghost push-right" onClick={remove}>
          Entfernen
        </button>
      </div>
      <div className="grid-3">
        <Field
          label="Bezeichnung"
          value={v.label}
          error={errors.label}
          onChange={(e) => set('label', e.target.value)}
        />
        <Field
          label="Hinweis"
          value={v.help_text}
          error={errors.help_text}
          onChange={(e) => set('help_text', e.target.value)}
        />
        <Checkbox label="Pflicht" checked={v.required} onChange={(on) => set('required', on)} />
        {block.kind === 'mannschaften' && (
          <>
            {num('min_teams', 'Mannschaften mindestens')}
            {num('max_teams', 'Mannschaften höchstens')}
            {num('min_size', 'Personen je Mannschaft mindestens')}
            {num('max_size', 'Personen je Mannschaft höchstens')}
            {num('substitutes', 'Ersatzleute je Mannschaft höchstens')}
            {list('positions', 'Aufgaben', 'z. B. Mannschaftsführer, mit Komma getrennt')}
          </>
        )}
        {block.kind === 'personen' && (
          <>
            {num('min', 'Personen mindestens')}
            {num('max', 'Personen höchstens')}
            {list('positions', 'Aufgaben', 'z. B. Delegierter, Fahnenträger')}
          </>
        )}
        {block.kind === 'zahl' && (
          <>
            {num('min', 'kleinster Wert')}
            {num('max', 'größter Wert')}
          </>
        )}
        {block.kind === 'auswahl' && (
          <>
            {list('options', 'Antworten', 'mit Komma getrennt')}
            <Checkbox
              label="mehrere Antworten möglich"
              checked={!!s.multiple}
              onChange={(on) => setS({ multiple: on })}
            />
          </>
        )}
        {block.kind === 'text' && (
          <Checkbox
            label="mehrzeilig"
            checked={!!s.multiline}
            onChange={(on) => setS({ multiline: on })}
          />
        )}
      </div>
      {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
    </div>
  )
}
