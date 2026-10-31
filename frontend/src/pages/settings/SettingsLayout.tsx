import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { PERM } from '../../api/orgs.ts'
import { Tabs } from '../../components/ui.tsx'
import { useOrg } from '../../org/OrgContext.tsx'
import { federationAccess } from '../members/access.ts'

export function SettingsLayout() {
  const { active, can } = useOrg()
  const location = useLocation()

  // Persönliche Einstellungen stehen unter „Mein Konto“ (/mein-konto),
  // hier nur die Einstellungen der gewählten Organisation.
  if (!active) return <Navigate to="/" replace />

  // Arbeitsbereich einer Untereinheit: Stammdaten pflegt die Einheit darüber
  const unit = active.type === 'unit'
  const items = [
    ...(unit ? [] : [{ to: '/einstellungen/organisation', label: 'Organisation' }]),
    ...(unit || active.type === 'platform'
      ? []
      : [
          { to: '/einstellungen/impressum', label: 'Impressum' },
          { to: '/einstellungen/datenschutz', label: 'Datenschutz' },
          { to: '/einstellungen/briefbogen', label: 'Briefbogen' },
        ]),
    // Untereinheit mit eigener Webseite: nur deren Datenschutzhinweise
    ...(unit && active.modules.includes('website') && can(PERM.websiteManage)
      ? [{ to: '/einstellungen/datenschutz', label: 'Datenschutz' }]
      : []),
    // Untereinheiten stehen als eigener Punkt im Hauptmenü (modules.tsx)
    // Dachverband ohne Mitgliederzugriff: kein Menüpunkt Mitglieder, die
    // Einrichtung (Zusatzfelder, Jubiläen) bleibt aber erreichbar.
    ...(active.type === 'federation' && !federationAccess(active) && can(PERM.membersView)
      ? [{ to: '/mitglieder/einrichtung', label: 'Mitglieder-Einrichtung' }]
      : []),
    ...(can(PERM.rolesManage) ? [{ to: '/einstellungen/rollen', label: 'Rollen & Benutzer' }] : []),
    ...(unit ? [] : [{ to: '/einstellungen/erscheinungsbild', label: 'Erscheinungsbild' }]),
    ...(active.type !== 'platform' &&
    (can(PERM.dataExport) || (active.type === 'club' && can(PERM.orgEdit)))
      ? [{ to: '/einstellungen/datenuebernahme', label: 'Datenübernahme' }]
      : []),
    ...((active.type === 'federation' || active.type === 'club') && can(PERM.peeringManage)
      ? [{ to: '/einstellungen/verbund', label: 'Verbund' }]
      : []),
    ...(can(PERM.auditView)
      ? [
          { to: '/einstellungen/protokoll', label: 'Protokoll' },
          { to: '/einstellungen/postausgang', label: 'Postausgang' },
        ]
      : []),
  ]

  if (location.pathname.replace(/\/$/, '') === '/einstellungen') {
    if (items.length === 0) return <Navigate to="/" replace />
    return <Navigate to={items[0].to} replace />
  }

  return (
    <section>
      <h1>Einstellungen</h1>
      <p className="muted">{active.name}</p>
      <Tabs items={items} />
      <Outlet />
    </section>
  )
}
