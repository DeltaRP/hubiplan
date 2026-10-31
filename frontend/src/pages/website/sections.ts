// Webseite: Unterpunkte in der Seitenleiste (wie bei Mitglieder und Finanzen).
import { PERM } from '../../api/orgs.ts'
import type { OrgSummary } from '../../api/orgs.ts'

export interface NavItem {
  to: string
  label: string
}

const ALL: NavItem[] = [
  { to: '/webseite', label: 'Übersicht' },
  { to: '/webseite/inhalte', label: 'Texte und Bilder' },
  { to: '/webseite/beitraege', label: 'Social Media' },
  { to: '/webseite/aufbau', label: 'Menü und Bereiche' },
  { to: '/webseite/gestaltung', label: 'Gestaltung' },
  { to: '/webseite/kontakt', label: 'Kontaktformular' },
  { to: '/webseite/domain', label: 'Internetadresse' },
]

/** Wer nur Inhalte pflegt, sieht nur „Texte und Bilder“ und „Social Media“. */
export function websiteSections(org: OrgSummary | null): NavItem[] {
  if (!org) return []
  if (org.permissions.includes(PERM.websiteManage)) return ALL
  if (org.permissions.includes(PERM.websiteContent)) {
    return ALL.filter((s) => s.to === '/webseite/inhalte' || s.to === '/webseite/beitraege')
  }
  return []
}

/** Überschrift zum aktuellen Pfad */
export function sectionTitle(pathname: string): string {
  const path = pathname.replace(/\/+$/, '') || '/webseite'
  return ALL.find((s) => s.to === path)?.label ?? 'Webseite'
}
