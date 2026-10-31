// Mitglieder: Unterpunkte in der Seitenleiste und Reiter der Einrichtung.
// Welche erscheinen, hängt von den Schaltern der Einheit, Freigaben und Rechten ab.
import { PERM } from '../../api/orgs.ts'
import type { OrgSummary } from '../../api/orgs.ts'

export interface NavItem {
  to: string
  label: string
}

/** Darf die Organisation Mitglieder sehen (Menüpunkt „Mitglieder“)? */
export function membersVisible(org: OrgSummary | null): boolean {
  if (!org || !org.permissions.includes(PERM.membersView)) return false
  if (org.type === 'club') return org.modules.includes('members')
  return org.type === 'federation' && (federationAccess(org) || ownMembers(org))
}

/** Oberste Einheit, die auch selbst Mitglieder führt */
export function ownMembers(org: OrgSummary) {
  return org.type === 'federation' && !!org.direct_members && org.modules.includes('members')
}

/** Dachverband mit Zugriff auf die Mitgliedsdaten der Vereine */
export function federationAccess(org: OrgSummary) {
  return !!org.federation_member_access && org.federation_member_access !== 'none'
}

/** Unterpunkte von Mitglieder (Seitenleiste). */
export function memberSections(org: OrgSummary | null): NavItem[] {
  if (!org || !membersVisible(org)) return []
  if (org.type === 'federation' && !ownMembers(org)) {
    return [
      { to: '/mitglieder', label: 'Mitgliederliste' },
      { to: '/mitglieder/entwicklung', label: 'Entwicklung' },
      { to: '/mitglieder/einrichtung', label: 'Einrichtung' },
    ]
  }
  const canEdit = org.permissions.includes(PERM.membersEdit)
  if (org.type === 'federation') {
    // Eigene Mitglieder; die Übersicht über alle Einheiten darunter daneben
    return [
      { to: '/mitglieder', label: 'Eigene Mitglieder' },
      ...(federationAccess(org) ? [{ to: '/mitglieder/verbund', label: 'Alle Mitglieder' }] : []),
      { to: '/mitglieder/entwicklung', label: 'Entwicklung' },
      ...(federationAccess(org)
        ? [{ to: '/mitglieder/verbund/entwicklung', label: 'Entwicklung aller' }]
        : []),
      { to: '/mitglieder/jubilaeen', label: 'Jubiläen' },
      { to: '/mitglieder/wuerdentraeger', label: 'Würdenträger' },
      { to: '/mitglieder/aemter', label: 'Ämter' },
      { to: '/mitglieder/einrichtung', label: 'Einrichtung' },
    ]
  }
  return [
    { to: '/mitglieder', label: 'Mitgliederliste' },
    { to: '/mitglieder/entwicklung', label: 'Entwicklung' },
    { to: '/mitglieder/jubilaeen', label: 'Jubiläen' },
    { to: '/mitglieder/wuerdentraeger', label: 'Würdenträger' },
    { to: '/mitglieder/aemter', label: 'Ämter' },
    { to: '/mitglieder/anfragen', label: 'Anfragen' },
    ...(canEdit ? [{ to: '/mitglieder/import', label: 'Import' }] : []),
    { to: '/mitglieder/einrichtung', label: 'Einrichtung' },
  ]
}

export function requestTabs(): NavItem[] {
  return [
    { to: '/mitglieder/anfragen', label: 'Wechselanfragen' },
    { to: '/mitglieder/anfragen/aenderungen', label: 'Änderungsmeldungen' },
  ]
}

export function setupTabs(org: OrgSummary): NavItem[] {
  const club = org.type === 'club'
  return [
    ...(club || ownMembers(org)
      ? [{ to: '/mitglieder/einrichtung/mitgliedsarten', label: 'Mitgliedsarten' }]
      : []),
    { to: '/mitglieder/einrichtung/ehrungen', label: 'Ehrungen' },
    { to: '/mitglieder/einrichtung/zusatzfelder', label: 'Zusatzfelder' },
    { to: '/mitglieder/einrichtung/jubilaeen', label: 'Jubiläen & Dauer' },
    ...(club
      ? [{ to: '/mitglieder/einrichtung/mitgliederbereich', label: 'Mitgliederbereich & Fotos' }]
      : []),
  ]
}
