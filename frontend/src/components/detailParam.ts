// Geöffnete Details (Buchung, Rechnung) stehen in der Adresse (?buchung=12):
// „Zurück“ im Browser schließt sie, Neuladen und Links öffnen denselben Datensatz.
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

export function useDetailParam(name: string) {
  const [params, setParams] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const value = params.get(name)
  const pushedHere = (location.state as { detail?: string } | null)?.detail === name

  function set(v: string | null, push: boolean) {
    const next = new URLSearchParams(params)
    if (v === null) next.delete(name)
    else next.set(name, v)
    setParams(next, push ? { state: { detail: name } } : { replace: true, state: location.state })
  }

  return {
    value,
    /** öffnen: eigener Verlaufseintrag, wenn noch nichts offen ist */
    open: (v: string) => set(v, value === null),
    /** Inhalt wechseln, ohne neuen Verlaufseintrag (z. B. nach dem Speichern) */
    replace: (v: string) => set(v, false),
    close: () => {
      if (value === null) return
      if (pushedHere) navigate(-1)
      else set(null, false)
    },
  }
}
