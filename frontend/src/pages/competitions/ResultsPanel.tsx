// Auswertung: Ranglisten je Wertung mit Preisplätzen, offene Stechen, Kennzahlen, Ausgaben.
import { useState } from 'react'
import {
  competitionsApi,
  showValue,
  type CompetitionDetail,
  type ShootOff,
  type ShootOffEntry,
  type StandingBlock,
  type Stats,
} from '../../api/competitions.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, useLoad } from '../../components/forms.ts'
import { Alert, LoadError } from '../../components/ui.tsx'

export function ResultsPanel({
  org,
  comp,
  onChanged,
}: {
  org: number
  comp: CompetitionDetail
  onChanged: () => void
}) {
  const standings = useLoad(() => competitionsApi.standings(org, comp.id), [org, comp.id])
  const shootoffs = useLoad(() => competitionsApi.shootoffs(org, comp.id), [org, comp.id])
  const [message, setMessage] = useState<string | null>(null)
  const closed = comp.status === 'endgueltig'

  function reload() {
    void standings.reload()
    void shootoffs.reload()
  }

  async function startShootoff(scoring: number, keys: string[]) {
    try {
      await competitionsApi.createShootoff(org, comp.id, scoring, keys)
      reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  if (standings.error) return <LoadError message={standings.error} onRetry={reload} />
  const data = standings.data
  if (!data) return <p className="muted">Wird geladen …</p>
  const exp = (q: string) => competitionsApi.exportUrl(org, comp.id, q)

  return (
    <>
      <div className="button-row">
        <a className="button button-ghost" href={exp('als=pdf')} target="_blank" rel="noreferrer">
          Ergebnisliste (PDF)
        </a>
        <a className="button button-ghost" href={exp('als=xlsx')}>
          Excel
        </a>
        <button type="button" className="button button-ghost" onClick={reload}>
          Aktualisieren
        </button>
      </div>
      {message && <Alert kind="error">{message}</Alert>}
      {data.open_shootoffs > 0 && (
        <Alert kind="info">
          Gleichstand auf Preisplätzen: Stechen nötig. Erst danach lässt sich der Wettbewerb
          endgültig abschließen.
        </Alert>
      )}
      {data.scorings.map((block) => {
        const scoring = comp.scorings.find((s) => s.id === block.scoring)
        const own = (shootoffs.data ?? []).filter((so) => so.scoring === block.scoring)
        return (
          <div className="card card-wide" key={block.scoring}>
            <h2>{block.name}</h2>
            <StandingTable block={block} />
            {block.open.map((t) => (
              <div key={t.keys.join()} className="alert alert-info">
                <p>
                  Platz {t.place}: {t.names.join(', ')}{' '}
                  {t.shootoff ? `– ${t.shootoff}. Stechen läuft` : '– Stechen nötig'}
                </p>
                {!t.shootoff && !closed && (
                  <button
                    type="button"
                    className="button"
                    onClick={() => void startShootoff(block.scoring, t.keys)}
                  >
                    Stechen anlegen
                  </button>
                )}
              </div>
            ))}
            {own.map((so) => (
              <ShootOffCard
                key={so.id}
                org={org}
                comp={comp}
                so={so}
                decimals={
                  (block.kind === 'einheit'
                    ? comp.scorings.find((s) => s.id === scoring?.source)?.decimals
                    : scoring?.decimals) ?? 0
                }
                closed={closed}
                onChanged={reload}
              />
            ))}
            {block.without_value.length > 0 && (
              <p className="muted small">
                Ohne Ergebnis: {block.without_value.map((w) => w.name).join(', ')}
              </p>
            )}
          </div>
        )
      })}
      {'count' in data.stats && <StatsCard stats={data.stats as Stats} />}
      <p className="muted small">
        Zustand ändern und abschließen unter „Einrichten“.{' '}
        <button type="button" className="link-button" onClick={onChanged}>
          Neu laden
        </button>
      </p>
    </>
  )
}

function StandingTable({ block }: { block: StandingBlock }) {
  const unit = block.kind === 'einheit'
  const hasShootoff = block.rows.some((r) => r.shootoff && Object.keys(r.shootoff).length)
  if (!block.rows.length) return <p className="muted">Noch keine Ergebnisse.</p>
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th className="num">Platz</th>
            <th>{unit ? 'Einheit' : 'Name'}</th>
            <th>{unit ? 'Schützen' : 'Einheit / Verein'}</th>
            {unit && <th>Bester Schütze</th>}
            <th className="num">Wert</th>
            {hasShootoff && <th className="num">Stechen</th>}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((r) => (
            <tr key={r.key} className={r.prize ? 'row-prize' : undefined}>
              <td className="num">{r.place ? `${r.place}.` : '–'}</td>
              <td>
                {r.name}
                {r.out_of_competition ? ' (außer Konkurrenz)' : ''}
                {r.guest ? <span className="muted"> · Gast</span> : null}
              </td>
              <td>{unit ? r.count : r.unit_name || r.club}</td>
              {unit && <td>{r.best}</td>}
              <td className="num">{r.value_text || <span className="muted">{r.reason}</span>}</td>
              {hasShootoff && (
                <td className="num">{Object.values(r.shootoff ?? {}).join(' / ')}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ShootOffCard({
  org,
  comp,
  so,
  decimals,
  closed,
  onChanged,
}: {
  org: number
  comp: CompetitionDetail
  so: ShootOff
  decimals: number
  closed: boolean
  onChanged: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const unitShootoff = so.entries.some((e) => e.unit !== null)

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

function StatsCard({ stats }: { stats: Stats }) {
  return (
    <div className="card card-wide">
      <h2>Kennzahlen</h2>
      <dl className="stats-list">
        <dt>Schützen</dt>
        <dd>
          {stats.count} ({stats.members} Mitglieder, {stats.guests} Gäste)
        </dd>
        <dt>Durchschnitt</dt>
        <dd>{stats.average}</dd>
        <dt>Höchster / niedrigster Wert</dt>
        <dd>
          {stats.max} / {stats.min}
        </dd>
      </dl>
      {stats.per_unit.length > 0 && (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Einheit</th>
                <th className="num">Schützen</th>
                <th className="num">Mitglieder</th>
                <th className="num">Beteiligung</th>
                <th className="num">Durchschnitt</th>
                <th className="num">Bester Wert</th>
              </tr>
            </thead>
            <tbody>
              {stats.per_unit.map((u) => (
                <tr key={u.unit}>
                  <td>{u.name}</td>
                  <td className="num">{u.count}</td>
                  <td className="num">{u.members}</td>
                  <td className="num">{u.participation !== null ? `${u.participation} %` : ''}</td>
                  <td className="num">{u.average}</td>
                  <td className="num">{u.best}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
