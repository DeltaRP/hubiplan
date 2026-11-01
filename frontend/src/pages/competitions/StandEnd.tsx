// Ende des Schießens im Standmodus (Ralf 2026-11-01): wer noch fehlt, „Schießen beenden“
// (vorläufig), Stechen anlegen und erfassen, dann endgültig abschließen. Stechen auch per
// Standzugang; Beenden und Abschluss nur angemeldet mit „Wettbewerbe verwalten“.
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  competitionsApi,
  type CompetitionDetail,
  type CompetitionStatus,
  type StandApi,
  type SyncOp,
} from '../../api/competitions.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage } from '../../components/forms.ts'
import { ShootoffBlock } from './Shootoffs.tsx'
import { StandFinish } from './StandFinish.tsx'
import { mergeShootoffs, queuedShootoffApi, withLocalShootoffs } from './standShootoffs.ts'
import { useVersion, type Local } from './standStore.ts'

export function StandEnd({
  org,
  api,
  comp,
  status,
  pending,
  online,
  onStatus,
  local,
  setLocal,
  push,
}: {
  /** angemeldet; ohne (Standzugang) kein „Schießen beenden“ */
  org?: number
  api: StandApi
  comp: CompetitionDetail
  status: CompetitionStatus
  pending: number
  online: boolean
  onStatus: (status: CompetitionStatus) => void
  /** Speicher des Standmodus: Stechen gehen durch die Warteschlange (auch ohne Empfang) */
  local: Local
  setLocal: (change: (l: Local) => Local) => void
  push: (op: SyncOp) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  useVersion(api, () => setTick((t) => t + 1))
  const localRef = useRef(local)
  const pushRef = useRef(push)
  useEffect(() => {
    localRef.current = local
    pushRef.current = push
  })

  useEffect(() => {
    let stop = false
    api
      .standings()
      .then((standings) => {
        if (!stop) setLocal((l) => ({ ...l, standings }))
      })
      .catch(() => undefined) // ohne Empfang bleibt der letzte Stand auf dem Gerät
    return () => {
      stop = true
    }
  }, [api, tick, setLocal])

  const shootoffApi = useMemo(
    () =>
      queuedShootoffApi(
        api,
        () => localRef.current,
        (op) => pushRef.current(op),
        () => localRef.current.standings?.scorings ?? [],
      ),
    [api],
  )
  const standings = local.standings
  if (status === 'endgueltig' || !standings) return null
  const shootoffs = mergeShootoffs(local)
  const data = { standings, shootoffs }
  const reload = () => setTick((t) => t + 1)
  const blocks = standings.scorings.map((b) => withLocalShootoffs(b, shootoffs))
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
                api={shootoffApi}
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
