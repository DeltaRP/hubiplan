// Stechen im Standmodus auch ohne Empfang (Ralf 2026-11-01): Anlegen, Regeln, Werte und
// Schütze gehen wie die Ergebnisse in die Warteschlange des Geräts. Bis der Server antwortet,
// zeigt das Gerät seinen eigenen Stand; legen zwei Geräte dasselbe Stechen an, führt der
// Server sie zusammen.
import { newRequestKey } from '../../api/client.ts'
import type {
  ShootOff,
  ShootoffApi,
  StandApi,
  StandingBlock,
  SyncOp,
} from '../../api/competitions.ts'
import type { Local } from './standStore.ts'

/** Gerätekennung oder Nummer beim Server; noch nicht abgeglichene Stechen haben negative
 *  Nummern auf dem Gerät. */
type Ref = number | string

/** Stechen vom letzten Abgleich mit den noch wartenden Eingaben des Geräts. */
export function mergeShootoffs(l: Local): ShootOff[] {
  const out: ShootOff[] = (l.shootoffs ?? []).map((so) => ({
    ...so,
    entries: so.entries.map((e) => ({ ...e })),
  }))
  const keys = l.shootoffKeys ?? {}
  const temp = new Map<string, ShootOff>()
  const find = (ref: Ref): ShootOff | undefined => {
    if (typeof ref === 'number') return out.find((so) => so.id === ref)
    if (keys[ref] !== undefined) return out.find((so) => so.id === keys[ref])
    return temp.get(ref)
  }
  let n = 0
  for (const o of l.ops) {
    if (o.op === 'shootoff') {
      if (keys[o.client_key] !== undefined) continue
      n += 1
      const number =
        Math.max(0, ...out.filter((x) => x.scoring === o.scoring).map((x) => x.number)) + 1
      const so: ShootOff = {
        id: -n,
        scoring: o.scoring,
        number,
        shots: o.shots ?? null,
        counted_shots: o.counted_shots ?? null,
        pending: true,
        entries: (o.entries ?? []).map((e, i) => ({
          id: -(n * 1000 + i + 1),
          key: e.key,
          starter: e.starter,
          unit: e.unit,
          membership: null,
          name: e.name,
          value: null,
        })),
      }
      temp.set(o.client_key, so)
      out.push(so)
    } else if (o.op === 'shootoff_rules') {
      const so = find(o.shootoff)
      if (so) {
        if (o.shots !== undefined) so.shots = o.shots
        if (o.counted_shots !== undefined) so.counted_shots = o.counted_shots
      }
    } else if (o.op === 'shootoff_value' || o.op === 'shootoff_member') {
      const entry = find(o.shootoff)?.entries.find((e) => e.key === o.key)
      if (!entry) continue
      if (o.op === 'shootoff_value') entry.value = o.value
      else {
        entry.membership = o.membership
        if (o.name !== undefined) entry.name = o.name
      }
    }
  }
  return out
}

/** Offene Gleichstände: läuft für die Gruppe schon ein (auch noch wartendes) Stechen? */
export function withLocalShootoffs(block: StandingBlock, shootoffs: ShootOff[]): StandingBlock {
  const open = block.open.map((tm) => {
    if (tm.shootoff) return tm
    const mine = shootoffs.find(
      (so) =>
        so.pending &&
        so.scoring === block.scoring &&
        so.entries
          .map((e) => e.key)
          .sort()
          .join() === [...tm.keys].sort().join(),
    )
    return mine ? { ...tm, shootoff: mine.number } : tm
  })
  return { ...block, open }
}

/** Ref eines Stechens für die Warteschlange: Nummer beim Server oder Gerätekennung. */
function refOf(l: Local, id: number): Ref {
  if (id > 0) return id
  let n = 0
  for (const o of l.ops) {
    if (o.op !== 'shootoff' || (l.shootoffKeys ?? {})[o.client_key] !== undefined) continue
    n += 1
    if (-n === id) return o.client_key
  }
  return id
}

/** ShootoffApi über die Warteschlange des Geräts (Standmodus, angemeldet und Standzugang). */
export function queuedShootoffApi(
  api: StandApi,
  local: () => Local,
  push: (op: SyncOp) => void,
  blocks: () => StandingBlock[],
): ShootoffApi {
  const current = () => mergeShootoffs(local())
  const byEntry = (entryId: number) => {
    const so = current().find((x) => x.entries.some((e) => e.id === entryId))
    const entry = so?.entries.find((e) => e.id === entryId)
    if (!so || !entry) throw new Error('Unbekannter Teilnehmer im Stechen.')
    return { so, entry }
  }
  const result = (id: number) => {
    const so = current().find((x) => x.id === id)
    if (!so) throw new Error('Unbekanntes Stechen.')
    return so
  }
  return {
    list: () => Promise.resolve(current()),
    create: (scoring, keys, rules) => {
      const block = blocks().find((b) => b.scoring === scoring)
      const rows = new Map((block?.rows ?? []).map((r) => [r.key, r]))
      const entries = keys.map((key) => {
        const r = rows.get(key)
        const unit = key.startsWith('u') ? Number(key.slice(1)) : null
        return {
          key,
          name: (unit ? r?.best : r?.name) ?? key,
          unit,
          starter: unit ? null : Number(key.slice(1)),
        }
      })
      push({ op: 'shootoff', client_key: newRequestKey(), scoring, keys, ...rules, entries })
      return Promise.resolve(current().at(-1) as ShootOff)
    },
    update: (id, rules) => {
      push({ op: 'shootoff_rules', shootoff: refOf(local(), id), ...rules })
      return Promise.resolve(result(id))
    },
    updateEntry: (entryId, data) => {
      const { so, entry } = byEntry(entryId)
      const ref = refOf(local(), so.id)
      if (data.value !== undefined)
        push({
          op: 'shootoff_value',
          shootoff: ref,
          key: entry.key,
          value: data.value,
          at: new Date().toISOString(),
        })
      if (data.membership !== undefined)
        push({
          op: 'shootoff_member',
          shootoff: ref,
          key: entry.key,
          membership: data.membership,
          ...(data.name !== undefined ? { name: data.name } : {}),
        })
      return Promise.resolve(result(so.id))
    },
    // ohne Empfang aus der Mitgliederliste auf dem Gerät
    unitMembers: (unit) =>
      api.shootoffs.unitMembers(unit).catch(() =>
        local()
          .members.filter((m) => m.unit === unit)
          .map((m) => ({ membership: m.membership, name: m.name })),
      ),
    remove: api.shootoffs.remove
      ? (id) =>
          id < 0
            ? Promise.reject(new Error('Erst nach dem Abgleich mit dem Server entfernbar.'))
            : api.shootoffs.remove!(id)
      : undefined,
    printUrl: api.shootoffs.printUrl,
  }
}
