// Stechen (Ralf 2026-11-01): bei Gleichstand auf einem Preisplatz anlegen, die Regeln
// (Schüsse, davon gewertet) vor Ort festlegen, Werte eintragen. Gleich in der Auswertung und
// im Standmodus.
import { useState } from 'react'
import {
  showValue,
  type CompetitionDetail,
  type ShootOff,
  type ShootoffApi,
  type ShootOffEntry,
  type StandingBlock,
} from '../../api/competitions.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, useLoad } from '../../components/forms.ts'
import { Alert } from '../../components/ui.tsx'
import { Why } from '../../learning/Aids.tsx'
import { t } from '../../i18n/index.ts'

type Rules = { shots: number | null; counted_shots: number | null }

const num = (v: string): number | null => (v.trim() ? Number(v) : null)

/** Offene Gleichstände einer Wertung mit „Stechen anlegen“ und die angelegten Stechen. */
export function ShootoffBlock({
  api,
  comp,
  block,
  shootoffs,
  closed,
  onChanged,
}: {
  api: ShootoffApi
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
      await api.create(block.scoring, keys, rules)
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
      {block.open.map((tm) => (
        <div key={tm.keys.join()} className="alert alert-info">
          <p>
            {t('Platz {place}:', { place: tm.place })} {tm.names.join(', ')}{' '}
            {tm.shootoff
              ? t('– {shootoff}. Stechen läuft', { shootoff: tm.shootoff })
              : t('– Stechen nötig')}
          </p>
          {!tm.shootoff &&
            !closed &&
            (creating === tm.keys.join() ? (
              <RulesForm
                initial={proposal}
                unit={unit}
                submitLabel={t('Stechen anlegen')}
                onSubmit={(rules) => void create(tm.keys, rules)}
                onCancel={() => setCreating(null)}
              />
            ) : (
              <div className="button-row">
                <button
                  type="button"
                  className="button"
                  onClick={() => setCreating(tm.keys.join())}
                >
                  {t('Stechen anlegen …')}
                </button>
              </div>
            ))}
        </div>
      ))}
      {shootoffs.map((so) => (
        <ShootOffCard
          key={so.id}
          api={api}
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
          <span>{t('Schüsse im Stechen')}</span>
          <input
            type="number"
            min={1}
            value={shots}
            onChange={(e) => setShots(e.target.value)}
            placeholder={t('ohne feste Zahl')}
          />
        </label>
        {!unit && (
          <label className="field">
            <span>{t('davon gewertet')}</span>
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
      <Why k="comp_shootoff_rules" />
      <div className="button-row">
        <button type="submit" className="button button-primary">
          {submitLabel}
        </button>
        <button type="button" className="button button-ghost" onClick={onCancel}>
          {t('Abbrechen')}
        </button>
      </div>
    </form>
  )
}

function ShootOffCard({
  api,
  comp,
  so,
  unit,
  decimals,
  closed,
  onChanged,
}: {
  api: ShootoffApi
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
      await api.update(so.id, rules)
      setEditing(false)
      setError(null)
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function save(entry: ShootOffEntry, data: { value?: string | null; membership?: number }) {
    try {
      await api.updateEntry(entry.id, data)
      setError(null)
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function remove() {
    const ok = await confirmDialog({
      title: t('Stechen entfernen'),
      message: t('{number}. Stechen mit allen Werten entfernen?', { number: so.number }),
      confirmLabel: t('Entfernen'),
    })
    if (!ok) return
    try {
      await api.remove?.(so.id)
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
          {so.shots ? t(' · {shots} Schuss', { shots: so.shots }) : ''}
          {so.counted_shots && so.counted_shots !== so.shots
            ? t(', davon {counted_shots} gewertet', { counted_shots: so.counted_shots })
            : ''}
        </h3>
        {api.printUrl && (
          <a
            className="button button-ghost push-right"
            href={api.printUrl(so.id)}
            target="_blank"
            rel="noreferrer"
          >
            {t('Stechliste (PDF)')}
          </a>
        )}
      </div>
      {error && <Alert kind="error">{error}</Alert>}
      {editing && (
        <RulesForm
          initial={so}
          unit={unit}
          submitLabel={t('Regeln speichern')}
          onSubmit={(rules) => void setRules(rules)}
          onCancel={() => setEditing(false)}
        />
      )}
      <table className="table">
        <thead>
          <tr>
            {unitShootoff && <th>{t('Einheit')}</th>}
            <th>{t('Schütze')}</th>
            <th className="num">{t('Wert')}</th>
          </tr>
        </thead>
        <tbody>
          {so.entries.map((e) => (
            <tr key={e.id}>
              {unitShootoff && <td>{comp.units.find((u) => u.id === e.unit)?.name}</td>}
              <td>
                {unitShootoff && !closed ? (
                  <UnitShooter
                    api={api}
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
                  aria-label={t('Wert im Stechen für {name}', { name: e.name })}
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
              {t('Regeln ändern')}
            </button>
          )}
          {api.remove && (
            <button type="button" className="button button-ghost" onClick={() => void remove()}>
              {t('Stechen entfernen')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function UnitShooter({
  api,
  entry,
  onPick,
}: {
  api: ShootoffApi
  entry: ShootOffEntry
  onPick: (membership: number) => void
}) {
  const { data } = useLoad(
    () => (entry.unit ? api.unitMembers(entry.unit) : Promise.resolve([])),
    [api, entry.unit],
  )
  return (
    <select
      className="inline-edit"
      aria-label={t('Schütze im Stechen')}
      value={entry.membership ?? ''}
      onChange={(e) => e.target.value && onPick(Number(e.target.value))}
    >
      <option value="">{entry.membership ? entry.name : t('bitte wählen')}</option>
      {(data ?? []).map((m) => (
        <option key={m.membership} value={m.membership}>
          {m.name}
        </option>
      ))}
    </select>
  )
}
