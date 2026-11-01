// Erfassen am Stand (Kartenschießen): Schützen kommen in beliebiger Reihenfolge mit ihrer
// Karte. Ein Suchfeld ist immer aktiv: Name oder Startnummer, Enter, Punkte, Enter.
// Alle Eingaben landen erst auf dem Gerät und gleichen sich bei Empfang selbst ab
// (Schießstände im Keller, Ralf 2026-11-01).
import { useMemo, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { newRequestKey } from '../../api/client.ts'
import {
  foldName,
  showValue,
  type CompetitionDetail,
  type MemberChoice,
  type Scoring,
  type StandApi,
  type Starter,
  type SyncOp,
} from '../../api/competitions.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { StandFinish } from './StandFinish.tsx'
import { describe, useStandStore } from './standStore.ts'

type Hit =
  | { kind: 'starter'; starter: Starter }
  | { kind: 'member'; member: MemberChoice }
  | { kind: 'guest'; name: string }

export function StandPanel({
  api,
  comp,
  fullscreen = false,
}: {
  api: StandApi
  comp: CompetitionDetail
  fullscreen?: boolean
}) {
  const scoring: Scoring | undefined = comp.scorings.find((s) => s.kind === 'einzel')
  const [notice, setNotice] = useState<string | null>(null)
  const { local, setLocal, push, online, syncError, pending, statusText } = useStandStore(
    api,
    describe,
    (conflicts) => {
      const values = conflicts.filter((c) => c.value !== undefined)
      const notes = conflicts.filter((c) => c.value === undefined && c.note)
      setNotice(
        [
          values.length
            ? `Auf einem anderen Gerät später geändert, dieser Wert gilt: ${values
                .map((c) => `${c.name} ${showValue(c.value, scoring?.decimals ?? 0)}`)
                .join(', ')}`
            : '',
          ...notes.map((c) => `${c.name} ${c.note}.`),
        ]
          .filter(Boolean)
          .join(' '),
      )
    },
    // auch ohne eigene Eingaben regelmäßig den Stand holen: Eingaben anderer Geräte
    // (Standmodus, Standzugang) erscheinen so ohne Neuladen
    true,
  )
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [chosen, setChosen] = useState<Hit | null>(null)
  const [points, setPoints] = useState('')
  const [guestClub, setGuestClub] = useState('')
  const searchRef = useRef<HTMLInputElement>(null)
  const pointsRef = useRef<HTMLInputElement>(null)
  const closed = (local.status ?? comp.status) === 'endgueltig'

  const hits: Hit[] = useMemo(() => {
    const q = foldName(query.trim())
    if (!q) return []
    const words = q.split(/\s+/)
    const match = (name: string, extra = '') => {
      const hay = foldName(`${name} ${extra}`)
      return words.every((w) => hay.includes(w))
    }
    const startersHit = local.starters
      .filter((s) => s.number === query.trim() || match(s.name, s.unit_name))
      .slice(0, 8)
      .map((s): Hit => ({ kind: 'starter', starter: s }))
    const taken = new Set(local.starters.map((s) => s.membership).filter(Boolean))
    const membersHit = local.members
      .filter((m) => !taken.has(m.membership) && match(m.name, m.unit_name))
      .slice(0, 8)
      .map((m): Hit => ({ kind: 'member', member: m }))
    return [...startersHit, ...membersHit, { kind: 'guest', name: query.trim() }]
  }, [query, local.starters, local.members])

  function choose(hit: Hit) {
    setChosen(hit)
    setPoints('')
    setGuestClub('')
    setTimeout(() => pointsRef.current?.focus(), 0)
  }

  function onSearchKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => Math.min(a + 1, hits.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, 0))
    } else if (e.key === 'Enter' && hits.length) {
      e.preventDefault()
      choose(hits[Math.min(active, hits.length - 1)])
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!chosen || !scoring) return
    const value = points.trim().replace(',', '.')
    if (value !== '' && !Number.isFinite(Number(value))) {
      setNotice('Bitte eine Zahl eingeben.')
      return
    }
    const max = scoring.max_per_shot
      ? Number(scoring.max_per_shot) * (scoring.counted_shots || scoring.shots || 0)
      : 0
    if (value !== '' && max && Number(value) > max) {
      setNotice(`Höchstens ${showValue(String(max), 0)}.`)
      return
    }
    let ref: number | string
    let name: string
    if (chosen.kind === 'starter') {
      const s = chosen.starter
      ref = s.key ?? s.id
      name = s.name
      const old = s.values[String(scoring.id)]
      if (old !== undefined && old !== '' && value !== '' && Number(old) !== Number(value)) {
        const ok = await confirmDialog({
          title: 'Schon erfasst',
          message: `${s.name} hat schon ${showValue(old, scoring.decimals)} ${scoring.unit_label}. Durch ${showValue(value, scoring.decimals)} ersetzen?`,
          confirmLabel: 'Ersetzen',
          danger: false,
        })
        if (!ok) return
      }
    } else {
      const key = newRequestKey()
      ref = key
      name = chosen.kind === 'member' ? chosen.member.name : chosen.name
      const starter: Starter & { key: string } = {
        id: 0,
        key,
        name,
        club: chosen.kind === 'guest' ? guestClub.trim() : '',
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
      const op: SyncOp =
        chosen.kind === 'member'
          ? { op: 'starter', client_key: key, membership: chosen.member.membership }
          : { op: 'starter', client_key: key, name, club: guestClub.trim() }
      setLocal((l) => ({ ...l, ops: [...l.ops, op], starters: [...l.starters, starter] }))
    }
    if (value !== '') {
      const at = new Date().toISOString()
      push({ op: 'score', starter: ref, scoring: scoring.id, value, at }, (l) => ({
        ...l,
        starters: l.starters.map((s) =>
          (s.key ?? s.id) === ref ? { ...s, values: { ...s.values, [scoring.id]: value } } : s,
        ),
        recent: [{ ref, name, value, at }, ...l.recent].slice(0, 10),
      }))
      setNotice(`${name}: ${showValue(value, scoring.decimals)} ${scoring.unit_label}`)
    } else {
      push(null)
      setNotice(`${name} eingetragen.`)
    }
    setChosen(null)
    setQuery('')
    setPoints('')
    setActive(0)
    setTimeout(() => searchRef.current?.focus(), 0)
  }

  function backToSearch() {
    setChosen(null)
    setQuery('')
    setPoints('')
    setTimeout(() => searchRef.current?.focus(), 0)
  }

  async function clearValue(s: Starter) {
    if (!scoring) return
    const ok = await confirmDialog({
      title: 'Wert löschen',
      message: `Den Wert von ${s.name} löschen? ${s.name} steht danach wieder unter „Noch offen“.`,
      confirmLabel: 'Löschen',
    })
    if (!ok) return
    const ref = s.key ?? s.id
    const at = new Date().toISOString()
    push({ op: 'score', starter: ref, scoring: scoring.id, value: null, at }, (l) => ({
      ...l,
      starters: l.starters.map((x) =>
        (x.key ?? x.id) === ref ? { ...x, values: { ...x.values, [scoring.id]: '' } } : x,
      ),
      recent: l.recent.filter((r) => r.ref !== ref),
    }))
    setNotice(`Wert von ${s.name} gelöscht.`)
    backToSearch()
  }

  async function removeStarter(s: Starter) {
    const ok = await confirmDialog({
      title: 'Aus dem Wettbewerb entfernen',
      message: `${s.name} mit allen Werten aus dem Wettbewerb entfernen?`,
      confirmLabel: 'Entfernen',
    })
    if (!ok) return
    const ref = s.key ?? s.id
    push({ op: 'starter_delete', starter: ref }, (l) => ({
      ...l,
      starters: l.starters.filter((x) => (x.key ?? x.id) !== ref),
      recent: l.recent.filter((r) => r.ref !== ref),
    }))
    setNotice(`${s.name} entfernt.`)
    backToSearch()
  }

  if (!scoring) return <p className="muted">Zuerst eine Einzelwertung anlegen.</p>

  const open = local.starters.filter((s) => !s.values[String(scoring.id)])
  // Zuletzt erfasst über alle Geräte: Zeitpunkt vom Server, dazu eigene noch nicht
  // abgeglichene Eingaben; je Schütze nur die letzte mit seinem aktuellen Wert
  const latest = new Map<number | string, { ref: number | string; name: string; at: string }>()
  for (const s of local.starters)
    if (s.scored_at && s.values[String(scoring.id)])
      latest.set(s.key ?? s.id, { ref: s.key ?? s.id, name: s.name, at: s.scored_at })
  for (const r of local.recent) {
    const known = latest.get(r.ref)
    if (!known || Date.parse(r.at) > Date.parse(known.at))
      latest.set(r.ref, { ref: r.ref, name: r.name, at: r.at })
  }
  const recent = [...latest.values()]
    .map((r) => {
      const s = local.starters.find((x) => (x.key ?? x.id) === r.ref)
      return { ...r, value: s?.values[String(scoring.id)] ?? '' }
    })
    .filter((r) => r.value !== '')
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
    .slice(0, 10)

  return (
    <div className={`stand${fullscreen ? ' stand-full' : ''}`}>
      <p className={`stand-sync ${pending ? 'stand-sync-wait' : 'stand-sync-ok'}`} role="status">
        {online ? '' : 'Kein Empfang · '}
        {statusText}
      </p>
      {syncError && <p className="alert alert-error">{syncError}</p>}
      {closed ? (
        <p className="alert alert-info">Der Wettbewerb ist endgültig, Eingaben sind gesperrt.</p>
      ) : (
        <form className="stand-entry" onSubmit={submit}>
          {!chosen ? (
            <>
              <label className="stand-label" htmlFor="stand-suche">
                Schütze (Name oder Startnummer)
              </label>
              <input
                id="stand-suche"
                ref={searchRef}
                className="stand-input"
                autoFocus
                autoComplete="off"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value)
                  setActive(0)
                }}
                onKeyDown={onSearchKey}
                aria-controls="stand-treffer"
              />
              {hits.length > 0 && (
                <ul id="stand-treffer" className="stand-hits" role="listbox">
                  {hits.map((h, i) => (
                    <li key={hitKey(h)} role="option" aria-selected={i === active}>
                      <button
                        type="button"
                        className={`stand-hit${i === active ? ' active' : ''}`}
                        onClick={() => choose(h)}
                      >
                        {hitLabel(h, scoring)}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <>
              <p className="stand-chosen">
                <strong>{hitName(chosen)}</strong>
                {chosen.kind === 'member' && chosen.member.unit_name
                  ? ` · ${chosen.member.unit_name}`
                  : ''}
                {chosen.kind === 'starter' && chosen.starter.unit_name
                  ? ` · ${chosen.starter.unit_name}`
                  : ''}
                {chosen.kind === 'guest' ? ' · neuer Gast' : ''}
              </p>
              {chosen.kind === 'guest' && (
                <>
                  <label className="stand-label" htmlFor="stand-verein">
                    Verein (optional)
                  </label>
                  <input
                    id="stand-verein"
                    className="stand-input"
                    value={guestClub}
                    onChange={(e) => setGuestClub(e.target.value)}
                  />
                </>
              )}
              <label className="stand-label" htmlFor="stand-punkte">
                {scoring.unit_label}
                {scoring.counted_shots ? ` (${scoring.counted_shots} gewertete Schuss)` : ''}
              </label>
              <input
                id="stand-punkte"
                ref={pointsRef}
                className="stand-input stand-points"
                inputMode={scoring.decimals ? 'decimal' : 'numeric'}
                autoComplete="off"
                value={points}
                onChange={(e) => setPoints(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') {
                    setChosen(null)
                    setTimeout(() => searchRef.current?.focus(), 0)
                  }
                }}
              />
              <div className="button-row stand-buttons">
                <button type="submit" className="button">
                  Speichern
                </button>
                <button
                  type="button"
                  className="button button-ghost"
                  onClick={() => {
                    setChosen(null)
                    setTimeout(() => searchRef.current?.focus(), 0)
                  }}
                >
                  Abbrechen
                </button>
              </div>
              {chosen.kind === 'starter' && (
                <div className="button-row stand-buttons">
                  {!!chosen.starter.values[String(scoring.id)] && (
                    <button
                      type="button"
                      className="button button-ghost"
                      onClick={() => void clearValue(chosen.starter)}
                    >
                      Wert löschen
                    </button>
                  )}
                  <button
                    type="button"
                    className="button button-ghost"
                    onClick={() => void removeStarter(chosen.starter)}
                  >
                    Aus dem Wettbewerb entfernen
                  </button>
                </div>
              )}
            </>
          )}
        </form>
      )}
      {notice && (
        <p className="stand-notice" role="status">
          {notice}
        </p>
      )}
      <details className="stand-section" open={!fullscreen || undefined}>
        <summary>Zuletzt erfasst ({recent.length})</summary>
        <ul className="stand-list">
          {recent.map((r) => (
            <li key={`${r.ref}-${r.at}`}>
              <button
                type="button"
                className="link-button"
                onClick={() => {
                  const s = local.starters.find((x) => (x.key ?? x.id) === r.ref)
                  if (s) choose({ kind: 'starter', starter: s })
                }}
              >
                {r.name}
              </button>{' '}
              <span className="push-right">{showValue(r.value, scoring.decimals)}</span>
            </li>
          ))}
        </ul>
      </details>
      <details className="stand-section">
        <summary>Noch offen ({open.length})</summary>
        <ul className="stand-list">
          {open.map((s) => (
            <li key={s.key ?? s.id}>
              <button
                type="button"
                className="link-button"
                onClick={() => choose({ kind: 'starter', starter: s })}
              >
                {s.name}
              </button>
              <span className="muted"> {s.unit_name || s.club}</span>
            </li>
          ))}
        </ul>
      </details>
      {!closed && (
        <StandFinish
          api={api}
          comp={comp}
          pending={pending}
          online={online}
          onFinished={() => setLocal((l) => ({ ...l, status: 'endgueltig' }))}
        />
      )}
    </div>
  )
}

function hitKey(h: Hit) {
  if (h.kind === 'starter') return `s-${h.starter.key ?? h.starter.id}`
  if (h.kind === 'member') return `m-${h.member.membership}`
  return 'gast'
}

function hitName(h: Hit) {
  if (h.kind === 'starter') return h.starter.name
  if (h.kind === 'member') return h.member.name
  return h.name
}

function hitLabel(h: Hit, scoring: Scoring) {
  if (h.kind === 'starter') {
    const v = h.starter.values[String(scoring.id)]
    return (
      <>
        <strong>{h.starter.name}</strong>
        <span className="muted"> {h.starter.unit_name || h.starter.club}</span>
        {v ? <span className="push-right">schon {showValue(v, scoring.decimals)}</span> : null}
      </>
    )
  }
  if (h.kind === 'member')
    return (
      <>
        <strong>{h.member.name}</strong>
        <span className="muted">
          {' '}
          {h.member.unit_name}
          {h.member.birth_year ? ` · ${h.member.birth_year}` : ''}
        </span>
        <span className="push-right muted">neu</span>
      </>
    )
  return (
    <>
      Neu: <strong>„{h.name}“</strong> als Gast hinzufügen
    </>
  )
}
