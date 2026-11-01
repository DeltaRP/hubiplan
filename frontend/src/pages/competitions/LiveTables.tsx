// Live-Tabellen im Standmodus (Ralf 2026-11-01): rechts neben der Erfassung (auf dem Handy
// darunter) die Ranglisten aller Wertungen mit allen Plätzen, neu bei jeder Eingabe.
import { useEffect, useState } from 'react'
import type { StandApi, StandingBlock } from '../../api/competitions.ts'
import { useVersion } from './standStore.ts'

export function LiveTables({ api }: { api: StandApi }) {
  const [blocks, setBlocks] = useState<StandingBlock[] | null>(null)
  const [stale, setStale] = useState(false)
  const [tick, setTick] = useState(0)
  // neu laden, sobald irgendein Gerät etwas erfasst hat
  useVersion(api, () => setTick((t) => t + 1))

  useEffect(() => {
    let stop = false
    api
      .standings()
      .then((res) => {
        if (stop) return
        setBlocks(res.scorings)
        setStale(false)
      })
      .catch(() => {
        if (!stop) setStale(true) // ohne Empfang: letzter Stand bleibt stehen
      })
    return () => {
      stop = true
    }
  }, [api, tick])

  if (!blocks) return null
  return (
    <aside className="stand-live" aria-label="Aktuelle Tabellen">
      {stale && <p className="muted small">Ohne Empfang: Stand der letzten Abfrage.</p>}
      {blocks.map((b) => (
        <section key={b.scoring} className="stand-live-block">
          <h2>{b.name}</h2>
          {b.rows.length === 0 ? (
            <p className="muted small">Noch keine Werte.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th className="num">Platz</th>
                  <th>{b.kind === 'einheit' ? 'Einheit' : 'Name'}</th>
                  <th className="num">Wert</th>
                </tr>
              </thead>
              <tbody>
                {b.rows.map((r) => (
                  <tr key={r.key} className={r.prize ? 'stand-live-prize' : undefined}>
                    <td className="num">
                      {r.place ?? '–'}
                      {r.tie ? ' *' : ''}
                    </td>
                    <td>
                      {r.name}
                      {b.kind === 'einheit' ? (
                        r.reason ? (
                          <span className="muted small"> · {r.reason}</span>
                        ) : r.count !== undefined ? (
                          <span className="muted small"> · {r.count} Schützen</span>
                        ) : null
                      ) : (
                        (r.unit_name || r.club) && (
                          <span className="muted small"> · {r.unit_name || r.club}</span>
                        )
                      )}
                      {r.out_of_competition && <span className="muted small"> (a. K.)</span>}
                    </td>
                    <td className="num">{r.value_text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {b.open.length > 0 && <p className="muted small">* Gleichstand: Stechen nötig</p>}
        </section>
      ))}
    </aside>
  )
}
