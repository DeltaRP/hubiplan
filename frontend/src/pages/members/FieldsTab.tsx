import { useState } from 'react'
import { fieldApi } from '../../api/fields.ts'
import type { FieldType, FieldValue, MemberField, Scalar, Subfield } from '../../api/fields.ts'
import { useAutoSave, useLoad } from '../../components/forms.ts'
import { Alert, SaveStatus } from '../../components/ui.tsx'

/** Reiter „Zusatzfelder“ der Mitgliedsakte. */
export function FieldsTab({
  orgId,
  memberId,
  canEdit,
}: {
  orgId: number
  memberId: number
  canEdit: boolean
}) {
  // Die Werte tragen die Person, zu der sie gehören: Nach einem Wechsel zu einer
  // anderen Person dürfen die alten Werte weder angezeigt noch gespeichert werden.
  const { data, error, setData } = useLoad(
    () => fieldApi.memberValues(orgId, memberId).then((fields) => ({ memberId, fields })),
    [orgId, memberId],
  )
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data || data.memberId !== memberId) return <p className="muted">Lädt …</p>
  if (data.fields.length === 0) {
    return (
      <div className="card card-wide empty-state">
        <p>Es sind noch keine Zusatzfelder angelegt (Einstellungen → Zusatzfelder).</p>
      </div>
    )
  }
  return (
    <FieldsForm
      key={memberId}
      orgId={orgId}
      memberId={memberId}
      fields={data.fields}
      canEdit={canEdit}
      onSaved={(fields) => setData({ memberId, fields })}
    />
  )
}

function FieldsForm({
  orgId,
  memberId,
  fields,
  canEdit,
  onSaved,
}: {
  orgId: number
  memberId: number
  fields: MemberField[]
  canEdit: boolean
  onSaved: (f: MemberField[]) => void
}) {
  const [values, setValues] = useState<Record<string, FieldValue>>(() =>
    Object.fromEntries(fields.map((f) => [String(f.definition.id), f.value])),
  )
  const [errors, setErrors] = useState<Record<string, string>>({})
  const auto = useAutoSave(
    { values, setErrors },
    (changes) => fieldApi.saveMemberValues(orgId, memberId, changes as Record<string, FieldValue>),
    { enabled: canEdit, onSaved: (saved) => onSaved(saved as MemberField[]) },
  )

  const set = (id: number, value: FieldValue) => setValues((v) => ({ ...v, [String(id)]: value }))

  return (
    <form className="card card-wide" onSubmit={(e) => e.preventDefault()}>
      {canEdit && <SaveStatus auto={auto} />}
      <fieldset disabled={!canEdit}>
        {fields.map(({ definition: d }) => {
          const value = values[String(d.id)]
          const err = errors[String(d.id)]
          return (
            <div key={d.id} className={`field${err ? ' field-invalid' : ''}`}>
              <span>
                {d.label}
                {d.inherited && <small className="muted"> · {d.owner_name}</small>}
              </span>
              {d.repeatable ? (
                <RepeatableInput
                  subfields={d.subfields}
                  rows={(value as Record<string, Scalar>[]) ?? []}
                  onChange={(rows) => set(d.id, rows)}
                />
              ) : (
                <ScalarInput
                  label={d.label}
                  type={d.field_type}
                  choices={d.choices}
                  value={value as Scalar}
                  onChange={(x) => set(d.id, x)}
                />
              )}
              {d.help_text && <small className="muted">{d.help_text}</small>}
              {err && <small className="field-error">{err}</small>}
            </div>
          )
        })}
      </fieldset>
    </form>
  )
}

function ScalarInput({
  label,
  type,
  choices,
  value,
  onChange,
}: {
  label: string
  type: FieldType
  choices?: string[]
  value: Scalar
  onChange: (v: Scalar) => void
}) {
  if (type === 'bool') {
    return (
      <select
        aria-label={label}
        value={value === null ? '' : value ? 'ja' : 'nein'}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value === 'ja')}
      >
        <option value="">–</option>
        <option value="ja">ja</option>
        <option value="nein">nein</option>
      </select>
    )
  }
  if (type === 'choice') {
    return (
      <select
        aria-label={label}
        value={(value as string) ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">–</option>
        {(choices ?? []).map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    )
  }
  if (type === 'yearrange') {
    return <YearRangeInput label={label} value={value} onChange={onChange} />
  }
  return (
    <input
      aria-label={label}
      type={type === 'date' ? 'date' : type === 'number' ? 'text' : 'text'}
      inputMode={type === 'number' ? 'decimal' : undefined}
      value={value === null || value === undefined ? '' : String(value)}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

/** Startjahr und optionales Endjahr, gespeichert als „JJJJ“ oder „JJJJ/JJJJ“. */
function YearRangeInput({
  label,
  value,
  onChange,
}: {
  label: string
  value: Scalar
  onChange: (v: Scalar) => void
}) {
  const text = value === null || value === undefined ? '' : String(value)
  const [start = '', end = ''] = text.split('/')
  const join = (s: string, e: string) => {
    const a = s.trim()
    const b = e.trim()
    return a || b ? (b ? `${a}/${b}` : a) : null
  }
  return (
    <span className="year-range">
      <input
        aria-label={`${label}: Startjahr`}
        placeholder="Startjahr"
        inputMode="numeric"
        maxLength={4}
        value={start}
        onChange={(e) => onChange(join(e.target.value, end))}
      />
      <span aria-hidden="true">/</span>
      <input
        aria-label={`${label}: Endjahr`}
        placeholder="Endjahr (optional)"
        inputMode="numeric"
        maxLength={4}
        value={end}
        onChange={(e) => onChange(join(start, e.target.value))}
      />
    </span>
  )
}

function RepeatableInput({
  subfields,
  rows,
  onChange,
}: {
  subfields: Subfield[]
  rows: Record<string, Scalar>[]
  onChange: (rows: Record<string, Scalar>[]) => void
}) {
  const empty = () =>
    Object.fromEntries(subfields.map((s) => [s.key!, null])) as Record<string, Scalar>
  return (
    <div className="repeatable">
      {rows.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              {subfields.map((s) => (
                <th key={s.key}>{s.label}</th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {subfields.map((s) => (
                  <td key={s.key}>
                    <ScalarInput
                      label={s.label}
                      type={s.type}
                      choices={s.choices}
                      value={row[s.key!] ?? null}
                      onChange={(v) =>
                        onChange(rows.map((r, j) => (j === i ? { ...r, [s.key!]: v } : r)))
                      }
                    />
                  </td>
                ))}
                <td className="actions">
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onChange(rows.filter((_, j) => j !== i))}
                  >
                    entfernen
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <button
        type="button"
        className="button button-ghost"
        onClick={() => onChange([...rows, empty()])}
      >
        Eintrag hinzufügen
      </button>
    </div>
  )
}
