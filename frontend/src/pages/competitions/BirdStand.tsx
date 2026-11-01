// Vogelschießen am Stand (Konzept 5b und 5c): groß der Schütze, der dran ist, darunter die
// nächsten drei, Zähler und Pfänder. „Schuss“ zählt und springt weiter, „Pfand gefallen“
// wählt die Teile. Leertaste = Schuss, Ziffern = Pfand, Strg+Z = Rückgängig. Alles landet
// zuerst auf dem Gerät und geht auch ohne Empfang weiter.
import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { newRequestKey } from '../../api/client.ts'
import { drawFree, lot, project, refOf, sameStarter, type Ref } from '../../api/bird.ts'
import {
  foldName,
  PRESENCE_LABELS,
  type CompetitionDetail,
  type MemberChoice,
  type Presence,
  type StandApi,
  type Starter,
} from '../../api/competitions.ts'
import { StandFinish } from './StandFinish.tsx'
import { describe, useStandStore, type LocalStarter } from './standStore.ts'

export function BirdStand({
  api,
  comp,
  fullscreen = false,
  onDrawAll,
}: {
  api: StandApi
  comp: CompetitionDetail
  fullscreen?: boolean
  /** alle ohne Nummer auf einmal auslosen (nur angemeldet und online) */
  onDrawAll?: () => Promise<void>
}) {
  const [notice, setNotice] = useState<string | null>(null)
  const store = useStandStore(
    api,
    describe,
    (conflicts) =>
      setNotice(
        conflicts.map((c) => `${c.name}: ${c.note ?? ''} Neue Nummer ${c.number}`).join(' '),
      ),
    true,
  )

  const { local, setLocal, push, online, syncError, statusText } = store
  const [choosing, setChoosing] = useState<number[] | null>(null)
  const [big, setBig] = useState<{ name: string; number: number } | null>(null)
  const closed = (local.status ?? comp.status) === 'endgueltig'
  const view = useMemo(
    () => project(local.bird, local.ops, local.starters, comp.drop_out),
    [local.bird, local.ops, local.starters, comp.drop_out],
  )
  const starter = (ref: Ref | null | undefined) =>
    ref === null || ref === undefined ? undefined : local.starters.find((s) => sameStarter(s, ref))
  const current = starter(view.upcoming[0])
  const hanging = view.prizes.filter((p) => !p.fallen)
  const allowed = hanging
  const fixed = comp.fixed_order
  // alle Pfänder gefallen: kein Weiterschießen, nur noch Rückgängig und Abschluss
  const done = view.prizes.length > 0 && hanging.length === 0
  // feste Reihenfolge: ein Klick auf eine Nummer wählt dieses und alle davor
  const pick = (c: number[] | null, id: number): number[] => {
    if (!fixed) return c?.includes(id) ? c.filter((x) => x !== id) : [...(c ?? []), id]
    const upto = hanging.findIndex((p) => p.id === id)
    const ids = hanging.slice(0, upto + 1).map((p) => p.id)
    return c && c.length === ids.length && c.includes(id) ? ids.slice(0, -1) : ids
  }

  function shot(hits: number[] = []) {
    if (closed || !current || done) return
    const ref = refOf(current)
    const at = new Date().toISOString()
    push({ op: 'shot', starter: ref, hits, client_key: newRequestKey(), at })
    const names = view.prizes.filter((p) => hits.includes(p.id)).map((p) => p.name)
    setNotice(
      names.length
        ? `${current.name} schießt ${names.join(' und ')} ab (Schuss ${view.total + 1}).`
        : null,
    )
    setChoosing(null)
  }

  function undo() {
    if (closed || !view.last) return
    const last = view.last
    const pendingIndex = local.ops.findIndex(
      (o) => o.op === 'shot' && last.key !== null && o.client_key === last.key,
    )
    if (pendingIndex >= 0) {
      // Noch nicht abgeglichen: einfach aus der Warteschlange nehmen
      setLocal((l) => ({ ...l, ops: l.ops.filter((_, i) => i !== pendingIndex) }))
    } else {
      push({ op: 'undo', client_key: last.key })
    }
    setNotice(`Schuss ${last.number} zurückgenommen.`)
  }

  function setPresence(s: Starter, presence: Presence) {
    push({ op: 'starter_update', starter: refOf(s), presence }, (l) => ({
      ...l,
      starters: l.starters.map((x) => (sameStarter(x, refOf(s)) ? { ...x, presence } : x)),
    }))
  }

  // Tastatur am Laptop
  const keyRef = useRef<(e: KeyboardEvent) => void>(() => undefined)
  useEffect(() => {
    keyRef.current = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
      if (target?.tagName === 'BUTTON' && (e.key === ' ' || e.key === 'Enter')) return
      if (closed) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        undo()
      } else if (e.key === ' ' && !choosing) {
        e.preventDefault()
        shot()
      } else if (/^[1-9]$/.test(e.key)) {
        const p = allowed[Number(e.key) - 1]
        if (p) {
          e.preventDefault()
          setChoosing((c) => (c?.includes(p.id) ? c : pick(c, p.id)))
        }
      } else if (e.key === 'Enter' && choosing?.length) {
        e.preventDefault()
        shot(choosing)
      } else if (e.key === 'Escape') {
        setChoosing(null)
      }
    }
  })

  useEffect(() => {
    const handler = (e: KeyboardEvent) => keyRef.current(e)
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  return (
    <div className={`stand stand-bird${fullscreen ? ' stand-full' : ''}`}>
      <p
        className={`stand-sync ${store.pending ? 'stand-sync-wait' : 'stand-sync-ok'}`}
        role="status"
      >
        {online ? '' : 'Kein Empfang · '}
        {statusText}
      </p>
      {syncError && <p className="alert alert-error">{syncError}</p>}
      {closed && (
        <p className="alert alert-info">Der Wettbewerb ist endgültig, Eingaben sind gesperrt.</p>
      )}
      {big && (
        <div className="stand-draw-big" role="status">
          <span>{big.name}</span>
          <strong>{big.number}</strong>
          <button type="button" className="button" onClick={() => setBig(null)}>
            Weiter
          </button>
        </div>
      )}

      <div className="stand-current" aria-live="polite">
        {current ? (
          <>
            <span className="stand-lot">{current.number}</span>
            <span className="stand-current-name">
              <strong>{current.name}</strong>
              <span className="muted"> {current.unit_name || current.club}</span>
            </span>
          </>
        ) : (
          <span className="muted">
            {local.starters.length
              ? 'Niemand in der Reihenfolge: Losnummern fehlen oder alle sind ausgeschieden.'
              : 'Noch keine Schützen. Unten unter „Schützen und Losnummern“ hinzufügen.'}
          </span>
        )}
      </div>
      {view.upcoming.length > 1 && (
        <ol className="stand-next">
          {view.upcoming.slice(1).map((ref) => {
            const s = starter(ref)
            return s ? (
              <li key={String(ref)}>
                <span className="stand-lot-small">{s.number}</span> {s.name}
                <span className="muted"> {s.unit_name || s.club}</span>
              </li>
            ) : null
          })}
        </ol>
      )}
      <p className="stand-counter">
        Schuss Nr. <strong>{view.total}</strong> · für dieses Pfand{' '}
        <strong>{view.sinceLast}</strong>
        {view.round ? (
          <>
            {' '}
            · Runde <strong>{view.round}</strong>
          </>
        ) : null}
      </p>

      {notice && (
        <p className="stand-notice" role="status">
          {notice}
        </p>
      )}

      {!closed && choosing && (
        <div className="stand-choose" role="group" aria-label="Gefallene Pfänder wählen">
          <p className="stand-label">
            Welche Pfänder sind gefallen? ({current?.name})
            {fixed && <span className="muted small"> Feste Reihenfolge: bis wohin?</span>}
          </p>
          <div className="stand-prize-buttons">
            {allowed.map((p, i) => (
              <button
                key={p.id}
                type="button"
                aria-pressed={choosing.includes(p.id)}
                className={`button stand-prize${choosing.includes(p.id) ? '' : ' button-ghost'}`}
                onClick={() => setChoosing((c) => pick(c, p.id))}
              >
                {i < 9 ? `${i + 1} · ` : ''}
                {p.name}
              </button>
            ))}
          </div>
          <div className="button-row">
            <button
              type="button"
              className="button"
              disabled={!choosing.length}
              onClick={() => shot(choosing)}
            >
              Speichern
            </button>
            <button type="button" className="button button-ghost" onClick={() => setChoosing(null)}>
              Abbrechen
            </button>
          </div>
        </div>
      )}

      {!closed && done && (
        <div className="stand-done" role="status">
          <p className="alert alert-success">
            Alle Pfänder sind gefallen. Jetzt den Wettbewerb abschließen oder, falls nötig, den
            letzten Schuss zurücknehmen.
          </p>
          <StandFinish
            api={api}
            comp={comp}
            pending={store.pending}
            online={online}
            onFinished={() => setLocal((l) => ({ ...l, status: 'endgueltig' }))}
          />
          <div className="button-row">
            <button
              type="button"
              className="button button-ghost"
              disabled={!view.last}
              onClick={undo}
            >
              Rückgängig
            </button>
          </div>
        </div>
      )}

      {!closed && !choosing && !done && (
        <div className="button-row stand-buttons stand-bird-buttons">
          <button
            type="button"
            className="button stand-shot"
            disabled={!current}
            onClick={() => shot()}
          >
            Schuss
          </button>
          {fixed && hanging[0] ? (
            <>
              {/* feste Reihenfolge: das nächste Pfand mit einem Klick */}
              <button
                type="button"
                className="button"
                disabled={!current}
                onClick={() => shot([hanging[0].id])}
              >
                {hanging[0].name} gefallen
              </button>
              {hanging.length > 1 && (
                <button
                  type="button"
                  className="button button-ghost"
                  disabled={!current}
                  onClick={() => setChoosing([hanging[0].id, hanging[1].id])}
                >
                  mehrere auf einmal
                </button>
              )}
            </>
          ) : (
            <button
              type="button"
              className="button"
              disabled={!current || !allowed.length}
              onClick={() => setChoosing([])}
            >
              Pfand gefallen
            </button>
          )}
          <button
            type="button"
            className="button button-ghost"
            disabled={!current}
            onClick={() => current && setPresence(current, 'fehlt')}
          >
            Schütze fehlt
          </button>
          <button
            type="button"
            className="button button-ghost"
            disabled={!view.last}
            onClick={undo}
          >
            Rückgängig
          </button>
        </div>
      )}

      <h2 className="stand-h">Pfänder</h2>
      <ul className="stand-prizes">
        {view.prizes.map((p) => (
          <li key={p.id} className={p.fallen ? 'fallen' : ''}>
            <strong>{p.name}</strong>
            {p.fallen ? (
              <span>
                {' '}
                {p.winner_name}
                {p.unit_name || p.club ? ` (${p.unit_name || p.club})` : ''} · Schuss{' '}
                {p.shot_number}, {p.shots_for} für das Pfand
              </span>
            ) : (
              <span className="muted"> hängt noch</span>
            )}
          </li>
        ))}
      </ul>

      <details className="stand-section" open={!fullscreen || !local.starters.length || undefined}>
        <summary>Schützen und Losnummern ({local.starters.length})</summary>
        {!closed && (
          <AddShooter
            starters={local.starters}
            lots={comp.lots}
            members={local.members}
            onAdd={(s, op, number, how) => {
              setLocal((l) => ({ ...l, starters: [...l.starters, s] }))
              push(op)
              if (number !== null) {
                push({ op: 'draw', starter: s.key as string, number, how }, (l) => ({
                  ...l,
                  starters: l.starters.map((x) =>
                    x.key === s.key ? { ...x, number: String(number) } : x,
                  ),
                }))
                if (how === 'digital') setBig({ name: s.name, number })
              }
            }}
          />
        )}
        <DrawReport starters={local.starters} gaps={!comp.lots} />
        {onDrawAll && !closed && local.starters.some((s) => lot(s.number) === null) && (
          <div className="button-row">
            <button
              type="button"
              className="button button-ghost"
              disabled={!online}
              onClick={() => void onDrawAll().then(() => store.sync(true))}
            >
              Alle ohne Nummer auslosen
            </button>
          </div>
        )}
        <ul className="stand-list">
          {[...local.starters]
            .sort(
              (a, b) =>
                (lot(a.number) ?? 1e9) - (lot(b.number) ?? 1e9) || a.name.localeCompare(b.name),
            )
            .map((s) => (
              <ShooterRow
                key={String(refOf(s))}
                s={s}
                closed={closed}
                winner={view.prizes.some(
                  (p) => p.winnerRef !== null && sameStarter(s, p.winnerRef),
                )}
                onDraw={(number, how) => {
                  const n = number ?? drawFree(local.starters, refOf(s), Math.random, comp.lots)
                  push({ op: 'draw', starter: refOf(s), number: n, how }, (l) => ({
                    ...l,
                    starters: l.starters.map((x) =>
                      sameStarter(x, refOf(s)) ? { ...x, number: String(n) } : x,
                    ),
                  }))
                  if (how === 'digital') setBig({ name: s.name, number: n })
                }}
                onPresence={(p) => setPresence(s, p)}
                taken={(n) =>
                  local.starters.find((x) => !sameStarter(x, refOf(s)) && lot(x.number) === n)
                }
              />
            ))}
        </ul>
      </details>
      {!closed && !done && (
        <StandFinish
          api={api}
          comp={comp}
          pending={store.pending}
          online={online}
          onFinished={() => setLocal((l) => ({ ...l, status: 'endgueltig' }))}
        />
      )}
    </div>
  )
}

function DrawReport({ starters, gaps: showGaps }: { starters: LocalStarter[]; gaps: boolean }) {
  const active = starters.filter((s) => s.presence !== 'zurueckgezogen')
  const missing = active.filter((s) => lot(s.number) === null)
  const numbers = active.map((s) => lot(s.number)).filter((n): n is number => n !== null)
  const top = Math.max(0, ...numbers)
  const gaps: number[] = []
  // mit Losen im Hut sind Lücken normal
  if (showGaps) for (let n = 1; n <= top; n += 1) if (!numbers.includes(n)) gaps.push(n)
  if (!missing.length && !gaps.length) return null
  return (
    <p className="muted">
      {missing.length ? `Ohne Losnummer: ${missing.map((s) => s.name).join(', ')}. ` : ''}
      {gaps.length ? `Nicht vergeben: ${gaps.join(', ')}.` : ''}
    </p>
  )
}

function ShooterRow({
  s,
  closed,
  winner,
  onDraw,
  onPresence,
  taken,
}: {
  s: LocalStarter
  closed: boolean
  winner: boolean
  onDraw: (number: number | null, how: 'hut' | 'digital') => void
  onPresence: (p: Presence) => void
  taken: (n: number) => Starter | undefined
}) {
  const [hat, setHat] = useState('')
  const [error, setError] = useState<string | null>(null)
  function save(e: FormEvent) {
    e.preventDefault()
    const n = lot(hat)
    if (n === null) {
      setError('Bitte eine Zahl ab 1.')
      return
    }
    const other = taken(n)
    if (other) {
      setError(`Nummer ${n} hat schon ${other.name}.`)
      return
    }
    setError(null)
    setHat('')
    onDraw(n, 'hut')
  }
  return (
    <li className="stand-shooter">
      <span className="stand-lot-small">{s.number || '–'}</span>{' '}
      <span>
        {s.name}
        <span className="muted"> {s.unit_name || s.club}</span>
        {winner ? <span className="badge"> Pfand</span> : null}
        {s.presence ? <span className="badge"> {PRESENCE_LABELS[s.presence]}</span> : null}
      </span>
      {!closed && (
        <span className="push-right stand-shooter-actions">
          {lot(s.number) === null && (
            <form className="stand-hat" onSubmit={save}>
              <input
                aria-label={`Losnummer aus dem Hut für ${s.name}`}
                inputMode="numeric"
                placeholder="Nr."
                value={hat}
                onChange={(e) => setHat(e.target.value)}
              />
              <button type="submit" className="button button-ghost">
                Eintragen
              </button>
              <button
                type="button"
                className="button button-ghost"
                onClick={() => onDraw(null, 'digital')}
              >
                Nummer ziehen
              </button>
            </form>
          )}
          <select
            aria-label={`Teilnahme von ${s.name}`}
            value={s.presence}
            onChange={(e) => onPresence(e.target.value as Presence)}
          >
            {Object.entries(PRESENCE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          {error && <span className="field-error">{error}</span>}
        </span>
      )}
    </li>
  )
}

type Pick = { kind: 'member'; member: MemberChoice } | { kind: 'guest'; name: string }

function AddShooter({
  starters,
  lots,
  members,
  onAdd,
}: {
  starters: LocalStarter[]
  lots: number | null
  members: MemberChoice[]
  onAdd: (
    s: LocalStarter,
    op: import('../../api/competitions.ts').SyncOp,
    number: number | null,
    how: 'hut' | 'digital',
  ) => void
}) {
  const [query, setQuery] = useState('')
  const [chosen, setChosen] = useState<Pick | null>(null)
  const [club, setClub] = useState('')
  const [hat, setHat] = useState('')
  const [error, setError] = useState<string | null>(null)
  const hits: Pick[] = useMemo(() => {
    const q = foldName(query.trim())
    if (!q) return []
    const words = q.split(/\s+/)
    const taken = new Set(starters.map((s) => s.membership).filter(Boolean))
    const found = members
      .filter((m) => !taken.has(m.membership))
      .filter((m) => words.every((w) => foldName(`${m.name} ${m.unit_name}`).includes(w)))
      .slice(0, 8)
      .map((m): Pick => ({ kind: 'member', member: m }))
    return [...found, { kind: 'guest', name: query.trim() }]
  }, [query, starters, members])

  function add(how: 'hut' | 'digital' | null) {
    if (!chosen) return
    let number: number | null = null
    if (how === 'hut') {
      number = lot(hat)
      if (number === null) {
        setError('Bitte die Nummer aus dem Hut eintragen.')
        return
      }
      const other = starters.find((s) => lot(s.number) === number)
      if (other) {
        setError(`Nummer ${number} hat schon ${other.name}.`)
        return
      }
    }
    const key = newRequestKey()
    const name = chosen.kind === 'member' ? chosen.member.name : chosen.name
    const s: LocalStarter = {
      id: 0,
      key,
      name,
      club: chosen.kind === 'guest' ? club.trim() : '',
      guest: chosen.kind === 'guest',
      membership: chosen.kind === 'member' ? chosen.member.membership : null,
      unit: chosen.kind === 'member' ? chosen.member.unit : null,
      unit_name: chosen.kind === 'member' ? chosen.member.unit_name : '',
      number: '',
      out_of_competition: false,
      presence: '',
      drawn_how: '',
      values: {},
    }
    const op =
      chosen.kind === 'member'
        ? { op: 'starter' as const, client_key: key, membership: chosen.member.membership }
        : { op: 'starter' as const, client_key: key, name, club: club.trim() }
    if (how === 'digital') number = drawFree([...starters, s], undefined, Math.random, lots)
    onAdd(s, op, number, how ?? 'hut')
    setChosen(null)
    setQuery('')
    setHat('')
    setClub('')
    setError(null)
  }

  if (chosen)
    return (
      <div className="stand-entry">
        <p className="stand-chosen">
          <strong>{chosen.kind === 'member' ? chosen.member.name : chosen.name}</strong>
          {chosen.kind === 'member' && chosen.member.unit_name
            ? ` · ${chosen.member.unit_name}`
            : ''}
          {chosen.kind === 'guest' ? ' · neuer Gast' : ''}
        </p>
        {chosen.kind === 'guest' && (
          <label className="field">
            <span>Verein (optional)</span>
            <input className="stand-input" value={club} onChange={(e) => setClub(e.target.value)} />
          </label>
        )}
        <label className="field">
          <span>Nummer aus dem Hut</span>
          <input
            className="stand-input"
            inputMode="numeric"
            autoFocus
            value={hat}
            onChange={(e) => setHat(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                add(hat.trim() ? 'hut' : null)
              }
            }}
          />
        </label>
        {error && <p className="field-error">{error}</p>}
        <div className="button-row">
          <button type="button" className="button" onClick={() => add(hat.trim() ? 'hut' : null)}>
            {hat.trim() ? 'Mit dieser Nummer hinzufügen' : 'Ohne Nummer hinzufügen'}
          </button>
          <button type="button" className="button button-ghost" onClick={() => add('digital')}>
            Nummer ziehen
          </button>
          <button type="button" className="button button-ghost" onClick={() => setChosen(null)}>
            Abbrechen
          </button>
        </div>
      </div>
    )
  return (
    <div className="stand-entry">
      <label className="stand-label" htmlFor="vogel-suche">
        Schütze hinzufügen (Name)
      </label>
      <input
        id="vogel-suche"
        className="stand-input"
        autoComplete="off"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && hits.length) {
            e.preventDefault()
            setChosen(hits[0])
          }
        }}
      />
      {hits.length > 0 && (
        <ul className="stand-hits" role="listbox">
          {hits.map((h) => (
            <li
              key={h.kind === 'member' ? `m-${h.member.membership}` : 'gast'}
              role="option"
              aria-selected={false}
            >
              <button type="button" className="stand-hit" onClick={() => setChosen(h)}>
                {h.kind === 'member' ? (
                  <>
                    <strong>{h.member.name}</strong>
                    <span className="muted"> {h.member.unit_name}</span>
                  </>
                ) : (
                  <>
                    Neu: <strong>„{h.name}“</strong> als Gast hinzufügen
                  </>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
