import { PERM } from '../../api/orgs.ts'
import type { OrgSummary } from '../../api/orgs.ts'

/** Gibt es hier einen Menüpunkt für Untereinheiten? */
export function hasUnitsPage(org: OrgSummary, can: (perm: string) => boolean): boolean {
  if (org.type === 'club') return true
  return org.type === 'federation' && can(PERM.clubsManage)
}
