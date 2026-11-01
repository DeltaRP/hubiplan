// Module der linken Navigation. Welche erscheinen, hängt von der aktiven
// Organisation ab: freigeschaltete Module und Berechtigungen der Rolle.
import type { ReactNode } from 'react'
import { PERM } from './api/orgs.ts'
import type { OrgSummary } from './api/orgs.ts'
import type { DeptSummary, PortalEntry } from './api/portal.ts'
import { financeAccess, financeSections } from './pages/finanzen/access.ts'
import { memberSections, membersVisible } from './pages/members/access.ts'
import { websiteSections } from './pages/website/sections.ts'
import { circularsVisible } from './pages/circulars/access.ts'
import { hasUnitsPage } from './pages/settings/units.ts'

export interface Workspace {
  dept: DeptSummary | null
  portal: PortalEntry | null
}

export interface AppModule {
  id: string
  label: string
  /** Bezeichnung je Einheit, z. B. „Züge“ statt „Untereinheiten“ */
  labelFor?: (org: OrgSummary | null) => string
  path: string
  icon: ReactNode
  visible: (org: OrgSummary | null, ws: Workspace) => boolean
  /** Unterpunkte, in der Seitenleiste unter dem aktiven Modul */
  children?: (org: OrgSummary | null) => { to: string; label: string }[]
}

const icon = (d: string) => (
  <svg
    viewBox="0 0 24 24"
    width="20"
    height="20"
    aria-hidden="true"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d={d} />
  </svg>
)

export const modules: AppModule[] = [
  {
    id: 'start',
    label: 'Startseite',
    path: '/',
    icon: icon('M4 11 12 4l8 7M6 9.5V20h12V9.5M10 20v-5h4v5M16 7.5V4.5h2.5v5.2'),
    visible: () => true,
  },
  {
    id: 'mitglieder',
    label: 'Mitglieder',
    path: '/mitglieder',
    icon: icon(
      'M9 4.5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6M15.5 5.2a3 3 0 1 1 1.2 5.6M17.5 14.2c2.4.5 4 2.6 4 5.8',
    ),
    visible: membersVisible,
    children: memberSections,
  },
  {
    // Untereinheiten (z. B. Züge), benannt nach der Bezeichnung der Einheit
    id: 'untereinheiten',
    label: 'Untereinheiten',
    labelFor: (org) => org?.department_label_plural || 'Untereinheiten',
    path: '/untereinheiten',
    icon: icon(
      'M12 3.5v5M12 8.5H6v4M12 8.5h6v4M3.5 12.5h5v4h-5zM9.5 12.5h5v4h-5zM15.5 12.5h5v4h-5zM9.5 17.5v3h5v-3',
    ),
    visible: (org) => !!org && hasUnitsPage(org, (perm) => org.permissions.includes(perm)),
  },
  {
    id: 'termine',
    label: 'Termine',
    path: '/termine',
    icon: icon('M4 6.5h16v13.5H4zM4 10.5h16M8.5 4v4M15.5 4v4M8 14h2M14 14h2M8 17h2'),
    visible: (org, ws) =>
      org
        ? (org.type === 'club' || org.type === 'federation') && org.modules.includes('events')
        : !!(ws.dept?.events_enabled || ws.portal?.events_enabled),
  },
  {
    id: 'wettbewerbe',
    label: 'Wettbewerbe',
    path: '/wettbewerbe',
    icon: icon(
      'M8 4h8v5a4 4 0 0 1-8 0zM8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M8.5 20h7M10 17h4v3h-4z',
    ),
    visible: (org) =>
      !!org &&
      (org.type === 'club' || org.type === 'federation') &&
      org.modules.includes('competitions') &&
      (org.permissions.includes(PERM.competitionsManage) ||
        org.permissions.includes(PERM.competitionsResults)),
  },
  {
    id: 'dokumente',
    label: 'Dokumente',
    path: '/dokumente',
    icon: icon('M6 3h8.5L19 7.5V21H6zM14.5 3v4.5H19M9 12h7M9 15.5h7M9 19h4'),
    visible: (org, ws) =>
      org
        ? (org.type === 'club' || org.type === 'federation') &&
          org.permissions.includes(PERM.docsView)
        : !!(ws.dept || ws.portal),
  },
  {
    id: 'rundschreiben',
    label: 'Rundschreiben',
    path: '/rundschreiben',
    icon: icon('M3 6h18v12H3zM3 6l9 7 9-7'),
    visible: (org, ws) => circularsVisible(org, ws.dept),
  },
  {
    id: 'webseite',
    label: 'Webseite',
    path: '/webseite',
    icon: icon('M3 5h18v14H3zM3 9h18M6 7h.01M8.5 7h.01M7 13h6M7 16h10'),
    visible: (org) =>
      !!org &&
      (org.type === 'club' || org.type === 'federation' || org.type === 'unit') &&
      org.modules.includes('website') &&
      (org.permissions.includes(PERM.websiteManage) ||
        org.permissions.includes(PERM.websiteContent)),
    children: websiteSections,
  },
  {
    id: 'finanzen',
    label: 'Finanzen',
    path: '/finanzen',
    icon: icon('M3 6h18v12H3zM3 10h18M7 14.5h4'),
    visible: (org) => financeSections(financeAccess(org)).length > 0,
    children: (org) => financeSections(financeAccess(org)),
  },
  {
    id: 'abteilung',
    label: 'Abteilung',
    path: '/abteilung',
    icon: icon(
      'M12 6.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5M5 9a2 2 0 1 1 0 4 2 2 0 0 1 0-4M19 9a2 2 0 1 1 0 4 2 2 0 0 1 0-4M7 20c0-2.8 2.2-5 5-5s5 2.2 5 5M2 19c0-2 1.3-3.5 3-3.8M22 19c0-2-1.3-3.5-3-3.8',
    ),
    visible: (_org, ws) => !!ws.dept,
  },
  {
    id: 'mein-bereich',
    label: 'Mein Bereich',
    path: '/mein-bereich',
    icon: icon('M12 4a4 4 0 1 1 0 8 4 4 0 0 1 0-8M4.5 21c.4-4 3.6-6.5 7.5-6.5s7.1 2.5 7.5 6.5'),
    visible: (_org, ws) => !!ws.portal,
    children: () => [
      { to: '/mein-bereich', label: 'Übersicht' },
      { to: '/mein-bereich/ausweis', label: 'Ausweis' },
      { to: '/mein-bereich/rechnungen', label: 'Rechnungen' },
      { to: '/mein-bereich/rundschreiben', label: 'Rundschreiben' },
      { to: '/mein-bereich/daten', label: 'Meine Daten' },
    ],
  },
  {
    id: 'einstellungen',
    label: 'Einstellungen',
    path: '/einstellungen',
    icon: icon(
      'M4 7h8M16 7h4M4 17h4M12 17h8M14 5a2 2 0 1 1 0 4 2 2 0 0 1 0-4M10 15a2 2 0 1 1 0 4 2 2 0 0 1 0-4',
    ),
    visible: (org) => !!org && (org.type !== 'unit' || org.permissions.includes(PERM.rolesManage)),
  },
  {
    id: 'plattform',
    label: 'Plattform',
    path: '/plattform',
    icon: icon('M3 21h18M5 21V8l7-5 7 5v13M10 21v-5h4v5M9 11h.01M15 11h.01'),
    visible: (org) => !!org && org.permissions.includes(PERM.platformManage),
  },
]
