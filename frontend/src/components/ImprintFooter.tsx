import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { imprintPath, privacyPath } from '../api/imprint.ts'
import { displayName } from '../api/orgs.ts'
import { useOrg } from '../org/OrgContext.tsx'
import { PublicImprintContext } from './publicImprint.ts'
import type { PublicImprintTarget } from './publicImprint.ts'
import { formatTitle } from './pageTitle.ts'

// Ein Link je Seite: Mit Einheit zeigt die Seite zuerst die Einheit, dann die Plattform.
function FooterLinks({ unit }: { unit: PublicImprintTarget | null }) {
  return (
    <nav className="site-footer" aria-label="Rechtliches">
      <Link to={imprintPath(unit?.key)}>Impressum</Link>
      <Link to={privacyPath(unit?.key)}>Datenschutz</Link>
      <Link to="/lizenz">Lizenzen</Link>
      <Link to="/barrierefreiheit">Barrierefreiheit</Link>
    </nav>
  )
}

/** Rahmen der öffentlichen Seiten (ohne Anmeldung) mit Fußzeile. */
// Titel der öffentlichen Seiten (ohne Token oder Namen aus der Adresse)
const PUBLIC_TITLES: [string, string][] = [
  ['/anmelden/link', 'Anmeldung per Link'],
  ['/anmelden', 'Anmelden'],
  ['/konto/email', 'E-Mail-Adresse bestätigen'],
  ['/passwort-vergessen', 'Passwort vergessen'],
  ['/passwort-zuruecksetzen', 'Passwort zurücksetzen'],
  ['/foto', 'Foto hochladen'],
  ['/rundschreiben/abmelden', 'Rundschreiben abbestellen'],
  ['/ausweis', 'Mitgliedsausweis'],
  ['/impressum', 'Impressum'],
  ['/datenschutz', 'Datenschutz'],
  ['/lizenz', 'Lizenzen'],
  ['/barrierefreiheit', 'Barrierefreiheit'],
]

export function PublicShell() {
  const [unit, setUnit] = useState<PublicImprintTarget | null>(null)
  const { pathname } = useLocation()
  const title = PUBLIC_TITLES.find(([prefix]) => pathname.startsWith(prefix))?.[1]
  useEffect(() => {
    document.title = formatTitle(title)
  }, [title])
  return (
    <PublicImprintContext.Provider value={setUnit}>
      <div className="public-shell">
        <Outlet />
        <FooterLinks unit={unit} />
      </div>
    </PublicImprintContext.Provider>
  )
}

/** Fußzeile in der App: Plattform und die gerade gewählte Einheit. */
export function AppFooter() {
  const { active, activeDept, activePortal } = useOrg()
  let unit: PublicImprintTarget | null = null
  if (active && active.type !== 'platform' && active.imprint_key)
    unit = { key: active.imprint_key, name: displayName(active) }
  else if (activeDept?.imprint_key)
    unit = { key: activeDept.imprint_key, name: displayName(activeDept) }
  else if (activePortal?.imprint_key)
    unit = {
      key: activePortal.imprint_key,
      name: activePortal.club_display_name || activePortal.club_name,
    }
  return <FooterLinks unit={unit} />
}
