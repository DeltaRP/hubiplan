// Fremder Wettbewerb (Konzept 4 und 7): eigene Schützen und Mannschaften mit dem Platz und
// Wert, den der Ausrichter vergeben hat. Die Verbindung zu den Meldungen folgt später.
import { useMemo, useState } from 'react'
import {
  competitionsApi,
  foldName,
  showValue,
  type CompetitionDetail,
  type Scoring,
  type StandingBlock,
  type Starter,
  type Team,
} from '../../api/competitions.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, useLoad } from '../../components/forms.ts'
import { Alert, LoadError } from '../../components/ui.tsx'

export function ForeignPanel({ org, comp }: { org: number; comp: CompetitionDetail }) {
  const starters = useLoad(() => competitionsApi.starters(org, comp.id), [org, comp.id])
  const teams = useLoad(() => competitionsApi.teams(org, comp.id), [org, comp.id])
  const standings = useLoad(() => competitionsApi.standings(org, comp.id), [org, comp.id])
  const members = useLoad(() => competitionsApi.members(org, comp.id), [org, comp.id])
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const closed = comp.status === 'endgueltig'

  function reload() {
    void starters.reload()
    void teams.reload()
    void standings.reload()
  }

  async function run(action: () => Promise<unknown>) {
    try {
      await action()
      setError(null)
      reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const hits = useMemo(() => {
    const q = foldName(query.trim())
    if (!q || !members.data) return []
    const taken = new Set((starters.data ?? []).map((s) => s.membership))
    return members.data
      .filter((m) => !taken.has(m.membership))
      .filter((m) => q.split(/\s+/).every((w) => foldName(`${m.name} ${m.unit_name}`).includes(w)))
      .slice(0, 8)
  }, [query, members.data, starters.data])

  if (starters.error) return <LoadError message={starters.error} onRetry={reload} />
  if (!starters.data || !teams.data || !standings.data)
    return <p className="muted">Wird geladen …</p>
  const blocks = standings.data.scorings

  return (
    <>
      {error && <Alert kind="error">{error}</Alert>}
      {!closed && (
        <div className="card card-wide">
          <h2>Eigene Schützen</h2>
          <label className="field">
            <span>Mitglied hinzufügen (Name)</span>
            <input value={query} autoComplete="off" onChange={(e) => setQuery(e.target.value)} />
          </label>
          {hits.length > 0 && (
            <ul className="stand-hits">
              {hits.map((m) => (
                <li key={m.membership}>
                  <button
                    type="button"
                    className="stand-hit"
                    onClick={() =>
                      void run(() =>
                        competitionsApi.addStarter(org, comp.id, { membership: m.membership }),
                      ).then(() => setQuery(''))
                    }
                  >
                    <strong>{m.name}</strong>
                    <span className="muted"> {m.unit_name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="muted small">
            {starters.data.length
              ? starters.data.map((s) => s.name).join(', ')
              : 'Noch niemand eingetragen.'}
          </p>
        </div>
      )}
      {comp.scorings.some((s) => s.kind === 'mannschaft') && (
        <TeamsCard
          org={org}
          comp={comp}
          teams={teams.data}
          starters={starters.data}
          closed={closed}
          run={run}
        />
      )}
      {comp.scorings.map((sc) => {
        const block = blocks.find((b) => b.scoring === sc.id)
        return block ? (
          <PlacingCard
            key={sc.id}
            org={org}
            comp={comp}
            scoring={sc}
            block={block}
            closed={closed}
            onSaved={reload}
          />
        ) : null
      })}
    </>
  )
}

function TeamsCard({
  org,
  comp,
  teams,
  starters,
  closed,
  run,
}: {
  org: number
  comp: CompetitionDetail
  teams: Team[]
  starters: Starter[]
  closed: boolean
  run: (a: () => Promise<unknown>) => Promise<void>
}) {
  return (
    <div className="card card-wide">
      <h2>Mannschaften</h2>
      {teams.map((tm) => (
        <fieldset key={tm.id} className="team-box" disabled={closed}>
          <legend>
            <input
              aria-label="Name der Mannschaft"
              defaultValue={tm.name}
              onBlur={(e) => {
                const v = e.target.value.trim()
                if (v && v !== tm.name)
                  void run(() => competitionsApi.updateTeam(org, comp.id, tm.id, { name: v }))
              }}
            />
          </legend>
          <div className="checkbox-grid">
            {starters.map((s) => (
              <label key={s.id} className="checkbox">
                <input
                  type="checkbox"
                  checked={tm.members.includes(s.id)}
                  onChange={(e) =>
                    void run(() =>
                      competitionsApi.updateTeam(org, comp.id, tm.id, {
                        members: e.target.checked
                          ? [...tm.members, s.id]
                          : tm.members.filter((x) => x !== s.id),
                      }),
                    )
                  }
                />{' '}
                {s.name}
              </label>
            ))}
          </div>
          {!closed && (
            <div className="button-row">
              <button
                type="button"
                className="button button-ghost"
                onClick={async () => {
                  const ok = await confirmDialog({
                    title: 'Mannschaft entfernen',
                    message: `„${tm.name}“ mit Platz und Wert entfernen?`,
                    confirmLabel: 'Entfernen',
                  })
                  if (ok) await run(() => competitionsApi.removeTeam(org, comp.id, tm.id))
                }}
              >
                Mannschaft entfernen
              </button>
            </div>
          )}
        </fieldset>
      ))}
      {!closed && (
        <div className="button-row">
          <button
            type="button"
            className="button button-ghost"
            onClick={() => void run(() => competitionsApi.addTeam(org, comp.id))}
          >
            Mannschaft hinzufügen
          </button>
        </div>
      )}
    </div>
  )
}

function PlacingCard({
  org,
  comp,
  scoring,
  block,
  closed,
  onSaved,
}: {
  org: number
  comp: CompetitionDetail
  scoring: Scoring
  block: StandingBlock
  closed: boolean
  onSaved: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const team = scoring.kind === 'mannschaft'

  async function save(row: StandingBlock['rows'][number], form: HTMLElement) {
    const get = (name: string) =>
      (form.querySelector(`[name="${name}"]`) as HTMLInputElement | null)?.value ?? ''
    const old = {
      place: row.place ? String(row.place) : '',
      value: row.value ? showValue(row.value, scoring.decimals) : '',
      note: row.note ?? '',
    }
    if (
      get('place').trim() === old.place &&
      get('value').trim() === old.value &&
      get('note').trim() === old.note
    )
      return
    try {
      await competitionsApi.setPlacing(org, comp.id, {
        scoring: scoring.id,
        ...(team ? { team: row.team } : { starter: row.starter }),
        place: get('place'),
        value: get('value').replace(',', '.'),
        note: get('note'),
      })
      setError(null)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="card card-wide">
      <h2>{scoring.name}</h2>
      {scoring.field_size ? (
        <p className="muted">{scoring.field_size} Teilnehmer insgesamt</p>
      ) : (
        <p className="muted">Teilnehmerzahl insgesamt unter „Einrichten“ (für „Platz 2 von 14“).</p>
      )}
      {!block.rows.length ? (
        <p className="muted">{team ? 'Noch keine Mannschaft.' : 'Noch keine Schützen.'}</p>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>{team ? 'Mannschaft' : 'Name'}</th>
                <th className="num">Platz</th>
                <th className="num">Wert</th>
                <th>Bemerkung</th>
              </tr>
            </thead>
            <tbody>
              {block.rows.map((r) => (
                <tr
                  key={`${r.key}-${r.place}-${r.value_text}-${r.note}`}
                  onBlur={(e) => {
                    // Speichern, wenn die Zeile verlassen wird
                    const row = e.currentTarget
                    if (!row.contains(e.relatedTarget as Node | null)) void save(r, row)
                  }}
                >
                  <td>
                    {r.name}
                    {team && r.members?.length ? (
                      <span className="muted small"> ({r.members.join(', ')})</span>
                    ) : null}
                  </td>
                  <td className="num">
                    <input
                      name="place"
                      aria-label={`Platz ${r.name}`}
                      className="input-narrow"
                      inputMode="numeric"
                      disabled={closed}
                      defaultValue={r.place ?? ''}
                    />
                  </td>
                  <td className="num">
                    <input
                      name="value"
                      aria-label={`Wert ${r.name}`}
                      className="input-narrow"
                      inputMode="decimal"
                      disabled={closed}
                      defaultValue={r.value ? showValue(r.value, scoring.decimals) : ''}
                    />
                  </td>
                  <td>
                    <input
                      name="note"
                      aria-label={`Bemerkung ${r.name}`}
                      disabled={closed}
                      defaultValue={r.note ?? ''}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}
