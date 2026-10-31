// Bezeichnung einer Einheit (z. B. „Verein“, „Zug“) mit Artikel und Genitiv,
// damit Texte grammatisch stimmen. Genutzt für die eigene Bezeichnung einer
// Einheit und für die Bezeichnung ihrer Untereinheiten.
import { Field, SelectField } from './ui.tsx'
import { buildTerms, genitiveOf } from '../org/terms.ts'

export type Gender = 'f' | 'm' | 'n'

export interface LabelValue {
  label: string
  plural: string
  gender: Gender
  genitive: string
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
  const t = buildTerms(value.label, value.plural, value.gender, value.genitive)
  const set = (part: Partial<LabelValue>) => onChange({ ...value, ...part })
  return (
    <>
      <div className="grid-2">
        <Field
          label="Bezeichnung (Einzahl)"
          value={value.label}
          error={errors.label}
          onChange={(e) => set({ label: e.target.value })}
        />
        <Field
          label="Bezeichnung (Mehrzahl)"
          value={value.plural}
          error={errors.plural}
          onChange={(e) => set({ plural: e.target.value })}
        />
        <SelectField
          label="Artikel"
          value={value.gender}
          error={errors.gender}
          onChange={(e) => set({ gender: e.target.value as Gender })}
        >
          <option value="f">die (z. B. die Sparte)</option>
          <option value="m">der (z. B. der Zug)</option>
          <option value="n">das (z. B. das Korps)</option>
        </SelectField>
        <Field
          label="Genitiv, nur falls abweichend"
          placeholder={genitiveOf(value.label, value.gender)}
          hint="Leer lassen, wenn die Form im Beispiel unten stimmt."
          value={value.genitive}
          error={errors.genitive}
          onChange={(e) => set({ genitive: e.target.value })}
        />
      </div>
      <p className="muted small" data-testid={testId}>
        {preview === 'own'
          ? `So erscheint es: Mitglied ${t.im} · Vorstand ${t.gen} · Mitglied ${t.eines_anderen}`
          : `So erscheint es: ${t.Nom} · Mitglieder ${t.gen} · Rollen in ${t.diesem} · Termine in ${t.pl_dat}`}
      </p>
    </>
  )
}
