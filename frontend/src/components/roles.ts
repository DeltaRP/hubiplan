// Gemeinsame Angaben für Rollen aller Einheiten (Liste und Maske: RoleEditor.tsx)
import type { CatalogModule } from '../api/orgs.ts'

export interface RoleValues {
  name: string
  description: string
  is_board: boolean
  represents: boolean
  on_letterhead: boolean
  contact_email: string
  on_website: boolean
  in_chronicle: boolean
  permissions: string[]
}

export type RoleField = Exclude<keyof RoleValues, 'name' | 'permissions'>

/** Rolle, wie sie in Liste und Maske erscheint */
export interface RoleLike extends Partial<RoleValues> {
  id: number
  name: string
  permissions: string[]
  /** Inhaber: Anzahl oder Namen */
  holders: number | string[]
}

const FULL: RoleField[] = [
  'description',
  'is_board',
  'represents',
  'on_letterhead',
  'contact_email',
  'on_website',
  'in_chronicle',
]
/** Angaben, die Rollen einer Untereinheit (Zuordnung über die Mitgliederakte) haben */
export const UNIT_ROLE_FIELDS: RoleField[] = ['on_letterhead', 'contact_email', 'on_website']
export const ALL_ROLE_FIELDS = FULL

export function permissionLabels(codes: string[], catalog: CatalogModule[]): string {
  if (codes.length === 0) return 'keine'
  const labels = catalog.flatMap((m) => m.permissions).filter((p) => codes.includes(p.code))
  return labels.map((p) => p.label).join(', ')
}

export interface PermissionArea {
  label: string
  /** alle Rechte des Bereichs */
  full: boolean
  permissions: string[]
}

/** Rechte nach Bereichen des Katalogs zusammengefasst (für die kurze Übersicht) */
export function permissionAreas(codes: string[], catalog: CatalogModule[]): PermissionArea[] {
  return catalog
    .map((m) => {
      const held = m.permissions.filter((p) => codes.includes(p.code))
      return {
        label: m.label,
        full: held.length === m.permissions.length,
        permissions: held.map((p) => p.label),
      }
    })
    .filter((a) => a.permissions.length > 0)
}
