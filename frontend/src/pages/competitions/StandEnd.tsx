// Ende des Schießens im Standmodus (Ralf 2026-11-01): wer noch fehlt, „Schießen beenden“
// (vorläufig), Stechen anlegen und erfassen, dann endgültig abschließen. Stechen auch per
// Standzugang; Beenden und Abschluss nur angemeldet mit „Wettbewerbe verwalten“.
import { useEffect, useState } from 'react'
import {
  competitionsApi,
  type CompetitionDetail,
  type CompetitionStatus,
  type ShootOff,
  type StandApi,
  type Standings,
} from '../../api/competitions.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage } from '../../components/forms.ts'
import { ShootoffBlock } from './Shootoffs.tsx'
import { StandFinish } from './StandFinish.tsx'
import { useVersion } from './standStore.ts'

export function StandEnd({
  org,
  api,
  comp,
  status,
  pending,
  online,
  onStatus,
}: {
  /** angemeldet; ohne (Standzugang) kein „Schießen beenden“ */
  org?: number
  api: StandApi
  comp: CompetitionDetail
  status: CompetitionStatus
  pending: number
  online: boolean
  onStatus: (status: CompetitionStatus) => void
}) {
  const [data, setData] = useState<{
    standings: Pick<Standings, 'scorings' | 'open_shootoffs'>
    shootoffs: ShootOff[]
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  useVersion(api, () => setTick((t) => t + 1))

  useEffect(() => {
    let stop = false
    Promise.all([api.standings(), api.shootoffs.list()])
      .then(([standings, shootoffs]) => {
        if (!stop) setData({ standings, shootoffs })
      })
      .catch(() => undefined) // ohne Empfang bleibt der letzte Stand stehen
    return () => {
      stop = true
    }
  }, [api, tick])

  if (status === 'endgueltig' || !data) return null
  const reload = () => setTick((t) => t + 1)
  const blocks = data.standings.scorings
  const missing = [
    ...new Set(
      blocks.filter((b) => b.kind === 'einzel').flatMap((b) => b.without_value.map((w) => w.name)),
    ),
  ]
  const ended = status === 'vorlaeufig'
  const ties = blocks.filter(
    (b) => b.open.length || data.shootoffs.some((so) => so.scoring === b.scoring),
  )

  async function endShooting() {
    const ok = await confirmDialog({
      title: 'Schießen beenden',
      message: missing.length
        ? `Noch ohne Ergebnis: ${missing.join(', ')}. Trotzdem beenden? Die Ergebnisse gelten dann als vorläufig; Nachträge und Stechen bleiben möglich.`
        : 'Die Ergebnisse gelten dann als vorläufig; Nachträge und Stechen bleiben möglich.',
      confirmLabel: 'Schießen beenden',
      danger: false,
    })
    if (!ok || org === undefined) return
    try {
      await competitionsApi.setStatus(org, comp.id, 'vorlaeufig')
      setError(null)
      onStatus('vorlaeufig')
      reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <>
      {ties.length > 0 && (
        <section className="stand-block stand-end" aria-label="Stechen">
          <h2 className="stand-h">Stechen</h2>
          {ties.map((block) => (
            <div key={block.scoring} className="stand-shootoffs">
              <h3>{block.name}</h3>
              <ShootoffBlock
                api={api.shootoffs}
                comp={comp}
                block={block}
                shootoffs={data.shootoffs.filter((so) => so.scoring === block.scoring)}
                closed={false}
                onChanged={reload}
              />
            </div>
          ))}
        </section>
      )}
      <section className="stand-block stand-end" aria-label="Abschluss">
        <h2 className="stand-h">Abschluss</h2>
        <p className="muted">
          {missing.length
            ? `Noch ohne Ergebnis: ${missing.length} (${missing.join(', ')})`
            : 'Alle Schützen haben ein Ergebnis.'}
          {ended ? ' · Schießen beendet, Ergebnisse vorläufig.' : ''}
        </p>
        {error && <p className="alert alert-error">{error}</p>}
        {org !== undefined && comp.can_manage && !ended && (
          <div className="button-row">
            <button type="button" className="button" onClick={() => void endShooting()}>
              Schießen beenden
            </button>
          </div>
        )}
        {/* Schritt 2 erst nach „Schießen beenden“; über den Standzugang gibt es kein Beenden */}
        {(ended || org === undefined) && (
          <>
            {data.standings.open_shootoffs > 0 && (
              <p className="muted small">Erst die offenen Stechen entscheiden, dann abschließen.</p>
            )}
            <StandFinish
              api={api}
              comp={comp}
              pending={pending}
              online={online}
              onFinished={() => onStatus('endgueltig')}
            />
          </>
        )}
      </section>
    </>
  )
}
