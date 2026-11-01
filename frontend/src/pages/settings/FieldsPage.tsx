import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { FIELD_TYPES, fieldApi } from '../../api/fields.ts'
import type { FieldDefinition, FieldType, FieldUsage, Subfield } from '../../api/fields.ts'
import { PERM } from '../../api/orgs.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { ListInput } from '../../components/ListField.tsx'
import { parseTextList } from '../../components/lists.ts'
import { Alert, Checkbox, Field, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'
import { t } from '../../i18n/index.ts'

const typeLabel = (tmx: FieldType) => FIELD_TYPES.find((x) => x.value === tmx)?.label ?? tmx

export function FieldsPage() {
  const org = useActiveOrg()
  const editable = org.permissions.includes(PERM.orgEdit)
  const terms = useTerms()
  const { data, error, reload } = useLoad(() => fieldApi.list(org.id), [org.id])
  const [editing, setEditing] = useState<FieldDefinition | 'new' | null>(null)
  const [removing, setRemoving] = useState<{ field: FieldDefinition; usage: FieldUsage } | null>(
    null,
  )
  const [confirmValues, setConfirmValues] = useState(false)
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  const current = data.filter((f) => !f.is_archived)
  const archived = data.filter((f) => f.is_archived)

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true)
    setMessage(null)
    try {
      await action()
      setMessage({ kind: 'success', text: success })
      setRemoving(null)
      await reload()
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  async function askRemove(field: FieldDefinition) {
    setMessage(null)
    setEditing(null)
    setConfirmValues(false)
    try {
      setRemoving({ field, usage: await fieldApi.usage(org.id, field.id) })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  const persons = (n: number) => (n === 1 ? t('1 Person') : t('{n} Personen', { n }))

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>{t('Zusatzfelder')}</h2>
        {editable && editing === null && (
          <button
            type="button"
            className="button button-ghost push-right"
            onClick={() => setEditing('new')}
          >
            {t('Neues Feld')}
          </button>
        )}
      </div>
      <p className="muted small">
        {t(
          'Eigene Felder für die Mitgliedsakte. Wiederholbare Felder haben mehrere Einträge je Person, z. B. Auszeichnungen mit Bezeichnung, Datum und verleihender Organisation.',
        )}
        {org.type === 'federation' &&
          t(' Verbandsweite Felder gelten in allen {pl_dat}.', { pl_dat: terms.pl_dat })}
      </p>
      {editing !== null && (
        <FieldForm
          // Je Objekt ein eigenes Formular: Werte und Autospeichern wechseln nie das Ziel
          key={editing === 'new' ? 'new' : editing.id}
          orgId={org.id}
          isFederation={org.type === 'federation'}
          field={editing === 'new' ? null : editing}
          onDone={async () => {
            setEditing(null)
            await reload()
          }}
          onCancel={() => setEditing(null)}
        />
      )}
      {removing && (
        <div className="subcard" role="dialog" aria-label={t('Zusatzfeld entfernen')}>
          {removing.usage.deletable ? (
            <p>
              {t('„{label}“ ist bei niemandem ausgefüllt und wird', {
                label: removing.field.label,
              })}{' '}
              <strong>{t('gelöscht')}</strong>.
            </p>
          ) : (
            <>
              <p>
                {t('„{label}“ ist bei {x} ausgefüllt', {
                  label: removing.field.label,
                  x: persons(removing.usage.value_count),
                })}
                {removing.field.federation_wide && ` (in allen ${terms.pl_dat})`}.
              </p>
              <p className="muted small">
                <strong>{t('Archivieren')}</strong>
                {t(
                  ': Das Feld verschwindet aus Mitgliedsakte und Export, die Werte bleiben erhalten und das Feld lässt sich wiederherstellen.',
                )}{' '}
                <strong>{t('Samt Werten löschen')}</strong>
                {t(': Feld und alle Werte werden endgültig entfernt.')}
              </p>
              <Checkbox
                label={t('Ja, alle Werte bei {x} endgültig löschen', {
                  x: persons(removing.usage.value_count),
                })}
                checked={confirmValues}
                onChange={setConfirmValues}
              />
            </>
          )}
          <div className="button-row">
            {!removing.usage.deletable && !removing.usage.is_archived && (
              <button
                type="button"
                className="button button-primary"
                disabled={busy}
                onClick={() =>
                  void run(
                    () => fieldApi.archive(org.id, removing.field.id),
                    t('„{label}“ wurde archiviert.', { label: removing.field.label }),
                  )
                }
              >
                {t('Archivieren')}
              </button>
            )}
            <button
              type="button"
              className="button button-danger"
              disabled={busy || (!removing.usage.deletable && !confirmValues)}
              onClick={() =>
                void run(
                  () => fieldApi.remove(org.id, removing.field.id, !removing.usage.deletable),
                  t('„{label}“ wurde gelöscht.', { label: removing.field.label }),
                )
              }
            >
              {removing.usage.deletable ? t('Löschen') : t('Samt Werten löschen')}
            </button>
            <button type="button" className="button button-ghost" onClick={() => setRemoving(null)}>
              {t('Abbrechen')}
            </button>
          </div>
        </div>
      )}
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {current.length === 0 ? (
        <p className="muted">{t('Noch keine Zusatzfelder.')}</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>{t('Feld')}</th>
              <th>{t('Typ')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {current.map((f) => (
              <tr key={f.id}>
                <td>
                  <strong>{f.label}</strong>
                  {f.inherited && (
                    <div className="small muted" title={f.owner_name}>
                      {terms.dv_vom}
                    </div>
                  )}
                  {f.federation_wide && !f.inherited && (
                    <div className="small muted">verbandsweit</div>
                  )}
                </td>
                <td className="small">
                  {f.repeatable
                    ? t('wiederholbar: {x}', { x: f.subfields.map((s) => s.label).join(', ') })
                    : typeLabel(f.field_type)}
                  {f.field_type === 'choice' && !f.repeatable && ` (${f.choices.join(', ')})`}
                </td>
                <td className="actions">
                  {editable && !f.inherited && (
                    <>
                      <button type="button" className="link-button" onClick={() => setEditing(f)}>
                        {t('Bearbeiten')}
                      </button>{' '}
                      <button
                        type="button"
                        className="link-button"
                        aria-label={t('{label} löschen', { label: f.label })}
                        onClick={() => void askRemove(f)}
                      >
                        {t('Löschen')}
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {archived.length > 0 && (
        <>
          <h3>{t('Archivierte Zusatzfelder')}</h3>
          <p className="muted small">
            {t('Nicht in Mitgliedsakte und Export sichtbar; die Werte bleiben gespeichert.')}
          </p>
          <ul className="role-list">
            {archived.map((f) => (
              <li key={f.id} className="role-row">
                <strong>{f.label}</strong>
                {f.inherited && <span className="small muted"> {terms.dv_vom}</span>}
                {editable && !f.inherited && (
                  <span className="push-right">
                    <button
                      type="button"
                      className="button button-ghost"
                      disabled={busy}
                      onClick={() =>
                        void run(
                          () => fieldApi.restore(org.id, f.id),
                          t('„{label}“ ist wieder verfügbar.', { label: f.label }),
                        )
                      }
                    >
                      {t('Wiederherstellen')}
                    </button>{' '}
                    <button
                      type="button"
                      className="button button-ghost"
                      aria-label={t('{label} löschen', { label: f.label })}
                      onClick={() => void askRemove(f)}
                    >
                      {t('Löschen')}
                    </button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function FieldForm({
  orgId,
  isFederation,
  field,
  onDone,
  onCancel,
}: {
  orgId: number
  isFederation: boolean
  field: FieldDefinition | null
  onDone: () => void
  onCancel: () => void
}) {
  const tm = useTerms()
  const form = useForm({
    label: field?.label ?? '',
    field_type: field?.field_type ?? ('text' as FieldType),
    choices: (field?.choices ?? []).join('\n'),
    repeatable: field?.repeatable ?? false,
    subfields: field?.subfields ?? ([{ label: '', type: 'text' }] as Subfield[]),
    federation_wide: field?.federation_wide ?? false,
    help_text: field?.help_text ?? '',
  })
  const v = form.values
  const lines = (text: string) =>
    text
      .split('\n')
      .map((x) => x.trim())
      .filter(Boolean)

  function setSub(index: number, patch: Partial<Subfield>) {
    form.set(
      'subfields',
      v.subfields.map((s, i) => (i === index ? { ...s, ...patch } : s)),
    )
  }

  function payloadOf(x: typeof v) {
    return {
      label: x.label,
      field_type: x.field_type,
      choices: lines(x.choices),
      repeatable: x.repeatable,
      subfields: x.repeatable ? x.subfields.filter((s) => s.label.trim()) : [],
      federation_wide: x.federation_wide,
      help_text: x.help_text,
    }
  }

  // Ausdrücklich bestätigt: entfernte Unterfelder samt ihren Werten löschen
  const dropValues = useRef(false)
  // Bestehende Felder speichern automatisch, neue erst mit „Anlegen“
  const auto = useAutoSave(
    form,
    async (_changes, values) => {
      const saved = await fieldApi.update(orgId, field!.id, payloadOf(values), dropValues.current)
      dropValues.current = false
      return saved
    },
    { enabled: field !== null },
  )

  async function removeSub(index: number) {
    const sub = v.subfields[index]
    // Benutzte Unterfelder nur nach Rückfrage (die Werte gehen verloren)
    if (field?.in_use && sub.key && field.subfields.some((s) => s.key === sub.key)) {
      const ok = await confirmDialog({
        title: t('Unterfeld „{label}“ entfernen?', { label: sub.label }),
        message:
          t('Das Feld ist bei Personen ausgefüllt. Die Werte dieses Unterfelds werden dabei ') +
          t('bei allen Personen gelöscht.'),
        confirmLabel: t('Samt Werten entfernen'),
        danger: true,
      })
      if (!ok) return
      dropValues.current = true
    }
    form.set(
      'subfields',
      v.subfields.filter((_, j) => j !== index),
    )
  }

  async function save(e: FormEvent) {
    e.preventDefault()
    if (field) {
      if (!(await auto.flush())) return
      onDone()
      return
    }
    const ok = await form.submit(() => fieldApi.create(orgId, payloadOf(v)))
    if (ok) onDone()
  }

  return (
    <form className="subcard" onSubmit={save}>
      {field && <SaveStatus auto={auto} />}
      <div className="grid-2">
        <Field
          label={t('Bezeichnung')}
          required
          value={v.label}
          error={form.errors.label}
          onChange={(e) => form.set('label', e.target.value)}
        />
        <Field
          label={t('Hinweis (optional)')}
          value={v.help_text}
          onChange={(e) => form.set('help_text', e.target.value)}
        />
      </div>
      <Checkbox
        label={t('wiederholbar (mehrere Einträge mit Unterfeldern)')}
        checked={v.repeatable}
        onChange={(x) => form.set('repeatable', x)}
      />
      {!v.repeatable ? (
        <>
          <SelectField
            label={t('Typ')}
            value={v.field_type}
            onChange={(e) => form.set('field_type', e.target.value as FieldType)}
          >
            {FIELD_TYPES.map((tmx) => (
              <option key={tmx.value} value={tmx.value}>
                {tmx.label}
              </option>
            ))}
          </SelectField>
          {v.field_type === 'choice' && (
            <label className="field">
              <span>{t('Auswahlwerte (ein Wert pro Zeile)')}</span>
              <textarea
                rows={4}
                value={v.choices}
                onChange={(e) => form.set('choices', e.target.value)}
              />
              {form.errors.choices && <small className="field-error">{form.errors.choices}</small>}
            </label>
          )}
        </>
      ) : (
        <fieldset className="field">
          <span>{t('Unterfelder')}</span>
          {v.subfields.map((s, i) => (
            <div key={i} className="subfield-row">
              <input
                aria-label={t('Unterfeld {x}', { x: i + 1 })}
                placeholder={t('Bezeichnung')}
                value={s.label}
                onChange={(e) => setSub(i, { label: e.target.value })}
              />
              <select
                aria-label={t('Typ von Unterfeld {x}', { x: i + 1 })}
                value={s.type}
                onChange={(e) => setSub(i, { type: e.target.value as FieldType })}
              >
                {FIELD_TYPES.map((tmx) => (
                  <option key={tmx.value} value={tmx.value}>
                    {tmx.label}
                  </option>
                ))}
              </select>
              {s.type === 'choice' && (
                <ListInput
                  aria-label={t('Auswahlwerte von Unterfeld {x}', { x: i + 1 })}
                  placeholder={t('Werte, durch Komma getrennt')}
                  value={s.choices ?? []}
                  parse={parseTextList}
                  onChange={(choices) => setSub(i, { choices })}
                />
              )}
              <button type="button" className="link-button" onClick={() => void removeSub(i)}>
                entfernen
              </button>
            </div>
          ))}
          <button
            type="button"
            className="button button-ghost"
            onClick={() => form.set('subfields', [...v.subfields, { label: '', type: 'text' }])}
          >
            {t('Unterfeld hinzufügen')}
          </button>
          {form.errors.subfields && <small className="field-error">{form.errors.subfields}</small>}
        </fieldset>
      )}
      {isFederation && (
        <Checkbox
          label={t('verbandsweit (gilt in allen {pl_dat})', { pl_dat: tm.pl_dat })}
          checked={v.federation_wide}
          onChange={(x) => form.set('federation_wide', x)}
        />
      )}
      {form.message?.kind === 'error' && <Alert kind="error">{form.message.text}</Alert>}
      <div className="button-row">
        <button
          type="submit"
          className={field ? 'button button-ghost' : 'button button-primary'}
          disabled={form.busy}
        >
          {field ? t('Schließen') : t('Anlegen')}
        </button>
        {!field && (
          <button type="button" className="button button-ghost" onClick={onCancel}>
            {t('Abbrechen')}
          </button>
        )}
      </div>
    </form>
  )
}
