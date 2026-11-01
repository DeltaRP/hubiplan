// Sprache der Webseite (konzepte/englisch.md, W1): Deutsch oder Englisch für die festen
// Texte der Vereinswebseite. Nur sichtbar, wenn auf dem Server mehr als Deutsch
// freigeschaltet ist oder die Webseite schon eine andere Sprache hat.
import { useEffect, useState, type ReactNode } from 'react'
import { languageApi, type LanguageOption } from '../../api/language.ts'
import { SelectField } from '../../components/ui.tsx'
import { t } from '../../i18n/index.ts'

export function SiteLanguage({
  value,
  error,
  onChange,
  render,
}: {
  value: string
  error?: string
  onChange: (lang: string) => void
  render: (field: ReactNode) => ReactNode
}) {
  const [options, setOptions] = useState<LanguageOption[]>([])
  useEffect(() => {
    let alive = true
    languageApi
      .available()
      .then((data) => alive && setOptions(data.languages))
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])
  const choices = options.some((o) => o.code === value)
    ? options
    : [...options, { code: value, name: value }]
  if (choices.length < 2) return null
  return render(
    <>
      <SelectField
        label={t('Sprache der Webseite')}
        value={value}
        error={error}
        hint={t(
          'Gilt für Menü, Überschriften, Datumsangaben und Meldungen. Namen und eigene Texte zeigt die Webseite so, wie sie hier stehen.',
        )}
        onChange={(e) => onChange(e.target.value)}
      >
        {choices.map((o) => (
          <option key={o.code} value={o.code}>
            {o.name}
          </option>
        ))}
      </SelectField>
      {value !== 'de' && (
        <p className="muted small">
          {t(
            'Impressum und Datenschutzhinweise bleiben auf Deutsch; die Webseite weist darauf hin, dass die deutsche Fassung maßgeblich ist.',
          )}
        </p>
      )}
    </>,
  )
}
