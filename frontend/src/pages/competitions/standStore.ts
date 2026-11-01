// Speicher des Standmodus auf dem Gerät: Starter, Mitglieder, Warteschlange und (beim
// Vogelschießen) der letzte Stand vom Server. Eingaben landen erst hier und gleichen
// sich bei Empfang selbst ab (Schießstände im Keller, Ralf 2026-11-01).
import { useEffect, useRef, useState } from 'react'
import type {
  BirdState,
  CompetitionStatus,
  MemberChoice,
  Starter,
  StandApi,
  SyncOp,
  SyncResult,
} from '../../api/competitions.ts'
import { errorMessage } from '../../components/forms.ts'

export type LocalStarter = Starter & { key?: string | null }

export interface Local {
  /** Starter mit Werten; neue Starter tragen ihre Gerätekennung als ``key`` */
  starters: LocalStarter[]
  members: MemberChoice[]
  ops: SyncOp[]
  recent: { ref: number | string; name: string; value: string; at: string }[]
  savedAt: string | null
  bird?: BirdState | null
  status?: CompetitionStatus
}

const storageKey = (key: string) => `hubiplan.stand.${key}`

function loadLocal(key: string): Local | null {
  try {
    const raw = localStorage.getItem(storageKey(key))
    return raw ? (JSON.parse(raw) as Local) : null
  } catch {
    return null
  }
}

function saveLocal(key: string, data: Local) {
  try {
    localStorage.setItem(storageKey(key), JSON.stringify(data))
  } catch {
    // Speicher voll oder gesperrt: dann bleibt es bei der Warteschlange im Speicher
  }
}

export function mergePending(server: Starter[], l: Local): LocalStarter[] {
  // Noch nicht abgeglichene Starter und Eingaben des Geräts über den Stand des Servers legen
  const out: LocalStarter[] = server.map((s) => ({ ...s }))
  const pendingKeys = new Set(
    l.ops.filter((o) => o.op === 'starter').map((o) => (o as { client_key: string }).client_key),
  )
  for (const s of l.starters)
    if (s.key && pendingKeys.has(s.key) && !out.some((x) => x.key === s.key)) out.push(s)
  const find = (ref: number | string) => out.find((x) => x.id === ref || (!!x.key && x.key === ref))
  for (const o of l.ops) {
    if (o.op === 'score') {
      const s = find(o.starter)
      if (s) s.values = { ...s.values, [o.scoring]: o.value ?? '' }
    } else if (o.op === 'starter_update') {
      const s = find(o.starter)
      if (s) {
        if (o.number !== undefined) s.number = o.number
        if (o.presence !== undefined) s.presence = o.presence
      }
    } else if (o.op === 'draw') {
      const s = find(o.starter)
      if (s && o.number !== null) s.number = String(o.number)
    }
  }
  return out
}

export interface Conflict {
  name: string
  value?: string
  number?: number
  note?: string
}

/** Standmodus-Speicher mit Abgleich alle 15 s, beim Wiederkehren des Netzes und nach jeder
 * Eingabe. ``describe`` nennt eine Eingabe für Fehlermeldungen. */
export function useStandStore(
  api: StandApi,
  describe: (op: SyncOp, l: Local) => string,
  onConflicts?: (c: Conflict[]) => void,
  /** auch ohne eigene Eingaben regelmäßig den Stand holen (Vogelschießen live) */
  refresh = false,
) {
  const [local, setLocal] = useState<Local>(
    () => loadLocal(api.key) ?? { starters: [], members: [], ops: [], recent: [], savedAt: null },
  )
  const [online, setOnline] = useState(typeof navigator === 'undefined' ? true : navigator.onLine)
  const [syncError, setSyncError] = useState<string | null>(null)
  const localRef = useRef(local)
  const syncing = useRef(false)
  const conflictsRef = useRef(onConflicts)
  useEffect(() => {
    conflictsRef.current = onConflicts
  })

  useEffect(() => {
    localRef.current = local
    saveLocal(api.key, local)
  }, [api.key, local])

  function apply(res: SyncResult, sent: number) {
    setLocal((l) => {
      // Was während des Abgleichs dazukam, bleibt in der Warteschlange
      const rest = l.ops.slice(sent)
      return {
        ...l,
        ops: rest,
        starters: mergePending(res.starters, { ...l, ops: rest }),
        bird: res.bird ?? l.bird,
        status: res.status ?? l.status,
        savedAt: new Date().toISOString(),
      }
    })
  }

  async function sync(force = false) {
    const ops = localRef.current.ops
    if (syncing.current || (ops.length === 0 && !force)) return
    syncing.current = true
    try {
      const res = await api.sync(ops)
      const failed = res.results
        .map((r, i) => (r.ok ? null : `${describe(ops[i], localRef.current)}: ${r.error}`))
        .filter(Boolean)
      apply(res, ops.length)
      setOnline(true)
      setSyncError(failed.length ? `Nicht übernommen: ${failed.join('; ')}` : null)
      if (res.conflicts.length) conflictsRef.current?.(res.conflicts)
    } catch (err) {
      setOnline(false)
      setSyncError(
        errorMessage(err) === 'Der Server ist nicht erreichbar.' ? null : errorMessage(err),
      )
    } finally {
      syncing.current = false
    }
  }

  // Erst laden: Starter, Mitgliederliste und Stand aufs Gerät (für die Arbeit ohne Netz)
  useEffect(() => {
    let stop = false
    async function load() {
      try {
        const [starters, members] = await Promise.all([api.starters(), api.members()])
        if (stop) return
        setLocal((l) => ({ ...l, starters: mergePending(starters, l), members }))
        setOnline(true)
      } catch {
        if (!stop) setOnline(false)
      }
    }
    void load().then(() => sync(refresh))
    const up = () => {
      setOnline(true)
      void sync(refresh)
    }
    const down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    const timer = setInterval(() => void sync(refresh), 15000)
    return () => {
      stop = true
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
      clearInterval(timer)
    }
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [api.key])

  /** Eingabe auf dem Gerät übernehmen und gleich abgleichen. */
  function push(op: SyncOp | null, change: (l: Local) => Local = (l) => l) {
    setLocal((l) => change(op ? { ...l, ops: [...l.ops, op] } : l))
    setTimeout(() => void sync(), 0)
  }

  const pending = local.ops.length
  const statusText = pending
    ? `${pending} ${pending === 1 ? 'Eingabe wartet' : 'Eingaben warten'} auf ${online ? 'Abgleich' : 'Empfang'}`
    : 'Alles gespeichert'

  return { local, setLocal, push, sync, online, syncError, pending, statusText }
}

/** Eine Eingabe für Fehlermeldungen benennen. */
export function describe(op: SyncOp, l: Local): string {
  if (op.op === 'starter')
    return op.name ?? l.members.find((m) => m.membership === op.membership)?.name ?? 'Schütze'
  if (op.op === 'undo') return 'Rückgängig'
  const s = l.starters.find((x) => x.id === op.starter || (!!x.key && x.key === op.starter))
  return s?.name ?? 'Eingabe'
}
