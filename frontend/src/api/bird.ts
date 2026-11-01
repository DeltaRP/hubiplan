// Vogelschießen auf dem Gerät nachrechnen (wie backend/competitions/bird.py), damit der
// Standmodus auch ohne Empfang weiß, wer dran ist und welche Pfänder gefallen sind.
import type { BirdPrize, BirdState, Starter, SyncOp } from './competitions.ts'

export type Ref = number | string

/** Verweis auf einen Starter: Gerätekennung, wenn vorhanden, sonst die Nummer. */
export function refOf(s: Pick<Starter, 'id' | 'key'>): Ref {
  return s.key ?? s.id
}

export function sameStarter(s: Pick<Starter, 'id' | 'key'>, ref: Ref | null | undefined) {
  return ref !== null && ref !== undefined && (ref === s.id || (!!s.key && ref === s.key))
}

/** Losnummer als Zahl (Startnummern sind sonst freier Text). */
export function lot(number: string | null | undefined): number | null {
  const text = (number ?? '').trim()
  if (!/^\d+$/.test(text)) return null
  const n = Number(text)
  return n > 0 && n < 100000 ? n : null
}

export interface Slot {
  ref: Ref
  number: number
}

export function shootingOrder(
  starters: Starter[],
  isWinner: (s: Starter) => boolean,
  dropOut: boolean,
): Slot[] {
  const out: Slot[] = []
  for (const s of starters) {
    const n = lot(s.number)
    if (n === null || s.presence) continue
    if (dropOut && isWinner(s)) continue
    out.push({ ref: refOf(s), number: n })
  }
  return out.sort((a, b) => a.number - b.number)
}

export function nextAfter(order: Slot[], last: number | null): number | null {
  if (!order.length) return null
  if (last === null) return 0
  const i = order.findIndex((x) => x.number > last)
  return i === -1 ? 0 : i
}

export interface LocalShot {
  number: number
  starter: Ref | null
  key: string | null
}

export interface LocalPrize extends BirdPrize {
  winnerRef: Ref | null
}

export interface BirdView {
  prizes: LocalPrize[]
  shots: LocalShot[]
  total: number
  round: number
  sinceLast: number
  order: Slot[]
  /** die nächsten (bis zu 4) Schützen, der erste ist dran */
  upcoming: Ref[]
  /** letzter Schuss, falls er zurückgenommen werden kann */
  last: LocalShot | null
}

/** Stand des Servers plus die Eingaben, die noch auf dem Gerät warten. */
export function project(
  state: BirdState | null | undefined,
  ops: SyncOp[],
  starters: Starter[],
  dropOut: boolean,
): BirdView {
  const prizes: LocalPrize[] = (state?.prizes ?? []).map((p) => ({ ...p, winnerRef: p.winner }))
  const shots: LocalShot[] = (state?.recent ?? []).map((x) => ({
    number: x.number,
    starter: x.starter,
    key: x.client_key,
  }))
  let total = state?.live_shots ?? 0
  const manual = state && !state.live_shots ? state.shots : 0
  let round = state?.round ?? 0
  const find = (ref: Ref | null) =>
    ref === null ? undefined : starters.find((s) => sameStarter(s, ref))
  const numberOf = (ref: Ref | null) => lot(find(ref)?.number)
  const lastNumber = () => {
    for (let i = shots.length - 1; i >= 0; i -= 1) {
      const n = numberOf(shots[i].starter)
      if (n !== null) return { n, i }
    }
    return null
  }
  for (const op of ops) {
    if (op.op === 'shot') {
      const n = total + 1
      const num = numberOf(op.starter)
      const prev = lastNumber()
      if (num !== null && (prev === null || num <= prev.n)) round += 1
      const before = Math.max(
        0,
        ...prizes
          .filter((p) => p.fallen && p.shot_number !== null && p.shot_number < n)
          .map((p) => p.shot_number as number),
      )
      const who = find(op.starter)
      for (const p of prizes) {
        if (!op.hits.includes(p.id) || p.fallen) continue
        Object.assign(p, {
          fallen: true,
          winner: typeof op.starter === 'number' ? op.starter : null,
          winnerRef: op.starter,
          winner_name: who?.name ?? '',
          unit_name: who?.unit_name ?? '',
          club: who?.club ?? '',
          number: who?.number ?? '',
          shot_number: n,
          shots_for: n - before,
          live: true,
          fallen_at: op.at,
        })
      }
      shots.push({ number: n, starter: op.starter, key: op.client_key })
      total = n
    } else if (op.op === 'undo') {
      const last = shots[shots.length - 1]
      if (!last || (op.client_key && last.key !== op.client_key)) continue
      const num = numberOf(last.starter)
      shots.pop()
      const prev = lastNumber()
      if (num !== null && (prev === null || num <= prev.n)) round = Math.max(0, round - 1)
      for (const p of prizes) {
        if (p.live && p.shot_number === last.number) {
          Object.assign(p, {
            fallen: false,
            winner: null,
            winnerRef: null,
            winner_name: '',
            unit_name: '',
            club: '',
            number: '',
            shot_number: null,
            shots_for: null,
            live: false,
            fallen_at: null,
          })
        }
      }
      total = Math.max(0, total - 1)
    }
  }
  const count = total || manual
  const fallen = prizes.filter((p) => p.fallen && p.shot_number).map((p) => p.shot_number as number)
  const sinceLast = Math.max(0, fallen.length ? count - Math.max(...fallen) : count)
  const winners = prizes.map((p) => p.winnerRef).filter((r): r is Ref => r !== null)
  const order = shootingOrder(starters, (s) => winners.some((r) => sameStarter(s, r)), dropOut)
  const last = shots[shots.length - 1] ?? null
  const current = nextAfter(order, last ? numberOf(last.starter) : null)
  const upcoming: Ref[] = []
  if (current !== null) {
    for (let k = 0; k < Math.min(4, order.length); k += 1)
      upcoming.push(order[(current + k) % order.length].ref)
  }
  return { prizes, shots, total: count, round, sinceLast, order, upcoming, last }
}

/** Eine freie Losnummer ziehen (wie der Server: aus 1 … Anzahl der Schützen). */
/** Freie Losnummer ziehen: aus 1 bis Zahl der Starter oder, wenn gesetzt, bis „Lose im Hut“. */
export function drawFree(
  starters: Starter[],
  exclude?: Ref,
  random = Math.random,
  lots?: number | null,
): number {
  const taken = new Set(
    starters
      .filter((s) => exclude === undefined || !sameStarter(s, exclude))
      .map((s) => lot(s.number))
      .filter((n): n is number => n !== null),
  )
  const count = starters.filter((s) => s.presence !== 'zurueckgezogen').length
  const top = Math.max(count, lots ?? 0, ...taken, 0)
  const free: number[] = []
  for (let n = 1; n <= top; n += 1) if (!taken.has(n)) free.push(n)
  if (!free.length) return top + 1
  return free[Math.floor(random() * free.length)]
}
