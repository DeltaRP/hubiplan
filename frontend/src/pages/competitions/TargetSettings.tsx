// Scheibe, Wertungsart und Gleichstandskette einer Einzelwertung (Schießscheiben Schritt 1).
import type { CustomTarget, ScoringMethod, TargetCatalog } from '../../api/competitions.ts'
import { Field, SelectField } from '../../components/ui.tsx'
import { HowTo, Term, Why } from '../../learning/Aids.tsx'
import { TargetPicker } from './TargetPicker.tsx'
import { t } from '../../i18n/index.ts'

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
  dsb: t('wie DSB (Auflage)'),
  bhds: t('wie BHDS'),
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
  const chosen = catalog.targets.find((tm) => tm.key === v.target)
  const custom = v.target === catalog.custom
  const ct = { ...EMPTY_CUSTOM, ...(v.custom_target as CustomTarget) }
  const setCustom = (patch: Partial<CustomTarget>) => set('custom_target', { ...ct, ...patch })
  const labels = Object.fromEntries(catalog.tie_breaks.map((tm) => [tm.value, tm.label]))
  const unused = catalog.tie_breaks.filter((tm) => !v.tie_breaks.includes(tm.value))

  function move(index: number, by: -1 | 1) {
    const next = [...v.tie_breaks]
    const [item] = next.splice(index, 1)
    next.splice(index + by, 0, item)
    set('tie_breaks', next)
  }

  return (
    <div className="stack">
      <h4>{t('Scheibe und Wertung')}</h4>
      <TargetPicker
        targets={catalog.targets}
        value={v.target}
        customKey={catalog.custom}
        error={errors.target}
        onChange={(key) => {
          set('target', key)
          if (!key && v.method !== 'frei') set('method', 'frei')
          if (key === catalog.custom && !v.custom_target?.top_diameter) {
            set('custom_target', EMPTY_CUSTOM)
          }
        }}
      />
      <div className="grid-3">
        <SelectField
          label={t('Wertungsart')}
          value={v.method}
          error={errors.method}
          hint={v.target ? undefined : t('Ringe, Zehntel und Teiler brauchen eine Scheibe.')}
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
          {t('Zehn {x} mm, Ringe {x2} mm breit, Ringe  {lowest} bis', {
            x: fmt(chosen.top_diameter),
            x2: fmt(chosen.ring_width),
            lowest: chosen.lowest,
          })}{' '}
          {chosen.top}
          {chosen.inner_diameter ? (
            <>
              {t(', mit')} <Term k="comp_inner">{t('Innenzehner')}</Term>
            </>
          ) : (
            ''
          )}
          {t(', höchstens')} {chosen.max_decimal.replace('.', ',')} in{' '}
          <Term k="comp_decimal">{t('Zehnteln')}</Term>
          {chosen.black_diameter ? (
            <>
              , <Term k="comp_spot">{t('Spiegel')}</Term> {fmt(chosen.black_diameter)} mm
            </>
          ) : (
            ''
          )}
          {t('; der')} <Term k="comp_teiler">{t('Teiler')}</Term>{' '}
          {t('ist der Abstand in 1/100 mm.')} {chosen.note}
        </p>
      )}
      {chosen && <HowTo k="how_comp_score" />}
      {custom && (
        <div className="grid-3">
          <Field
            label={t('Name der Scheibe')}
            value={ct.name ?? ''}
            onChange={(e) => setCustom({ name: e.target.value })}
          />
          <Field
            label={t('Durchmesser höchster Ring (mm)')}
            inputMode="decimal"
            value={String(ct.top_diameter ?? '')}
            error={errors.top_diameter}
            onChange={(e) => setCustom({ top_diameter: num(e.target.value) })}
          />
          <Field
            label={t('Ringbreite (mm)')}
            inputMode="decimal"
            value={String(ct.ring_width ?? '')}
            error={errors.ring_width}
            onChange={(e) => setCustom({ ring_width: num(e.target.value) })}
          />
          <Field
            label={t('Kaliber (mm)')}
            inputMode="decimal"
            value={String(ct.caliber ?? '')}
            error={errors.caliber}
            onChange={(e) => setCustom({ caliber: num(e.target.value) })}
          />
          <Field
            label={t('Höchster Ring')}
            type="number"
            min={1}
            max={20}
            value={ct.top ?? 10}
            error={errors.top}
            onChange={(e) => setCustom({ top: Number(e.target.value) || 10 })}
          />
          <Field
            label={t('Niedrigster Ring')}
            type="number"
            min={1}
            max={20}
            value={ct.lowest ?? 1}
            error={errors.lowest}
            onChange={(e) => setCustom({ lowest: Number(e.target.value) || 1 })}
          />
          <Field
            label={t('Innenzehner (mm)')}
            inputMode="decimal"
            hint={t('leer: gibt es nicht')}
            value={String(ct.inner_diameter ?? '')}
            error={errors.inner_diameter}
            onChange={(e) => setCustom({ inner_diameter: num(e.target.value) || null })}
          />
          <SelectField
            label={t('Innenzehner zählt, wenn …')}
            value={ct.inner_mode}
            onChange={(e) =>
              setCustom({ inner_mode: e.target.value as CustomTarget['inner_mode'] })
            }
          >
            <option value="beruehren">{t('der Lochrand ihn berührt')}</option>
            <option value="wegschiessen">{t('der Punkt ganz weggeschossen ist')}</option>
          </SelectField>
          <Field
            label={t('Spiegel (mm)')}
            inputMode="decimal"
            hint={t('schwarze Fläche, nur zum Zeichnen')}
            value={String(ct.black_diameter ?? '')}
            error={errors.black_diameter}
            onChange={(e) => setCustom({ black_diameter: num(e.target.value) || null })}
          />
          <Field
            label={t('Scheibenbilder je Karte')}
            type="number"
            min={1}
            max={20}
            value={ct.spots ?? 1}
            error={errors.spots}
            onChange={(e) => setCustom({ spots: Number(e.target.value) || 1 })}
          />
          <Field
            label={t('Teilerfaktor')}
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
          <h4>{t('Bei Gleichstand')}</h4>
          <p className="muted small">
            {t(
              'Die Regeln gelten der Reihe nach, wenn für alle Gleichen Treffer erfasst sind. Bleibt es gleich, teilen sie sich den Platz; auf Preisplätzen folgt ein Stechen.',
            )}
          </p>
          <Why k="comp_tie_breaks" />
          {v.tie_breaks.length > 0 ? (
            <ol className="plain-list">
              {v.tie_breaks.map((key, i) => (
                <li key={key}>
                  {i + 1}. {labels[key] ?? key}{' '}
                  <button
                    type="button"
                    className="link-button"
                    disabled={i === 0}
                    aria-label={t('{x} nach oben', { x: labels[key] })}
                    onClick={() => move(i, -1)}
                  >
                    ↑
                  </button>{' '}
                  <button
                    type="button"
                    className="link-button"
                    disabled={i === v.tie_breaks.length - 1}
                    aria-label={t('{x} nach unten', { x: labels[key] })}
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
            <p className="muted small">{t('Keine Regeln: gleicher Wert, gleicher Platz.')}</p>
          )}
          {errors.tie_breaks && <p className="field-error">{errors.tie_breaks}</p>}
          <div className="button-row">
            {unused.length > 0 && (
              <SelectField
                label={t('Regel hinzufügen')}
                value=""
                onChange={(e) =>
                  e.target.value && set('tie_breaks', [...v.tie_breaks, e.target.value])
                }
              >
                <option value="">{t('wählen …')}</option>
                {unused.map((tm) => (
                  <option key={tm.value} value={tm.value}>
                    {tm.label}
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
              label={t('Schüsse je Serie')}
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
