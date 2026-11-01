// Webseite: Unterpunkte in der Seitenleiste (wie bei Mitglieder und Finanzen).
import { PERM } from '../../api/orgs.ts'
import type { OrgSummary } from '../../api/orgs.ts'
import { t } from '../../i18n/index.ts'

export interface NavItem {
  to: string
  label: string
}

const ALL: NavItem[] = [
  { to: '/webseite', label: t('Übersicht') },
  { to: '/webseite/inhalte', label: t('Texte') },
  { to: '/webseite/bilder', label: t('Bilder') },
  { to: '/webseite/beitraege', label: t('Social Media') },
  { to: '/webseite/aufbau', label: t('Menü und Bereiche') },
  { to: '/webseite/gestaltung', label: t('Gestaltung') },
  { to: '/webseite/kontakt', label: t('Kontaktformular') },
  { to: '/webseite/domain', label: t('Internetadresse') },
]

/** Wer nur Inhalte pflegt, sieht nur „Texte“, „Bilder“ und „Social Media“. */
export function websiteSections(org: OrgSummary | null): NavItem[] {
  if (!org) return []
  if (org.permissions.includes(PERM.websiteManage)) return ALL
  if (org.permissions.includes(PERM.websiteContent)) {
    return ALL.filter((s) =>
      ['/webseite/inhalte', '/webseite/bilder', '/webseite/beitraege'].includes(s.to),
    )
  }
  return []
}

/** Überschrift zum aktuellen Pfad */
export function sectionTitle(pathname: string): string {
  const path = pathname.replace(/\/+$/, '') || '/webseite'
  return ALL.find((s) => s.to === path)?.label ?? t('Webseite')
}
