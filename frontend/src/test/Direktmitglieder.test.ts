import { describe, expect, it } from 'vitest'
import type { OrgSummary } from '../api/orgs.ts'
import { memberSections, membersVisible, setupTabs } from '../pages/members/access.ts'
import { testOrg } from './fakeApi.ts'

const fed = (extra: Record<string, unknown> = {}) =>
  testOrg({
    type: 'federation',
    permissions: ['members.view', 'members.edit'],
    modules: ['members'],
    federation_member_access: 'none',
    ...extra,
  }) as unknown as OrgSummary

describe('Eigene Mitglieder der obersten Einheit', () => {
  it('ohne Schalter und ohne Freigabe kein Menüpunkt', () => {
    expect(membersVisible(fed())).toBe(false)
  })

  it('mit Schalter: eigene Liste und Mitgliedsarten', () => {
    const org = fed({ direct_members: true })
    expect(membersVisible(org)).toBe(true)
    expect(memberSections(org).map((s) => s.label)).toEqual([
      'Eigene Mitglieder',
      'Entwicklung',
      'Jubiläen',
      'Würdenträger',
      'Ämter',
      'Einrichtung',
    ])
    expect(memberSections(org).map((s) => s.to)).not.toContain('/mitglieder/verbund/entwicklung')
    expect(setupTabs(org).map((t) => t.label)).toContain('Mitgliedsarten')
  })

  it('mit Schalter und Freigabe: dazu die Übersicht über alle', () => {
    const org = fed({ direct_members: true, federation_member_access: 'read' })
    expect(memberSections(org).map((s) => s.to)).toContain('/mitglieder/verbund')
    // Eigene Entwicklung und die aller Einheiten darunter getrennt
    expect(memberSections(org).map((s) => s.to)).toContain('/mitglieder/verbund/entwicklung')
  })

  it('nur Freigabe: Übersicht wie bisher', () => {
    const org = fed({ federation_member_access: 'read' })
    expect(memberSections(org)[0]).toEqual({ to: '/mitglieder', label: 'Mitgliederliste' })
    expect(setupTabs(org).map((t) => t.label)).not.toContain('Mitgliedsarten')
  })
})
