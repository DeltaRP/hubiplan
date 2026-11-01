// Stechen ohne Empfang (Ralf 2026-11-01): das Gerät zeigt seine wartenden Eingaben an.
import { describe, expect, it } from 'vitest'
import type { ShootOff, StandingBlock } from '../api/competitions.ts'
import { mergeShootoffs, withLocalShootoffs } from '../pages/competitions/standShootoffs.ts'
import type { Local } from '../pages/competitions/standStore.ts'

const base: Local = { starters: [], members: [], ops: [], recent: [], savedAt: null }
const block = {
  scoring: 11,
  name: 'Einzelwertung',
  kind: 'einzel',
  open: [{ keys: ['s1', 's2'], names: ['Max Muster', 'Erika Beispiel'], place: 1, shootoff: null }],
  rows: [],
  without_value: [],
} as unknown as StandingBlock

describe('Stechen ohne Empfang', () => {
  it('angelegtes Stechen mit Wert erscheint sofort, auch ohne Server', () => {
    const l: Local = {
      ...base,
      ops: [
        {
          op: 'shootoff',
          client_key: 'k1',
          scoring: 11,
          keys: ['s1', 's2'],
          shots: 1,
          entries: [
            { key: 's1', name: 'Max Muster', unit: null, starter: 1 },
            { key: 's2', name: 'Erika Beispiel', unit: null, starter: 2 },
          ],
        },
        { op: 'shootoff_value', shootoff: 'k1', key: 's2', value: '9', at: '2027-06-14T12:00:00Z' },
      ],
    }
    const [so] = mergeShootoffs(l)
    expect(so).toMatchObject({ number: 1, shots: 1, pending: true })
    expect(so.entries.map((e) => [e.name, e.value])).toEqual([
      ['Max Muster', null],
      ['Erika Beispiel', '9'],
    ])
    // der Gleichstand gilt als „Stechen läuft“, kein zweites „Stechen anlegen“
    expect(withLocalShootoffs(block, [so]).open[0].shootoff).toBe(1)
  })

  it('nach dem Abgleich zählt der Server; spätere Werte über die Gerätekennung', () => {
    const server: ShootOff = {
      id: 5,
      scoring: 11,
      number: 1,
      shots: 1,
      counted_shots: null,
      entries: [
        {
          id: 51,
          key: 's1',
          starter: 1,
          unit: null,
          membership: null,
          name: 'Max Muster',
          value: null,
        },
      ],
    }
    const l: Local = {
      ...base,
      shootoffs: [server],
      shootoffKeys: { k1: 5 },
      ops: [
        {
          op: 'shootoff_value',
          shootoff: 'k1',
          key: 's1',
          value: '10',
          at: '2027-06-14T12:01:00Z',
        },
      ],
    }
    const list = mergeShootoffs(l)
    expect(list).toHaveLength(1)
    expect(list[0].entries[0].value).toBe('10')
    expect(list[0].pending).toBeUndefined()
  })
})
