// Bezeichnung einer Einheit (z. B. „Verein“, „Zug“) mit Artikel und Genitiv,
// damit Texte grammatisch stimmen. Genutzt für die eigene Bezeichnung einer
// Einheit und für die Bezeichnung ihrer Untereinheiten.
import { useEffect, useState } from 'react'
import { Field, SelectField } from './ui.tsx'
import { buildTerms, buildTermsEn, englishLabel, genitiveOf } from '../org/terms.ts'
import { t } from '../i18n/index.ts'
import { availableLanguages } from '../api/language.ts'

export type Gender = 'f' | 'm' | 'n'

export interface LabelValue {
  label: string
  plural: string
  gender: Gender
  genitive: string
  /** Englische Bezeichnung (optional; leer: Vorgabe bzw. die deutsche) */
  labelEn?: string
  pluralEn?: string
}

/** Ob Englisch auf dieser Instanz wählbar ist (sonst keine englischen Felder). */
function useEnglishAvailable(): boolean {
  const [on, setOn] = useState(false)
  useEffect(() => {
    let alive = true
    availableLanguages()
      .then((data) => alive && setOn(data.languages.some((l) => l.code === 'en')))
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])
  return on
}

export function LabelFields({
  value,
  errors = {},
  onChange,
  preview = 'own',
  testId,
}: {
  value: LabelValue
  /** Fehler je Teil: label, plural, gender, genitive */
  errors?: Partial<Record<keyof LabelValue, string>>
  onChange: (next: LabelValue) => void
  /** Beispielsätze: für die eigene Einheit oder für Untereinheiten */
  preview?: 'own' | 'children'
  testId?: string
}) {
  const tm = buildTerms(value.label, value.plural, value.gender, value.genitive)
  const set = (part: Partial<LabelValue>) => onChange({ ...value, ...part })
  const english = useEnglishAvailable() && value.labelEn !== undefined
  const [enDefault, enDefaultPlural] = englishLabel(value.label, value.plural)
  const en = buildTermsEn(value.label, value.plural, value.gender, value.labelEn, value.pluralEn)
  return (
    <>
      <div className="grid-2">
        <Field
          label={t('Bezeichnung (Einzahl)')}
          value={value.label}
          error={errors.label}
          onChange={(e) => set({ label: e.target.value })}
        />
        <Field
          label={t('Bezeichnung (Mehrzahl)')}
          value={value.plural}
          error={errors.plural}
          onChange={(e) => set({ plural: e.target.value })}
        />
        <SelectField
          label={t('Artikel')}
          value={value.gender}
          error={errors.gender}
          onChange={(e) => set({ gender: e.target.value as Gender })}
        >
          <option value="f">{t('die (z. B. die Sparte)')}</option>
          <option value="m">{t('der (z. B. der Zug)')}</option>
          <option value="n">{t('das (z. B. das Korps)')}</option>
        </SelectField>
        <Field
          label={t('Genitiv, nur falls abweichend')}
          placeholder={genitiveOf(value.label, value.gender)}
          hint={t('Leer lassen, wenn die Form im Beispiel unten stimmt.')}
          value={value.genitive}
          error={errors.genitive}
          onChange={(e) => set({ genitive: e.target.value })}
        />
      </div>
      <p className="muted small" data-testid={testId}>
        {preview === 'own'
          ? t('So erscheint es: Mitglied {im} · Vorstand {gen} · Mitglied {eines_anderen}', {
              im: tm.im,
              gen: tm.gen,
              eines_anderen: tm.eines_anderen,
            })
          : t(
              'So erscheint es: {Nom} · Mitglieder {gen} · Rollen in {diesem} · Termine in {pl_dat}',
              { Nom: tm.Nom, gen: tm.gen, diesem: tm.diesem, pl_dat: tm.pl_dat },
            )}
      </p>
      {english && (
        <>
          <div className="grid-2">
            <Field
              label={t('Englisch (Einzahl)')}
              placeholder={enDefault}
              hint={t('Optional, für die englische Oberfläche. Leer: „{x}“.', { x: enDefault })}
              value={value.labelEn ?? ''}
              error={errors.labelEn}
              onChange={(e) => set({ labelEn: e.target.value })}
            />
            <Field
              label={t('Englisch (Mehrzahl)')}
              placeholder={value.labelEn || enDefaultPlural}
              value={value.pluralEn ?? ''}
              error={errors.pluralEn}
              onChange={(e) => set({ pluralEn: e.target.value })}
            />
          </div>
          <p className="muted small" lang="en" data-testid={testId && `${testId}-en`}>
            {t('Auf Englisch: {a} · {b} · {c}', { a: en.Nom, b: en.ein, c: en.pl })}
          </p>
        </>
      )}
    </>
  )
}
