// Wer sieht den Menüpunkt „Rundschreiben“ und wer darf verfassen?
import { PERM } from '../../api/orgs.ts'
import type { OrgSummary } from '../../api/orgs.ts'
import { DEPT_PERM } from '../../api/portal.ts'
import type { DeptSummary } from '../../api/portal.ts'

/** Darf die Rolle in der Organisation Rundschreiben verfassen? */
export function canWriteCirculars(org: OrgSummary | null): boolean {
  if (!org || !org.permissions.includes(PERM.circularsSend)) return false
  return org.type === 'federation' || org.type === 'club'
}

/** Menüpunkt „Rundschreiben“ */
export function circularsVisible(org: OrgSummary | null, dept: DeptSummary | null): boolean {
  if (org) return canWriteCirculars(org) || org.type === 'club'
  return !!dept && dept.permissions.includes(DEPT_PERM.circularsSend)
}
