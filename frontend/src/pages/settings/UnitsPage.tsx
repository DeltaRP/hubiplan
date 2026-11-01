// Untereinheiten (z. B. Züge): eigener Punkt im Hauptmenü unter /untereinheiten, benannt nach
// der Bezeichnung der Einheit (Ralf 2026-10-30, vorher unter Einstellungen).
// Was darunter liegt, hängt nur an den Schaltern der Einheit: Einheiten mit eigenen Mitgliedern
// zeigen ihren Baum der Untereinheiten, andere die Einheiten mit eigenen Mitgliedern darunter.
import { Navigate, useLocation } from 'react-router-dom'
import { PERM } from '../../api/orgs.ts'
import { Alert } from '../../components/ui.tsx'
import { useActiveOrg, useOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'
import { ClubsPage } from './ClubsPage.tsx'
import { DepartmentsPage } from './DepartmentsPage.tsx'
import { t } from '../../i18n/index.ts'

export function UnitsPage() {
  const org = useActiveOrg()
  const { can } = useOrg()
  if (org.type === 'club') return <DepartmentsPage />
  if (org.type === 'federation' && can(PERM.clubsManage)) return <ClubsPage />
  return <Alert kind="info">{t('Hier gibt es keine Untereinheiten zu pflegen.')}</Alert>
}

/** Seite im Hauptmenü: Überschrift mit der eigenen Bezeichnung, darunter die Pflege */
export function UnitsArea() {
  const org = useActiveOrg()
  const tm = useTerms()
  return (
    <section>
      <h1>{org.department_label_plural || tm.Pl}</h1>
      <p className="muted">{org.name}</p>
      <UnitsPage />
    </section>
  )
}

/** Frühere Adressen unter Einstellungen; Abfrage (z. B. ?import=…) bleibt erhalten */
export function UnitsRedirect() {
  const { search } = useLocation()
  return <Navigate to={`/untereinheiten${search}`} replace />
}
