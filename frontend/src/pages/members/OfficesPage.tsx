// Mitglieder › Ämter: wer hatte wann welches Amt (jahresgenau). Frühere Inhaber, die
// keine Mitglieder mehr sind, stehen als Name ohne Konto; Erfassen und Excel-Import.
import { useState } from 'react'
import { Route, Routes } from 'react-router-dom'
import { newRequestKey } from '../../api/client.ts'
import { officesApi } from '../../api/offices.ts'
import type { Office, OfficeEntryInput, OfficeHolder, OfficeImportRow } from '../../api/offices.ts'
import { PERM } from '../../api/orgs.ts'
import { DataTable } from '../../components/DataTable.tsx'
import type { Column } from '../../components/DataTable.tsx'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { useChangesGuard } from '../../components/leaveGuard.ts'
import { DeleteIcon, EditIcon, IconButton } from '../../components/icons.tsx'
import { Alert, Checkbox, Field, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { MembersSection } from '../MembersPage.tsx'
import { CandidateSelect, PersonField } from './ChroniclePage.tsx'
import { t } from '../../i18n/index.ts'

export function OfficesPage() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.membersEdit)
  const tabs = [
    { to: '/mitglieder/aemter', label: t('Amtsinhaber') },
    { to: '/mitglieder/aemter/statistik', label: t('Statistik') },
    ...(canEdit ? [{ to: '/mitglieder/aemter/import', label: t('Import') }] : []),
  ]
  return (
    <MembersSection title={t('Ämter')} tabs={tabs}>
      <Routes>
        <Route index element={<HoldersPanel />} />
        <Route path="statistik" element={<StatsPanel />} />
        {canEdit && <Route path="import" element={<ImportPanel />} />}
      </Routes>
    </MembersSection>
  )
}

function officeLabel(o: { name: string; unit_name: string | null }) {
  return o.unit_name ? t('{name} ({unit_name})', { name: o.name, unit_name: o.unit_name }) : o.name
}

function periodText(h: { from_year: number; until_year: number | null; current: boolean }) {
  if (h.current) return t('{from_year} bis heute', { from_year: h.from_year })
  if (h.until_year === null || h.until_year === h.from_year) return String(h.from_year)
  return t('{from_year} bis {until_year}', { from_year: h.from_year, until_year: h.until_year })
}

interface Row extends OfficeHolder {
  office: Office
}

function HoldersPanel() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.membersEdit)
  const offices = useLoad(() => officesApi.list(org.id), [org.id])
  const [editing, setEditing] = useState<Row | 'new' | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  if (offices.error) return <Alert kind="error">{offices.error}</Alert>
  if (!offices.data) return <p className="muted">{t('Lädt …')}</p>
  // Je Amt eine eigene Tabelle (Ralf 2026-10-31)
  // Nur Ämter der eigenen Einheit, keine der Untereinheiten (Ralf 2026-10-31)
  const own = offices.data.filter((o) => o.unit === null)
  const groups = own.filter((o) => o.holders.length > 0)

  async function remove(r: Row) {
    const ok = await confirmDialog({
      title: t('Eintrag löschen?'),
      message: t('{x} {x2}: {name}', { x: officeLabel(r.office), x2: periodText(r), name: r.name }),
      confirmLabel: t('Löschen'),
    })
    if (!ok) return
    try {
      await officesApi.remove(org.id, r.id)
      await offices.reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  return (
    <>
      <div className="card card-wide">
        <div className="card-head">
          <h2>{t('Amtsinhaber')}</h2>
          {canEdit && editing === null && own.length > 0 && (
            <button
              type="button"
              className="button button-ghost push-right"
              onClick={() => setEditing('new')}
            >
              {t('Früheren Inhaber eintragen')}
            </button>
          )}
        </div>
        <p className="muted small">
          {t(
            'Wer wann welches Amt hatte, auf das Jahr genau. Heutige Inhaber vergebt ihr wie bisher unter den Rollen. Frühere Inhaber, die keine Mitglieder mehr sind, tragt ihr hier mit Namen ein oder importiert eine Liste. Auf der Webseite erscheinen die Ämter, bei denen in der Rolle „unter Ämter zeigen“ eingeschaltet ist.',
          )}
        </p>
        {own.length === 0 && (
          <Alert kind="info">{t('Legt zuerst unter Einstellungen › Rollen die Ämter an.')}</Alert>
        )}
        {own.length > 0 && groups.length === 0 && (
          <p className="muted">{t('Noch keine Amtsinhaber erfasst.')}</p>
        )}
        {editing !== null && (
          <EntryForm
            key={editing === 'new' ? 'new' : editing.id}
            entry={editing === 'new' ? null : editing}
            offices={own}
            onDone={async () => {
              setEditing(null)
              await offices.reload()
            }}
            onCancel={() => setEditing(null)}
          />
        )}
        {message && <Alert kind="error">{message}</Alert>}
      </div>
      {groups.map((o) => (
        <div className="card card-wide" key={o.id}>
          <h2>{officeLabel(o)}</h2>
          {o.in_chronicle && <p className="muted small">{t('Auf der Webseite unter „Ämter“.')}</p>}
          <div className="table-scroll">
            <table className="table" aria-label={t('{x}: Inhaber', { x: officeLabel(o) })}>
              <thead>
                <tr>
                  <th scope="col">{t('Zeitraum')}</th>
                  <th scope="col">{t('Name')}</th>
                  {canEdit && (
                    <th scope="col">
                      <span className="sr-only">{t('Aktionen')}</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {o.holders.map((h) => {
                  const r: Row = { ...h, office: o }
                  return (
                    <tr key={h.id}>
                      <td>{periodText(h)}</td>
                      <td>
                        {h.name}
                        {h.former_entry && h.person === null && (
                          <span className="muted small">
                            {h.name_public
                              ? ' (kein Mitglied)'
                              : ' (kein Mitglied, nicht auf der Webseite)'}
                          </span>
                        )}
                      </td>
                      {canEdit && (
                        <td className="actions">
                          {h.former_entry && (
                            <>
                              <IconButton
                                label={t('{name} {x} bearbeiten', {
                                  name: h.name,
                                  x: periodText(h),
                                })}
                                icon={<EditIcon />}
                                onClick={() => setEditing(r)}
                              />
                              <IconButton
                                label={t('{name} {x} löschen', { name: h.name, x: periodText(h) })}
                                icon={<DeleteIcon />}
                                danger
                                onClick={() => void remove(r)}
                              />
                            </>
                          )}
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </>
  )
}

function EntryForm({
  entry,
  offices,
  onDone,
  onCancel,
}: {
  entry: Row | null
  offices: Office[]
  onDone: () => void
  onCancel: () => void
}) {
  const org = useActiveOrg()
  const form = useForm<OfficeEntryInput>({
    role: entry?.role ?? (offices.find((o) => o.in_chronicle) ?? offices[0]).id,
    name: entry?.name ?? '',
    person: entry?.person ?? null,
    from_year: entry?.from_year ?? null,
    until_year: entry?.until_year ?? null,
    name_public: entry?.name_public ?? false,
  })
  const { values: v, set, errors } = form
  // Bestehende Einträge speichern automatisch, neue erst mit „Anlegen“
  const auto = useAutoSave(
    form,
    (_changes, values) => officesApi.update(org.id, entry!.id, values),
    {
      enabled: entry !== null,
    },
  )

  // Neue Einträge vor dem Anlegen: beim Verlassen nachfragen (Gesamtaudit 01.11.)
  const { markSaved } = useChangesGuard(v, entry === null)

  function year(value: string) {
    return value ? Number(value) : null
  }

  return (
    <form
      className="subcard"
      onSubmit={(e) => {
        e.preventDefault()
        if (entry) {
          void auto.flush().then((ok) => ok && onDone())
          return
        }
        void form
          .submit(() => officesApi.create(org.id, v))
          .then((result) => {
            if (result) {
              markSaved()
              onDone()
            }
          })
      }}
    >
      <h3>{entry ? t('Eintrag bearbeiten') : t('Früheren Inhaber eintragen')}</h3>
      {entry && <SaveStatus auto={auto} />}
      <SelectField
        label={t('Amt')}
        value={String(v.role)}
        error={errors.role}
        onChange={(e) => set('role', Number(e.target.value))}
      >
        {offices.map((o) => (
          <option key={o.id} value={o.id}>
            {officeLabel(o)}
          </option>
        ))}
      </SelectField>
      <PersonField
        label={t('Inhaber')}
        person={v.person}
        name={v.name}
        onChange={(person, name) => form.setValues({ ...v, person, name })}
      />
      {errors.name && <Alert kind="error">{errors.name}</Alert>}
      {errors.person && <Alert kind="error">{errors.person}</Alert>}
      {v.person === null && (
        <Checkbox
          label={t('Name darf auf der Webseite erscheinen')}
          hint={t('Ohne Häkchen erscheint der Name nicht unter „Ämter“ auf der Webseite.')}
          checked={v.name_public}
          onChange={(checked) => set('name_public', checked)}
        />
      )}
      <div className="grid-2">
        <Field
          label={t('von (Jahr)')}
          type="number"
          min={1000}
          max={2999}
          value={v.from_year ?? ''}
          error={errors.from_year}
          onChange={(e) => set('from_year', year(e.target.value))}
        />
        <Field
          label={t('bis (Jahr)')}
          type="number"
          min={1000}
          max={2999}
          value={v.until_year ?? ''}
          error={errors.until_year}
          onChange={(e) => set('until_year', year(e.target.value))}
        />
      </div>
      {form.message?.kind === 'error' && <Alert kind="error">{form.message.text}</Alert>}
      <div className="button-row">
        <button type="submit" className="button button-primary" disabled={form.busy}>
          {entry ? t('Schließen') : t('Anlegen')}
        </button>
        {!entry && (
          <button type="button" className="button button-ghost" onClick={onCancel}>
            {t('Abbrechen')}
          </button>
        )}
      </div>
    </form>
  )
}

// --- Statistik ---

/**
 * Jahre im Amt, jahresgenau: „1955 bis 1972“ sind 17 Jahre, ein einzelnes Jahr zählt als
 * eines, heutige Inhaber bis zum laufenden Jahr. Mehrere Zeiträume derselben Person werden
 * vereinigt, damit gleichzeitige Ämter (oder Überschneidungen) nicht doppelt zählen.
 */
function years(holders: { from_year: number; until_year: number | null; current: boolean }[]) {
  const now = new Date().getFullYear()
  const spans = holders
    .map((h) => {
      const end = h.current ? now : (h.until_year ?? h.from_year)
      return [h.from_year, Math.max(end, h.from_year + 1)] as const
    })
    .sort((a, b) => a[0] - b[0])
  let total = 0
  let start = -Infinity
  let stop = -Infinity
  for (const [a, b] of spans) {
    if (a > stop) {
      if (stop > start) total += stop - start
      start = a
      stop = b
    } else stop = Math.max(stop, b)
  }
  if (stop > start) total += stop - start
  return total
}

interface Tally {
  key: string
  name: string
  years: number
  periods: string
  offices: string
  current: boolean
}

function tally(entries: { holder: OfficeHolder; office: Office }[]): Tally[] {
  const groups = new Map<string, { holder: OfficeHolder; office: Office }[]>()
  // Gleiche Person: verknüpfte Akte, sonst gleicher Name. Ein freier Eintrag ohne Akte
  // zählt zur Akte mit genau diesem Namen (z. B. „2006 bis 2015“ frei, heute mit Konto).
  const norm = (name: string) => name.trim().replace(/\s+/g, ' ').toLowerCase()
  const byName = new Map<string, string>()
  for (const e of entries) {
    if (e.holder.person !== null) byName.set(norm(e.holder.name), `p${e.holder.person}`)
  }
  for (const e of entries) {
    const key =
      e.holder.person !== null
        ? `p${e.holder.person}`
        : (byName.get(norm(e.holder.name)) ?? `n${norm(e.holder.name)}`)
    groups.set(key, [...(groups.get(key) ?? []), e])
  }
  return [...groups.entries()]
    .map(([key, list]) => ({
      key,
      name: list[list.length - 1].holder.name,
      years: years(list.map((e) => e.holder)),
      periods: list.map((e) => periodText(e.holder)).join(', '),
      offices: [...new Set(list.map((e) => officeLabel(e.office)))].join(', '),
      current: list.some((e) => e.holder.current),
    }))
    .sort((a, b) => b.years - a.years || a.name.localeCompare(b.name, 'de'))
}

function yearsText(n: number) {
  return n === 1 ? t('1 Jahr') : t('{n} Jahre', { n })
}

function StatsPanel() {
  const org = useActiveOrg()
  const offices = useLoad(() => officesApi.list(org.id), [org.id])
  const [boardOnly, setBoardOnly] = useState(false)

  if (offices.error) return <Alert kind="error">{offices.error}</Alert>
  if (!offices.data) return <p className="muted">{t('Lädt …')}</p>
  // Nur Ämter der eigenen Ebene, keine der Untereinheiten (Ralf 2026-10-31)
  const used = offices.data.filter((o) => o.unit === null && o.holders.length > 0)
  const people = tally(
    used
      .filter((o) => !boardOnly || o.is_board)
      .flatMap((o) => o.holders.map((holder) => ({ holder, office: o }))),
  )

  const personColumns: Column<Tally>[] = [
    { key: 'name', label: t('Name'), value: (tm) => tm.name },
    {
      key: 'years',
      label: t('Jahre insgesamt'),
      value: (tm) => tm.years,
      render: (tm) => yearsText(tm.years),
      numeric: true,
    },
    { key: 'offices', label: t('Ämter'), value: (tm) => tm.offices, optional: true },
    {
      key: 'current',
      label: t('heute im Amt'),
      value: (tm) => (tm.current ? 'ja' : ''),
      optional: true,
    },
  ]
  // Feste Breiten, damit die Spalten in allen Blöcken gleich stehen (Ralf 2026-10-31)
  const officeColumns: Column<Tally>[] = [
    { key: 'name', label: t('Name'), value: (tm) => tm.name, width: '40%' },
    {
      key: 'years',
      label: t('Jahre'),
      width: '9rem',
      value: (tm) => tm.years,
      render: (tm) => yearsText(tm.years),
      numeric: true,
    },
    { key: 'periods', label: t('Zeiträume'), value: (tm) => tm.periods, optional: true },
  ]

  return (
    <>
      <div className="card card-wide">
        <h2>{t('Personen nach Jahren im Amt')}</h2>
        <p className="muted small">
          {t(
            'Alle, die je ein Amt der eigenen Ebene hatten (ohne Ämter der Untereinheiten), nach der Zahl der Jahre insgesamt. Gezählt wird jahresgenau („1955 bis 1972“ sind 17 Jahre, ein einzelnes Jahr zählt als eines); wer mehrere Ämter gleichzeitig hatte, bekommt diese Jahre nur einmal. Gleiche Person heißt: dieselbe Mitgliedsakte, sonst derselbe Name.',
          )}
        </p>
        <Checkbox
          label={t('nur Vorstandsrollen zählen')}
          checked={boardOnly}
          onChange={(val) => setBoardOnly(val)}
        />
        <DataTable
          label={t('Personen nach Jahren im Amt')}
          rows={people}
          rowKey={(tm) => tm.key}
          columns={personColumns}
          initialSort={{ key: 'years', dir: 'desc' }}
          emptyText={t('Noch keine Amtsinhaber erfasst.')}
        />
      </div>
      {used.map((o) => (
        <div className="card card-wide" key={o.id}>
          <h2>{officeLabel(o)}</h2>
          <DataTable
            label={t('{x}: Inhaber nach Jahren', { x: officeLabel(o) })}
            rows={tally(o.holders.map((holder) => ({ holder, office: o })))}
            rowKey={(tm) => tm.key}
            columns={officeColumns}
            fixedLayout
            initialSort={{ key: 'years', dir: 'desc' }}
          />
        </div>
      ))}
    </>
  )
}

// --- Import ---

interface Decision {
  take: boolean
  person_id: number | null
}

function ImportPanel() {
  const org = useActiveOrg()
  const [rows, setRows] = useState<OfficeImportRow[] | null>(null)
  // Ein Schlüssel je Vorschau: nochmal „Übernehmen“ legt nichts doppelt an
  const [requestKey, setRequestKey] = useState(newRequestKey)
  const [newRoles, setNewRoles] = useState<string[]>([])
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function read(file: File) {
    setError(null)
    setResult(null)
    setBusy(true)
    try {
      const data = await officesApi.importPreview(org.id, file)
      setRows(data.rows)
      setRequestKey(newRequestKey())
      setNewRoles(data.new_roles)
      setDecisions(
        data.rows.map((r) => ({
          take: r.errors.length === 0 && !r.duplicate,
          person_id: r.person_id,
        })),
      )
    } catch (err) {
      setRows(null)
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  function decide(index: number, patch: Partial<Decision>) {
    setDecisions((all) => all.map((d, i) => (i === index ? { ...d, ...patch } : d)))
  }

  async function commit() {
    if (!rows) return
    setBusy(true)
    setError(null)
    try {
      const chosen = rows
        .map((r, i) => ({ r, d: decisions[i] }))
        .filter(({ r, d }) => d.take && r.errors.length === 0)
        .map(({ r, d }) => ({
          role: r.role,
          unit_id: r.unit_id,
          name: r.name,
          person_id: d.person_id,
          from_year: r.from_year as number,
          until_year: r.until_year as number,
        }))
      const res = await officesApi.importRows(org.id, chosen, requestKey)
      setResult(
        t('{created} Einträge übernommen.', { created: res.created }) +
          (res.roles_created.length
            ? t(
                ' Neu angelegte Ämter (Rollen ohne Rechte): {x}. Sie stehen noch nicht auf der Webseite; schaltet dafür in der Rolle „unter Ämter zeigen“ ein.',
                { x: res.roles_created.join(', ') },
              )
            : ''),
      )
      setRows(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const count = rows ? decisions.filter((d, i) => d.take && rows[i].errors.length === 0).length : 0

  return (
    <div className="card card-wide">
      <h2>{t('Frühere Amtsinhaber importieren')}</h2>
      <p className="muted small">
        {t('Excel- oder CSV-Datei mit den Spalten')} <strong>{t('Amt')}</strong>,{' '}
        <strong>{t('Name')}</strong>, <strong>von</strong> und <strong>bis</strong>{' '}
        {t(
          '(jeweils das Jahr; ohne „bis“ gilt nur das eine Jahr). Für Ämter einer Untereinheit (z. B. Zugführer) zusätzlich die Spalte',
        )}{' '}
        <strong>{t('Einheit')}</strong>{' '}
        {t(
          'mit ihrem Namen. HUBIplan schlägt zu jedem Namen passende Mitglieder vor, auch ehemalige; ohne Zuordnung bleibt es beim Namen. Unbekannte Ämter werden als Rollen ohne Rechte angelegt.',
        )}
      </p>
      <input
        type="file"
        accept=".xlsx,.xlsm,.csv,.txt"
        aria-label={t('Datei auswählen')}
        disabled={busy}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void read(file)
        }}
      />
      {error && <Alert kind="error">{error}</Alert>}
      {result && <Alert kind="success">{result}</Alert>}
      {rows && (
        <>
          {newRoles.length > 0 && (
            <Alert kind="info">
              {t('Neue Ämter werden angelegt:')} {newRoles.join(', ')}. Sie erscheinen nicht auf der
              Webseite, bis ihr in der Rolle „unter Ämter zeigen“ einschaltet.
            </Alert>
          )}
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>{t('Übernehmen')}</th>
                  <th>{t('Zeile')}</th>
                  <th>{t('Amt')}</th>
                  <th>{t('Zeitraum')}</th>
                  <th>{t('Name und Zuordnung')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.line} className={r.errors.length ? 'inactive' : undefined}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={t('Zeile {line} übernehmen', { line: r.line })}
                        checked={decisions[i].take}
                        disabled={r.errors.length > 0}
                        onChange={(e) => decide(i, { take: e.target.checked })}
                      />
                    </td>
                    <td>{r.line}</td>
                    <td>
                      {r.unit ? t('{role} ({unit})', { role: r.role, unit: r.unit }) : r.role}
                    </td>
                    <td>
                      {r.from_year === null
                        ? ''
                        : periodText({
                            from_year: r.from_year,
                            until_year: r.until_year,
                            current: false,
                          })}
                    </td>
                    <td>
                      {r.name}
                      {r.errors.length > 0 && (
                        <div className="field-error small">{r.errors.join(' ')}</div>
                      )}
                      {r.duplicate && <div className="muted small">{t('Schon vorhanden.')}</div>}
                      {r.name && (
                        <CandidateSelect
                          label={t('Zuordnung Zeile {line}', { line: r.line })}
                          candidates={r.candidates}
                          value={decisions[i].person_id}
                          onChange={(id) => decide(i, { person_id: id })}
                        />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="button-row">
            <button
              type="button"
              className="button button-primary"
              disabled={busy || count === 0}
              onClick={() => void commit()}
            >
              {count} {t('Einträge übernehmen')}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
