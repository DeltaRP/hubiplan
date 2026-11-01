import { describe, expect, it } from 'vitest'
import { bindUndoToUser, clearUndo } from '../components/undo.ts'

// Gesamtaudit 01.11., GA-S07: Suchbegriffe überleben das Abmelden nicht
describe('gemerkte Listensuchen', () => {
  it('werden beim Abmelden gelöscht', () => {
    sessionStorage.setItem('hubiplan.mitgliederliste.7', JSON.stringify({ suche: 'erika@x.test' }))
    sessionStorage.setItem('hubiplan.abteilungsliste.3', JSON.stringify({ term: 'Muster' }))
    sessionStorage.setItem('anderes', '1')
    clearUndo()
    expect(sessionStorage.getItem('hubiplan.mitgliederliste.7')).toBeNull()
    expect(sessionStorage.getItem('hubiplan.abteilungsliste.3')).toBeNull()
    expect(sessionStorage.getItem('anderes')).toBe('1')
  })

  it('werden beim Kontowechsel im Tab gelöscht', () => {
    bindUndoToUser(1)
    sessionStorage.setItem('hubiplan.mitgliederliste.7', JSON.stringify({ suche: 'Muster' }))
    bindUndoToUser(1)
    expect(sessionStorage.getItem('hubiplan.mitgliederliste.7')).not.toBeNull()
    bindUndoToUser(2)
    expect(sessionStorage.getItem('hubiplan.mitgliederliste.7')).toBeNull()
  })
})
