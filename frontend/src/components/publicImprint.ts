// Welche Einheit gehört zur gerade gezeigten öffentlichen Seite (für die Fußzeile)?
import { createContext, useContext, useEffect } from 'react'

export interface PublicImprintTarget {
  key: string
  name: string
}

export const PublicImprintContext = createContext<(target: PublicImprintTarget | null) => void>(
  () => {},
)

/** Öffentliche Seiten einer Einheit (Ausweis, Foto, Abmeldung) verlinken ihr Impressum. */
export function usePublicImprint(key?: string | null, name?: string | null) {
  const setTarget = useContext(PublicImprintContext)
  useEffect(() => {
    setTarget(key && name ? { key, name } : null)
    return () => setTarget(null)
  }, [key, name, setTarget])
}
