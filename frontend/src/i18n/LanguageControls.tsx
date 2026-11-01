// Sprache wählen: im Profil (gespeichert am Konto) und vor der Anmeldung (nur Cookie).
// Beides erscheint nur, wenn der Server mehr als Deutsch freigeschaltet hat.
import { useEffect, useState } from 'react'
import { languageApi } from '../api/language.ts'
import type { LanguageOption } from '../api/language.ts'
import { Alert, SelectField } from '../components/ui.tsx'
import { errorMessage } from '../components/forms.ts'
import { lang, switchLanguage, t } from './index.ts'
import type { Lang } from './index.ts'

const asLang = (code: string): Lang => (code === 'en' ? 'en' : 'de')

/** Mein Konto › Profil: Sprache des Kontos (gilt auch für Mails, Push und die App) */
export function LanguageCard() {
  const [options, setOptions] = useState<LanguageOption[] | null>(null)
  const [value, setValue] = useState<string>(lang())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    languageApi
      .mine()
      .then((data) => {
        if (!alive) return
        setOptions(data.languages)
        if (data.language) setValue(data.language)
      })
      .catch(() => alive && setOptions([]))
    return () => {
      alive = false
    }
  }, [])

  if (!options || options.length < 2) return null

  async function choose(code: string) {
    setError(null)
    setBusy(true)
    try {
      const data = await languageApi.setMine(code)
      setValue(data.language ?? code)
      switchLanguage(asLang(data.language ?? code))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      {/* Immer zweisprachig, damit man zurückfindet */}
      <h2>Sprache / Language</h2>
      <SelectField
        label={t('Sprache der Oberfläche')}
        value={value}
        disabled={busy}
        onChange={(e) => void choose(e.target.value)}
        hint={t(
          'Gilt auch für Hinweis-Mails und die App. Belege und Briefe des Vereins bleiben in der Sprache des Vereins.',
        )}
      >
        {options.map((o) => (
          <option key={o.code} value={o.code}>
            {o.name}
          </option>
        ))}
      </SelectField>
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}

/** Vor der Anmeldung: kleiner Umschalter unten auf der Seite */
export function LanguageSwitch() {
  const [options, setOptions] = useState<LanguageOption[]>([])

  useEffect(() => {
    let alive = true
    languageApi
      .available()
      .then((data) => alive && setOptions(data.languages))
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [])

  const others = options.filter((o) => o.code !== lang())
  if (options.length < 2 || others.length === 0) return null
  return (
    <p className="small language-switch">
      {others.map((o) => (
        <button
          key={o.code}
          type="button"
          className="link-button"
          lang={o.code}
          onClick={() => switchLanguage(asLang(o.code))}
        >
          {o.name}
        </button>
      ))}
    </p>
  )
}
