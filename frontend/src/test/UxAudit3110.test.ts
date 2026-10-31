// UX-Audit 31.10.: Seitenleisten-Baum (W09) und CSV der Importprüfung
import { describe, expect, it } from 'vitest'
import { buildNavTree } from '../components/subnav.ts'

describe('buildNavTree (W09)', () => {
  it('hängt Reiter einer Seite ohne feste Unterpunkte direkt ans Modul', () => {
    const tree = buildNavTree(
      '/termine',
      [],
      [
        [
          { to: '/termine', label: 'Kalender' },
          { to: '/termine/veranstaltungen', label: 'Veranstaltungen' },
        ],
      ],
    )
    expect(tree.map((n) => n.label)).toEqual(['Kalender', 'Veranstaltungen'])
  })

  it('hängt tiefere Reiter unter den passenden festen Punkt, ohne Doppel', () => {
    const tree = buildNavTree(
      '/finanzen',
      [
        { to: '/finanzen', label: 'Übersicht' },
        { to: '/finanzen/rechnungen', label: 'Rechnungen' },
      ],
      [
        [
          { to: '/finanzen/rechnungen', label: 'Liste' },
          { to: '/finanzen/rechnungen/laeufe', label: 'Läufe' },
        ],
      ],
    )
    const bills = tree.find((n) => n.label === 'Rechnungen')
    expect(bills?.children.map((n) => n.label)).toEqual(['Läufe'])
    expect(tree.find((n) => n.label === 'Übersicht')?.children).toEqual([])
  })

  it('zeigt einzelne Reiter unter dem Modul nicht', () => {
    expect(buildNavTree('/dokumente', [], [[{ to: '/dokumente', label: 'Ablage' }]])).toEqual([])
  })
})
