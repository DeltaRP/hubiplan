// Stechen (Ralf 2026-11-01): bei Gleichstand auf einem Preisplatz anlegen, die Regeln
// (Schüsse, davon gewertet) vor Ort festlegen, Werte eintragen. Gleich in der Auswertung und
// im Standmodus.
import { useState } from 'react'
import {
  competitionsApi,
  showValue,
  type CompetitionDetail,
  type ShootOff,
  type ShootOffEntry,
  type StandingBlock,
} from '../../api/competitions.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, useLoad } from '../../components/forms.ts'
import { Alert } from '../../components/ui.tsx'

type Rules = { shots: number | null; counted_shots: number | null }

const num = (v: string): number | null => (v.trim() ? Number(v) : null)

/** Offene Gleichstände einer Wertung mit „Stechen anlegen“ und die angelegten Stechen. */
export function ShootoffBlock({
  org,
  comp,
  block,
  shootoffs,
  closed,
  onChanged,
}: {
  org: number
  comp: CompetitionDetail
  block: StandingBlock
  shootoffs: ShootOff[]
  closed: boolean
  onChanged: () => void
}) {
  const [creating, setCreating] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const scoring = comp.scorings.find((s) => s.id === block.scoring)
  const unit = block.kind === 'einheit'
  const decimals =
    (unit ? comp.scorings.find((s) => s.id === scoring?.source)?.decimals : scoring?.decimals) ?? 0
  // Vorschlag: wie im vorigen Stechen, sonst wie unter „Einrichten“
  const last = shootoffs.at(-1)
  const proposal: Rules = last
    ? { shots: last.shots, counted_shots: last.counted_shots }
    : {
        shots: scoring?.shootoff_shots ?? null,
        counted_shots: scoring?.shootoff_counted ?? null,
      }

  async function create(keys: string[], rules: Rules) {
    try {
      await competitionsApi.createShootoff(org, comp.id, block.scoring, keys, rules)
      setCreating(null)
      setError(null)
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <>
      {error && <Alert kind="error">{error}</Alert>}
      {block.open.map((t) => (
        <div key={t.keys.join()} className="alert alert-info">
          <p>
            Platz {t.place}: {t.names.join(', ')}{' '}
            {t.shootoff ? `– ${t.shootoff}. Stechen läuft` : '– Stechen nötig'}
          </p>
          {!t.shootoff &&
            !closed &&
            (creating === t.keys.join() ? (
              <RulesForm
                initial={proposal}
                unit={unit}
                submitLabel="Stechen anlegen"
                onSubmit={(rules) => void create(t.keys, rules)}
                onCancel={() => setCreating(null)}
              />
            ) : (
              <div className="button-row">
                <button type="button" className="button" onClick={() => setCreating(t.keys.join())}>
                  Stechen anlegen …
                </button>
              </div>
            ))}
        </div>
      ))}
      {shootoffs.map((so) => (
        <ShootOffCard
          key={so.id}
          org={org}
          comp={comp}
          so={so}
          unit={unit}
          decimals={decimals}
          closed={closed}
          onChanged={onChanged}
        />
      ))}
    </>
  )
}

function RulesForm({
  initial,
  unit,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: Rules
  unit: boolean
  submitLabel: string
  onSubmit: (rules: Rules) => void
  onCancel: () => void
}) {
  const [shots, setShots] = useState(initial.shots === null ? '' : String(initial.shots))
  const [counted, setCounted] = useState(
    initial.counted_shots === null ? '' : String(initial.counted_shots),
  )
  return (
    <form
      className="shootoff-rules"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit({ shots: num(shots), counted_shots: unit ? null : num(counted) })
      }}
    >
      <div className="grid-3">
        <label className="field">
          <span>Schüsse im Stechen</span>
          <input
            type="number"
            min={1}
            value={shots}
            onChange={(e) => setShots(e.target.value)}
            placeholder="ohne feste Zahl"
          />
        </label>
        {!unit && (
          <label className="field">
            <span>davon gewertet</span>
            <input
              type="number"
              min={1}
              value={counted}
              onChange={(e) => setCounted(e.target.value)}
              placeholder="alle"
            />
          </label>
        )}
      </div>
      <div className="button-row">
        <button type="submit" className="button button-primary">
          {submitLabel}
        </button>
        <button type="button" className="button button-ghost" onClick={onCancel}>
          Abbrechen
        </button>
      </div>
    </form>
  )
}

function ShootOffCard({
  org,
  comp,
  so,
  unit,
  decimals,
  closed,
  onChanged,
}: {
  org: number
  comp: CompetitionDetail
  so: ShootOff
  unit: boolean
  decimals: number
  closed: boolean
  onChanged: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const unitShootoff = so.entries.some((e) => e.unit !== null)
  const hasValues = so.entries.some((e) => e.value !== null)

  async function setRules(rules: Rules) {
    try {
      await competitionsApi.updateShootoff(org, comp.id, so.id, rules)
      setEditing(false)
      setError(null)
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function save(entry: ShootOffEntry, data: { value?: string | null; membership?: number }) {
    try {
      await competitionsApi.updateShootoffEntry(org, comp.id, entry.id, data)
      setError(null)
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function remove() {
    const ok = await confirmDialog({
      title: 'Stechen entfernen',
      message: `${so.number}. Stechen mit allen Werten entfernen?`,
      confirmLabel: 'Entfernen',
    })
    if (!ok) return
    try {
      await competitionsApi.removeShootoff(org, comp.id, so.id)
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>
          {so.number}. Stechen
          {so.shots ? ` · ${so.shots} Schuss` : ''}
          {so.counted_shots && so.counted_shots !== so.shots
            ? `, davon ${so.counted_shots} gewertet`
            : ''}
        </h3>
        <a
          className="button button-ghost push-right"
          href={competitionsApi.exportUrl(org, comp.id, `als=stechliste&stechen=${so.id}`)}
          target="_blank"
          rel="noreferrer"
        >
          Stechliste (PDF)
        </a>
      </div>
      {error && <Alert kind="error">{error}</Alert>}
      {editing && (
        <RulesForm
          initial={so}
          unit={unit}
          submitLabel="Regeln speichern"
          onSubmit={(rules) => void setRules(rules)}
          onCancel={() => setEditing(false)}
        />
      )}
      <table className="table">
        <thead>
          <tr>
            {unitShootoff && <th>Einheit</th>}
            <th>Schütze</th>
            <th className="num">Wert</th>
          </tr>
        </thead>
        <tbody>
          {so.entries.map((e) => (
            <tr key={e.id}>
              {unitShootoff && <td>{comp.units.find((u) => u.id === e.unit)?.name}</td>}
              <td>
                {unitShootoff && !closed ? (
                  <UnitShooter
                    org={org}
                    comp={comp}
                    entry={e}
                    onPick={(m) => void save(e, { membership: m })}
                  />
                ) : (
                  e.name
                )}
              </td>
              <td className="num">
                <input
                  className="inline-edit num"
                  inputMode={decimals ? 'decimal' : 'numeric'}
                  aria-label={`Wert im Stechen für ${e.name}`}
                  defaultValue={showValue(e.value, decimals)}
                  disabled={closed}
                  onBlur={(ev) => {
                    const v = ev.target.value.trim().replace(',', '.')
                    if (v !== (e.value === null ? '' : String(Number(e.value))))
                      void save(e, { value: v || null })
                  }}
                  onKeyDown={(ev) => {
                    if (ev.key === 'Enter') (ev.target as HTMLInputElement).blur()
                  }}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!closed && (
        <div className="button-row">
          {!hasValues && !editing && (
            <button type="button" className="button button-ghost" onClick={() => setEditing(true)}>
              Regeln ändern
            </button>
          )}
          <button type="button" className="button button-ghost" onClick={() => void remove()}>
            Stechen entfernen
          </button>
        </div>
      )}
    </div>
  )
}

function UnitShooter({
  org,
  comp,
  entry,
  onPick,
}: {
  org: number
  comp: CompetitionDetail
  entry: ShootOffEntry
  onPick: (membership: number) => void
}) {
  const { data } = useLoad(
    () =>
      entry.unit ? competitionsApi.unitMembers(org, comp.id, entry.unit) : Promise.resolve([]),
    [org, comp.id, entry.unit],
  )
  return (
    <select
      className="inline-edit"
      aria-label="Schütze im Stechen"
      value={entry.membership ?? ''}
      onChange={(e) => e.target.value && onPick(Number(e.target.value))}
    >
      <option value="">{entry.membership ? entry.name : 'bitte wählen'}</option>
      {(data ?? []).map((m) => (
        <option key={m.membership} value={m.membership}>
          {m.name}
        </option>
      ))}
    </select>
  )
}
