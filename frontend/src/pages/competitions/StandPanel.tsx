// Erfassen am Stand (Kartenschießen): Schützen kommen in beliebiger Reihenfolge mit ihrer
// Karte. Ein Suchfeld ist immer aktiv: Name oder Startnummer, Enter, Punkte, Enter.
// Alle Eingaben landen erst auf dem Gerät und gleichen sich bei Empfang selbst ab
// (Schießstände im Keller, Ralf 2026-11-01).
import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { newRequestKey } from '../../api/client.ts'
import {
  competitionsApi,
  foldName,
  showValue,
  type CompetitionDetail,
  type MemberChoice,
  type Scoring,
  type Starter,
  type SyncOp,
} from '../../api/competitions.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage } from '../../components/forms.ts'

interface Local {
  /** Starter mit Werten; neue Starter tragen ihre Gerätekennung als ``key`` */
  starters: (Starter & { key?: string })[]
  members: MemberChoice[]
  ops: SyncOp[]
  recent: { ref: number | string; name: string; value: string; at: string }[]
  savedAt: string | null
}

const storageKey = (org: number, id: number) => `hubiplan.stand.${org}.${id}`

function loadLocal(org: number, id: number): Local | null {
  try {
    const raw = localStorage.getItem(storageKey(org, id))
    return raw ? (JSON.parse(raw) as Local) : null
  } catch {
    return null
  }
}

function saveLocal(org: number, id: number, data: Local) {
  try {
    localStorage.setItem(storageKey(org, id), JSON.stringify(data))
  } catch {
    // Speicher voll oder gesperrt: dann bleibt es bei der Warteschlange im Speicher
  }
}

type Hit =
  | { kind: 'starter'; starter: Starter & { key?: string } }
  | { kind: 'member'; member: MemberChoice }
  | { kind: 'guest'; name: string }

export function StandPanel({
  org,
  comp,
  fullscreen = false,
}: {
  org: number
  comp: CompetitionDetail
  fullscreen?: boolean
}) {
  const scoring: Scoring | undefined = comp.scorings.find((s) => s.kind === 'einzel')
  const [local, setLocal] = useState<Local>(
    () =>
      loadLocal(org, comp.id) ?? { starters: [], members: [], ops: [], recent: [], savedAt: null },
  )
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [chosen, setChosen] = useState<Hit | null>(null)
  const [points, setPoints] = useState('')
  const [guestClub, setGuestClub] = useState('')
  const searchRef = useRef<HTMLInputElement>(null)
  const pointsRef = useRef<HTMLInputElement>(null)
  const localRef = useRef(local)
  const syncing = useRef(false)
  const closed = comp.status === 'endgueltig'

  useEffect(() => {
    localRef.current = local
    saveLocal(org, comp.id, local)
  }, [org, comp.id, local])

  // Erst laden: Starter und Mitgliederliste aufs Gerät (für die Suche ohne Netz)
  useEffect(() => {
    let stop = false
    async function load() {
      try {
        const [starters, members] = await Promise.all([
          competitionsApi.starters(org, comp.id),
          competitionsApi.members(org, comp.id),
        ])
        if (stop) return
        setLocal((l) => ({ ...l, starters: mergePending(starters, l), members }))
        setOnline(true)
      } catch {
        if (!stop) setOnline(false)
      }
    }
    void load().then(() => sync())
    const up = () => {
      setOnline(true)
      void sync()
    }
    const down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    const timer = setInterval(() => void sync(), 15000)
    return () => {
      stop = true
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
      clearInterval(timer)
    }
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [org, comp.id])

  async function sync() {
    const ops = localRef.current.ops
    if (syncing.current || ops.length === 0) return
    syncing.current = true
    try {
      const res = await competitionsApi.sync(org, comp.id, ops)
      const failed = res.results
        .map((r, i) => (r.ok ? null : `${describe(ops[i], localRef.current)}: ${r.error}`))
        .filter(Boolean)
      setLocal((l) => {
        // Was während des Abgleichs dazukam, bleibt in der Warteschlange
        const rest = l.ops.slice(ops.length)
        return {
          ...l,
          ops: rest,
          starters: mergePending(res.starters, { ...l, ops: rest }),
          savedAt: new Date().toISOString(),
        }
      })
      setOnline(true)
      setSyncError(failed.length ? `Nicht übernommen: ${failed.join('; ')}` : null)
      if (res.conflicts.length)
        setNotice(
          `Auf einem anderen Gerät später geändert, dieser Wert gilt: ${res.conflicts
            .map((c) => `${c.name} ${showValue(c.value, scoring?.decimals ?? 0)}`)
            .join(', ')}`,
        )
    } catch (err) {
      setOnline(false)
      setSyncError(
        errorMessage(err) === 'Der Server ist nicht erreichbar.' ? null : errorMessage(err),
      )
    } finally {
      syncing.current = false
    }
  }

  function push(op: SyncOp, change: (l: Local) => Local) {
    setLocal((l) => change({ ...l, ops: [...l.ops, op] }))
    setTimeout(() => void sync(), 0)
  }

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
      setTimeout(() => void sync(), 0)
      setNotice(`${name} eingetragen.`)
    }
    setChosen(null)
    setQuery('')
    setPoints('')
    setActive(0)
    setTimeout(() => searchRef.current?.focus(), 0)
  }

  if (!scoring) return <p className="muted">Zuerst eine Einzelwertung anlegen.</p>

  const open = local.starters.filter((s) => !s.values[String(scoring.id)])
  const pending = local.ops.length
  const status = pending
    ? `${pending} ${pending === 1 ? 'Eingabe wartet' : 'Eingaben warten'} auf ${online ? 'Abgleich' : 'Empfang'}`
    : 'Alles gespeichert'

  return (
    <div className={`stand${fullscreen ? ' stand-full' : ''}`}>
      <p className={`stand-sync ${pending ? 'stand-sync-wait' : 'stand-sync-ok'}`} role="status">
        {online ? '' : 'Kein Empfang · '}
        {status}
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
        <summary>Zuletzt erfasst ({local.recent.length})</summary>
        <ul className="stand-list">
          {local.recent.map((r) => (
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
    </div>
  )
}

function mergePending(server: Starter[], l: Local): (Starter & { key?: string })[] {
  // Noch nicht abgeglichene Starter und Werte des Geräts über den Stand des Servers legen
  const out: (Starter & { key?: string })[] = server.map((s) => ({ ...s }))
  const pendingKeys = new Set(
    l.ops.filter((o) => o.op === 'starter').map((o) => (o as { client_key: string }).client_key),
  )
  for (const s of l.starters) if (s.key && pendingKeys.has(s.key)) out.push(s)
  for (const o of l.ops) {
    if (o.op !== 'score') continue
    const s = out.find((x) => (x.key ?? x.id) === o.starter)
    if (s) s.values = { ...s.values, [o.scoring]: o.value ?? '' }
  }
  return out
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

function describe(op: SyncOp, l: Local): string {
  if (op.op === 'starter')
    return op.name ?? l.members.find((m) => m.membership === op.membership)?.name ?? 'Schütze'
  const s = l.starters.find((x) => (x.key ?? x.id) === op.starter)
  return s?.name ?? 'Eingabe'
}
