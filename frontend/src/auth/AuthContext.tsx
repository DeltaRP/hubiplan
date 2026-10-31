import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import * as api from '../api/auth.ts'
import type { User } from '../api/auth.ts'
import { bindUndoToUser, clearUndo } from '../components/undo.ts'

interface AuthState {
  user: User | null
  loading: boolean
  setUser: (user: User | null) => void
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api
      .getSession()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  const logout = useCallback(async () => {
    // Wirft, wenn der Server die Abmeldung ablehnt: dann bleibt man sichtbar angemeldet.
    await api.logout()
    clearUndo()
    setUser(null)
  }, [])

  useEffect(() => {
    if (user) bindUndoToUser(user.id)
  }, [user])

  const value = useMemo(() => ({ user, loading, setUser, logout }), [user, loading, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// oxlint-disable-next-line react/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth muss innerhalb von AuthProvider genutzt werden.')
  return ctx
}
