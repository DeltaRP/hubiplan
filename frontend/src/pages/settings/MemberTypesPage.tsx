import { useState } from 'react'
import type { FormEvent } from 'react'
import { memberApi } from '../../api/members.ts'
import type { MemberType, TypeUsage } from '../../api/members.ts'
import { PERM } from '../../api/orgs.ts'
import { errorMessage, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { Alert, Checkbox, Field, SaveStatus } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { fillTerms, useTerms } from '../../org/terms.ts'
import { Term, Why } from '../../learning/Aids.tsx'
import { SortHint } from '../../components/Sortable.tsx'
import { useSortable } from '../../components/useSortable.tsx'

export function MemberTypesPage() {
  const org = useActiveOrg()
  const editable = org.permissions.includes(PERM.orgEdit)
  const terms = useTerms()
  const fed = !!terms.dv_has
  const { data, error, reload } = useLoad(() => memberApi.types(org.id), [org.id])
  const [editing, setEditing] = useState<MemberType | 'new' | null>(null)
  const [removing, setRemoving] = useState<{ type: MemberType; usage: TypeUsage } | null>(null)
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const current = (data ?? []).filter((t) => !t.is_archived)
  const archived = (data ?? []).filter((t) => t.is_archived)
  const sort = useSortable({
    items: current,
    id: (t) => t.id,
    label: (t) => t.name,
    onReorder: (ids) =>
      memberApi.reorderTypes(org.id, [...ids, ...archived.map((t) => t.id)]).then(() => reload()),
    enabled: editable,
  })

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>

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

  async function askRemove(type: MemberType) {
    setMessage(null)
    setEditing(null)
    try {
      setRemoving({ type, usage: await memberApi.typeUsage(org.id, type.id) })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  function confirmRemove() {
    if (!removing) return
    const { type, usage } = removing
    if (usage.deletable) {
      void run(() => memberApi.deleteType(org.id, type.id), `„${type.name}“ wurde gelöscht.`)
    } else {
      void run(() => memberApi.archiveType(org.id, type.id), `„${type.name}“ wurde archiviert.`)
    }
  }

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>
          <Term k="member_type">Mitgliedsarten</Term>
        </h2>
        {editable && editing === null && (
          <button
            type="button"
            className="button button-ghost push-right"
            onClick={() => setEditing('new')}
          >
            Neue Mitgliedsart
          </button>
        )}
      </div>
      {fed ? (
        <p className="muted small">
          Jede Art hat drei Kennzeichen: <strong>{fillTerms('an {dv_akk} melden', terms)}</strong>{' '}
          (zählt für {terms.dv_akk}), <strong>aktiv</strong> ({terms.dv_im} nur in {terms.e_einem}{' '}
          erlaubt) und <strong>zählt für Mitgliedsdauer</strong>.
        </p>
      ) : (
        <p className="muted small">
          Jede Art hat zwei Kennzeichen: <strong>aktiv</strong> und{' '}
          <strong>zählt für Mitgliedsdauer</strong>.
        </p>
      )}
      {editing !== null && (
        <TypeForm
          // Je Objekt ein eigenes Formular: Werte und Autospeichern wechseln nie das Ziel
          key={editing === 'new' ? 'new' : editing.id}
          orgId={org.id}
          type={editing === 'new' ? null : editing}
          onDone={async () => {
            setEditing(null)
            await reload()
          }}
          onCancel={() => setEditing(null)}
        />
      )}
      {removing && (
        <div className="subcard" role="dialog" aria-label="Mitgliedsart entfernen">
          {removing.usage.deletable ? (
            <p>
              „{removing.type.name}“ wird nirgends verwendet und wird <strong>gelöscht</strong>.
            </p>
          ) : (
            <>
              <p>
                „{removing.type.name}“ wird noch verwendet und wird deshalb{' '}
                <strong>archiviert</strong> statt gelöscht:
              </p>
              <ul>
                {removing.usage.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
              <p className="muted small">
                Archivierte Arten stehen nicht mehr zur Auswahl für neue Einträge. In Historie,
                Mitgliederakte, Filtern und Exporten bleiben sie sichtbar und lassen sich jederzeit
                wiederherstellen.
              </p>
            </>
          )}
          <div className="button-row">
            <button
              type="button"
              className="button button-danger"
              disabled={busy}
              onClick={confirmRemove}
            >
              {removing.usage.deletable ? 'Löschen' : 'Archivieren'}
            </button>
            <button type="button" className="button button-ghost" onClick={() => setRemoving(null)}>
              Abbrechen
            </button>
          </div>
        </div>
      )}
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {sort.active && <SortHint />}
      <table className="table">
        <thead>
          <tr>
            {sort.active && (
              <th className="drag-cell">
                <span className="sr-only">Reihenfolge</span>
              </th>
            )}
            <th>Art</th>
            {fed && <th>melden</th>}
            <th>
              <Term k="active_passive">aktiv</Term>
            </th>
            <th>
              <Term k="membership_duration">zählt für Dauer</Term>
            </th>
            <th />
          </tr>
        </thead>
        <tbody>
          {sort.ordered.map((t) => (
            <tr key={t.id} {...sort.rowProps(t)}>
              {sort.active && <td className="drag-cell">{sort.handle(t)}</td>}
              <td>{t.name}</td>
              {fed && <td>{t.reported ? 'ja' : 'nein'}</td>}
              <td>{t.active ? 'ja' : 'nein'}</td>
              <td>{t.counts_for_duration ? 'ja' : 'nein'}</td>
              <td className="actions">
                {editable && (
                  <>
                    <button type="button" className="link-button" onClick={() => setEditing(t)}>
                      Bearbeiten
                    </button>{' '}
                    <button
                      type="button"
                      className="link-button"
                      aria-label={`${t.name} löschen`}
                      onClick={() => void askRemove(t)}
                    >
                      Löschen
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {sort.status}

      {archived.length > 0 && (
        <>
          <h3>Archivierte Mitgliedsarten</h3>
          <p className="muted small">
            Nicht mehr für neue Einträge wählbar, in Historie und Auswertungen weiter sichtbar.
          </p>
          <ul className="role-list">
            {archived.map((t) => (
              <li key={t.id} className="role-row">
                <strong>{t.name}</strong>
                {editable && (
                  <button
                    type="button"
                    className="button button-ghost push-right"
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () => memberApi.restoreType(org.id, t.id),
                        `„${t.name}“ ist wieder verfügbar.`,
                      )
                    }
                  >
                    Wiederherstellen
                  </button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function TypeForm({
  orgId,
  type,
  onDone,
  onCancel,
}: {
  orgId: number
  type: MemberType | null
  onDone: () => void
  onCancel: () => void
}) {
  const terms = useTerms()
  const form = useForm({
    name: type?.name ?? '',
    reported: type?.reported ?? true,
    active: type?.active ?? false,
    counts_for_duration: type?.counts_for_duration ?? true,
    is_archived: type?.is_archived ?? false,
  })
  const v = form.values

  // Bestehende Arten speichern automatisch, neue erst mit „Anlegen“
  const auto = useAutoSave(form, (changes) => memberApi.updateType(orgId, type!.id, changes), {
    enabled: type !== null,
  })

  async function save(e: FormEvent) {
    e.preventDefault()
    if (type) {
      if (!(await auto.flush())) return
      onDone()
      return
    }
    const ok = await form.submit(() => memberApi.createType(orgId, v))
    if (ok) onDone()
  }

  return (
    <form className="subcard" onSubmit={save}>
      {type && <SaveStatus auto={auto} />}
      <div className="grid-2">
        <Field
          label="Name"
          required
          value={v.name}
          error={form.errors.name}
          onChange={(e) => form.set('name', e.target.value)}
        />
      </div>
      {terms.dv_has && (
        <Checkbox
          label={fillTerms('an {dv_akk} melden', terms)}
          checked={v.reported}
          onChange={(x) => form.set('reported', x)}
        />
      )}
      {terms.dv_has && <Why k="member_type_reported" />}
      <Checkbox label="aktiv" checked={v.active} onChange={(x) => form.set('active', x)} />
      <Why k="member_type_active" />
      <Checkbox
        label="zählt für Mitgliedsdauer"
        checked={v.counts_for_duration}
        onChange={(x) => form.set('counts_for_duration', x)}
      />
      <Why k="member_type_duration" />
      {form.message?.kind === 'error' && <Alert kind="error">{form.message.text}</Alert>}
      <div className="button-row">
        <button
          type="submit"
          className={type ? 'button button-ghost' : 'button button-primary'}
          disabled={form.busy}
        >
          {type ? 'Schließen' : 'Anlegen'}
        </button>
        {!type && (
          <button type="button" className="button button-ghost" onClick={onCancel}>
            Abbrechen
          </button>
        )}
      </div>
    </form>
  )
}
