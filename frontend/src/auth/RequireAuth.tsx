import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext.tsx'

const PASSWORD_PAGE = '/mein-konto/anmeldung'

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="page-loading">Lädt …</div>
  if (!user) {
    // Aufgerufene Seite merken: nach der Anmeldung geht es dorthin zurück.
    const from = location.pathname + location.search + location.hash
    return <Navigate to="/anmelden" replace state={from !== '/' ? { from } : undefined} />
  }
  // Startpasswort: zuerst ein eigenes Passwort festlegen (Gesamtaudit 31.10.b, AT-S04)
  if (user.must_change_password && location.pathname !== PASSWORD_PAGE) {
    return <Navigate to={PASSWORD_PAGE} replace />
  }
  return <>{children}</>
}
