import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext.tsx'
import { t } from '../i18n/index.ts'

const PASSWORD_PAGE = '/mein-konto/anmeldung'

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="page-loading">{t('Lädt …')}</div>
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

/** Wie RequireAuth; ist der Server beim Start nicht erreichbar, geht es trotzdem weiter
 * (Standmodus ohne Empfang arbeitet mit dem Speicher auf dem Gerät). */
export function RequireAuthOrOffline({ children }: { children: ReactNode }) {
  const { user, loading, offline } = useAuth()
  if (!loading && !user && offline) return <>{children}</>
  return <RequireAuth>{children}</RequireAuth>
}
