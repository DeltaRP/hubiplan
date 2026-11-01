// Scheibe, Wertungsart und Gleichstandskette einer Einzelwertung (Schießscheiben Schritt 1).
import type { CustomTarget, ScoringMethod, TargetCatalog } from '../../api/competitions.ts'
import { Field, SelectField } from '../../components/ui.tsx'
import { Why } from '../../learning/Aids.tsx'

export interface TargetValues {
  target: string
  custom_target: CustomTarget | Record<string, never>
  method: ScoringMethod
  tie_breaks: string[]
  series_size: number
}

const EMPTY_CUSTOM: CustomTarget = {
  name: '',
  top_diameter: '',
  ring_width: '',
  caliber: '4.5',
  top: 10,
  lowest: 1,
  inner_diameter: null,
  inner_mode: 'beruehren',
  black_diameter: null,
  spots: 1,
  teiler_factor: 1,
}

const PRESET_LABELS: Record<string, string> = {
  dsb: 'wie DSB (Auflage)',
  bhds: 'wie BHDS',
}

function num(v: string): string {
  return v.replace(',', '.')
}

export function TargetSettings({
  catalog,
  values: v,
  set,
  errors,
}: {
  catalog: TargetCatalog
  values: TargetValues
  set: <K extends keyof TargetValues>(key: K, value: TargetValues[K]) => void
  errors: Record<string, string>
}) {
  const groups = [...new Set(catalog.targets.map((t) => t.group))]
  const chosen = catalog.targets.find((t) => t.key === v.target)
  const custom = v.target === catalog.custom
  const ct = { ...EMPTY_CUSTOM, ...(v.custom_target as CustomTarget) }
  const setCustom = (patch: Partial<CustomTarget>) => set('custom_target', { ...ct, ...patch })
  const labels = Object.fromEntries(catalog.tie_breaks.map((t) => [t.value, t.label]))
  const unused = catalog.tie_breaks.filter((t) => !v.tie_breaks.includes(t.value))

  function move(index: number, by: -1 | 1) {
    const next = [...v.tie_breaks]
    const [item] = next.splice(index, 1)
    next.splice(index + by, 0, item)
    set('tie_breaks', next)
  }

  return (
    <div className="stack">
      <h4>Scheibe und Wertung</h4>
      <div className="grid-3">
        <SelectField
          label="Scheibe"
          value={v.target}
          error={errors.target}
          onChange={(e) => {
            const key = e.target.value
            set('target', key)
            if (!key && v.method !== 'frei') set('method', 'frei')
            if (key === catalog.custom && !v.custom_target?.top_diameter) {
              set('custom_target', EMPTY_CUSTOM)
            }
          }}
        >
          <option value="">keine (nur Summe eingeben)</option>
          {groups.map((g) => (
            <optgroup key={g} label={g}>
              {catalog.targets
                .filter((t) => t.group === g)
                .map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.name}
                  </option>
                ))}
            </optgroup>
          ))}
          <option value={catalog.custom}>Eigene Scheibe …</option>
        </SelectField>
        <SelectField
          label="Wertungsart"
          value={v.method}
          error={errors.method}
          hint={v.target ? undefined : 'Ringe, Zehntel und Teiler brauchen eine Scheibe.'}
          onChange={(e) => set('method', e.target.value as ScoringMethod)}
        >
          {catalog.methods.map((m) => (
            <option key={m.value} value={m.value} disabled={m.value !== 'frei' && !v.target}>
              {m.label}
            </option>
          ))}
        </SelectField>
      </div>
      {chosen && (
        <p className="muted small">
          Zehn {fmt(chosen.top_diameter)} mm, Ringe {fmt(chosen.ring_width)} mm breit, Ringe{' '}
          {chosen.lowest} bis {chosen.top}
          {chosen.inner_diameter ? ', mit Innenzehner' : ''}, höchstens{' '}
          {chosen.max_decimal.replace('.', ',')} in Zehnteln. {chosen.note}
        </p>
      )}
      {custom && (
        <div className="grid-3">
          <Field
            label="Name der Scheibe"
            value={ct.name ?? ''}
            onChange={(e) => setCustom({ name: e.target.value })}
          />
          <Field
            label="Durchmesser höchster Ring (mm)"
            inputMode="decimal"
            value={String(ct.top_diameter ?? '')}
            error={errors.top_diameter}
            onChange={(e) => setCustom({ top_diameter: num(e.target.value) })}
          />
          <Field
            label="Ringbreite (mm)"
            inputMode="decimal"
            value={String(ct.ring_width ?? '')}
            error={errors.ring_width}
            onChange={(e) => setCustom({ ring_width: num(e.target.value) })}
          />
          <Field
            label="Kaliber (mm)"
            inputMode="decimal"
            value={String(ct.caliber ?? '')}
            error={errors.caliber}
            onChange={(e) => setCustom({ caliber: num(e.target.value) })}
          />
          <Field
            label="Höchster Ring"
            type="number"
            min={1}
            max={20}
            value={ct.top ?? 10}
            error={errors.top}
            onChange={(e) => setCustom({ top: Number(e.target.value) || 10 })}
          />
          <Field
            label="Niedrigster Ring"
            type="number"
            min={1}
            max={20}
            value={ct.lowest ?? 1}
            error={errors.lowest}
            onChange={(e) => setCustom({ lowest: Number(e.target.value) || 1 })}
          />
          <Field
            label="Innenzehner (mm)"
            inputMode="decimal"
            hint="leer: gibt es nicht"
            value={String(ct.inner_diameter ?? '')}
            error={errors.inner_diameter}
            onChange={(e) => setCustom({ inner_diameter: num(e.target.value) || null })}
          />
          <SelectField
            label="Innenzehner zählt, wenn …"
            value={ct.inner_mode}
            onChange={(e) =>
              setCustom({ inner_mode: e.target.value as CustomTarget['inner_mode'] })
            }
          >
            <option value="beruehren">der Lochrand ihn berührt</option>
            <option value="wegschiessen">der Punkt ganz weggeschossen ist</option>
          </SelectField>
          <Field
            label="Spiegel (mm)"
            inputMode="decimal"
            hint="schwarze Fläche, nur zum Zeichnen"
            value={String(ct.black_diameter ?? '')}
            error={errors.black_diameter}
            onChange={(e) => setCustom({ black_diameter: num(e.target.value) || null })}
          />
          <Field
            label="Scheibenbilder je Karte"
            type="number"
            min={1}
            max={20}
            value={ct.spots ?? 1}
            error={errors.spots}
            onChange={(e) => setCustom({ spots: Number(e.target.value) || 1 })}
          />
          <Field
            label="Teilerfaktor"
            inputMode="decimal"
            value={String(ct.teiler_factor ?? 1)}
            error={errors.teiler_factor}
            onChange={(e) => setCustom({ teiler_factor: num(e.target.value) })}
          />
        </div>
      )}
      {errors.custom_target && <p className="field-error">{errors.custom_target}</p>}
      {v.target && (
        <>
          <h4>Bei Gleichstand</h4>
          <p className="muted small">
            Die Regeln gelten der Reihe nach, wenn für alle Gleichen Treffer erfasst sind. Bleibt es
            gleich, teilen sie sich den Platz; auf Preisplätzen folgt ein Stechen.
          </p>
          {v.tie_breaks.length > 0 ? (
            <ol className="plain-list">
              {v.tie_breaks.map((key, i) => (
                <li key={key}>
                  {i + 1}. {labels[key] ?? key}{' '}
                  <button
                    type="button"
                    className="link-button"
                    disabled={i === 0}
                    aria-label={`${labels[key]} nach oben`}
                    onClick={() => move(i, -1)}
                  >
                    ↑
                  </button>{' '}
                  <button
                    type="button"
                    className="link-button"
                    disabled={i === v.tie_breaks.length - 1}
                    aria-label={`${labels[key]} nach unten`}
                    onClick={() => move(i, 1)}
                  >
                    ↓
                  </button>{' '}
                  <button
                    type="button"
                    className="link-button"
                    onClick={() =>
                      set(
                        'tie_breaks',
                        v.tie_breaks.filter((k) => k !== key),
                      )
                    }
                  >
                    entfernen
                  </button>
                </li>
              ))}
            </ol>
          ) : (
            <p className="muted small">Keine Regeln: gleicher Wert, gleicher Platz.</p>
          )}
          {errors.tie_breaks && <p className="field-error">{errors.tie_breaks}</p>}
          <div className="button-row">
            {unused.length > 0 && (
              <SelectField
                label="Regel hinzufügen"
                value=""
                onChange={(e) =>
                  e.target.value && set('tie_breaks', [...v.tie_breaks, e.target.value])
                }
              >
                <option value="">wählen …</option>
                {unused.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </SelectField>
            )}
            {Object.entries(catalog.presets).map(([key, chain]) => (
              <button
                key={key}
                type="button"
                className="button button-ghost"
                onClick={() => set('tie_breaks', chain)}
              >
                {PRESET_LABELS[key] ?? key}
              </button>
            ))}
          </div>
          {v.tie_breaks.includes('serien') && (
            <Field
              label="Schüsse je Serie"
              type="number"
              min={1}
              max={100}
              value={v.series_size}
              error={errors.series_size}
              onChange={(e) => set('series_size', Number(e.target.value) || 10)}
            />
          )}
        </>
      )}
      <Why k="comp_target" />
    </div>
  )
}

function fmt(n: number): string {
  return String(n).replace('.', ',')
}
