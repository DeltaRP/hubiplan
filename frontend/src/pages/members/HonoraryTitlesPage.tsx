// Mitglieder › Einrichtung › Ehrungen: Bezeichnungen der Organisation (Verein
// oder Dachverband) mit optionaler Beitragsanpassung. Verliehen wird in der
// Mitgliederakte.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { memberApi } from '../../api/members.ts'
import type { HonoraryFeeMode, HonoraryTitle } from '../../api/members.ts'
import { PERM } from '../../api/orgs.ts'
import { DataTable } from '../../components/DataTable.tsx'
import type { Column } from '../../components/DataTable.tsx'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { DeleteIcon, EditIcon, IconButton, RestoreIcon } from '../../components/icons.tsx'
import { Alert, Checkbox, Field, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'
import { ownMembers } from './access.ts'
import { SortableList, SortHint } from '../../components/Sortable.tsx'

const FEE_MODES: { value: HonoraryFeeMode; label: string }[] = [
  { value: 'none', label: 'keine Beitragsänderung' },
  { value: 'free', label: 'beitragsfrei' },
  { value: 'amount', label: 'fester Jahresbeitrag' },
  { value: 'discount', label: 'Abschlag in Prozent' },
]

export function HonoraryTitlesPage() {
  const tm = useTerms()
  const org = useActiveOrg()
  const editable = org.permissions.includes(PERM.orgEdit)
  const { data, error, reload } = useLoad(() => memberApi.honoraryTitles(org.id), [org.id])
  const [editing, setEditing] = useState<HonoraryTitle | 'new' | null>(null)
  const [sorting, setSorting] = useState(false)
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const federation = org.type === 'federation'

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>

  async function run(action: () => Promise<unknown>, success: string) {
    setMessage(null)
    try {
      await action()
      setMessage({ kind: 'success', text: success })
      await reload()
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  async function remove(title: HonoraryTitle) {
    setEditing(null)
    setMessage(null)
    let usage
    try {
      usage = await memberApi.honoraryTitleUsage(org.id, title.id)
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
      return
    }
    if (usage.deletable) {
      const ok = await confirmDialog({
        title: `„${title.name}“ löschen?`,
        message: 'Die Ehrung wurde noch nie verliehen.',
        confirmLabel: 'Löschen',
      })
      if (ok) {
        await run(
          () => memberApi.deleteHonoraryTitle(org.id, title.id),
          `„${title.name}“ wurde gelöscht.`,
        )
      }
      return
    }
    const ok = await confirmDialog({
      title: `„${title.name}“ archivieren?`,
      message: `Die Ehrung ist verliehen (${usage.reasons.join(', ')}) und wird deshalb archiviert statt gelöscht. Bestehende Verleihungen bleiben, neue sind nicht mehr möglich.`,
      confirmLabel: 'Archivieren',
    })
    if (ok) {
      await run(
        () => memberApi.archiveHonoraryTitle(org.id, title.id),
        `„${title.name}“ wurde archiviert.`,
      )
    }
  }

  const columns: Column<HonoraryTitle>[] = [
    { key: 'name', label: 'Ehrung', value: (tmx) => tmx.name },
    {
      key: 'fee',
      label: federation ? 'Verbandsbeitrag' : 'Beitrag',
      value: (tmx) => tmx.fee_text || 'unverändert',
      filter: true,
    },
    {
      key: 'status',
      label: 'Status',
      value: (tmx) => (tmx.is_archived ? 'archiviert' : 'aktiv'),
      filter: { initial: 'aktiv' },
    },
  ]

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>Ehrungen</h2>
        {editable && editing === null && (
          <div className="button-row push-right">
            {data.filter((tmx) => !tmx.is_archived).length > 1 && (
              <button
                type="button"
                className="button button-ghost"
                aria-pressed={sorting}
                onClick={() => setSorting((x) => !x)}
              >
                {sorting ? 'Schließen' : 'Reihenfolge ändern'}
              </button>
            )}
            {!sorting && (
              <button
                type="button"
                className="button button-ghost"
                onClick={() => setEditing('new')}
              >
                Neue Ehrung
              </button>
            )}
          </div>
        )}
      </div>
      <p className="muted small">
        Ehrungen wie Ehrenmitglied oder Ehrenmajor vergebt ihr in der Mitgliederakte, mit Beginn und
        optional Ende. Eine Ehrung kann den{' '}
        {federation ? `Verbandsbeitrag, den ${tm.nom} für das Mitglied zahlt` : 'Mitgliedsbeitrag'}{' '}
        ändern. Hat ein Mitglied mehrere solcher Ehrungen, gilt die günstigste.
        {(!federation || ownMembers(org)) &&
          ' Würden, die jedes Jahr wechseln (König, Prinz), pflegt ihr dagegen unter Mitglieder › Würdenträger.'}
        {federation &&
          ` Die ${tm.pl} sehen die Ehrungen, die ihr ihren Mitgliedern verliehen habt.`}
      </p>
      {editing !== null && (
        <TitleForm
          // Je Objekt ein eigenes Formular: Werte und Autospeichern wechseln nie das Ziel
          key={editing === 'new' ? 'new' : editing.id}
          orgId={org.id}
          title={editing === 'new' ? null : editing}
          onDone={async () => {
            setEditing(null)
            await reload()
          }}
          onCancel={() => setEditing(null)}
        />
      )}
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {sorting ? (
        <>
          <SortHint website={org.modules.includes('website')} />
          <SortableList
            ariaLabel="Reihenfolge der Ehrungen"
            items={data.filter((tmx) => !tmx.is_archived)}
            id={(tmx) => tmx.id}
            label={(tmx) => tmx.name}
            onReorder={(ids) =>
              memberApi
                .reorderHonoraryTitles(org.id, [
                  ...ids,
                  ...data.filter((tmx) => tmx.is_archived).map((tmx) => tmx.id),
                ])
                .then(() => reload())
            }
          />
        </>
      ) : (
        <DataTable
          label="Ehrungen"
          rows={data}
          rowKey={(tmx) => tmx.id}
          columns={columns}
          emptyText="Noch keine Ehrungen angelegt."
          rowClassName={(tmx) => (tmx.is_archived ? 'inactive' : undefined)}
          actions={
            editable
              ? (tmx) =>
                  tmx.is_archived ? (
                    <IconButton
                      label={`${tmx.name} wiederherstellen`}
                      icon={<RestoreIcon />}
                      onClick={() =>
                        void run(
                          () => memberApi.restoreHonoraryTitle(org.id, tmx.id),
                          `„${tmx.name}“ ist wieder verfügbar.`,
                        )
                      }
                    />
                  ) : (
                    <>
                      <IconButton
                        label={`${tmx.name} bearbeiten`}
                        icon={<EditIcon />}
                        onClick={() => setEditing(tmx)}
                      />
                      <IconButton
                        label={`${tmx.name} löschen`}
                        icon={<DeleteIcon />}
                        danger
                        onClick={() => void remove(tmx)}
                      />
                    </>
                  )
              : undefined
          }
        />
      )}
    </div>
  )
}

function TitleForm({
  orgId,
  title,
  onDone,
  onCancel,
}: {
  orgId: number
  title: HonoraryTitle | null
  onDone: () => void
  onCancel: () => void
}) {
  const form = useForm({
    name: title?.name ?? '',
    fee_mode: title?.fee_mode ?? ('none' as HonoraryFeeMode),
    fee_amount: title?.fee_amount ?? '',
    fee_discount_percent: title?.fee_discount_percent ?? '',
    is_public: title?.is_public ?? false,
    name_plural: title?.name_plural ?? '',
    year_only: title?.year_only ?? false,
  })
  const v = form.values
  const hasWebsite = useActiveOrg().modules.includes('website')

  function payload(changes: Partial<typeof v>) {
    const out: Record<string, unknown> = { ...changes }
    if ('fee_amount' in out) out.fee_amount = out.fee_amount === '' ? null : out.fee_amount
    if ('fee_discount_percent' in out) {
      out.fee_discount_percent = out.fee_discount_percent === '' ? null : out.fee_discount_percent
    }
    return out as Partial<HonoraryTitle>
  }

  // Bestehende Ehrungen speichern automatisch, neue erst mit „Anlegen“
  const auto = useAutoSave(
    form,
    (changes) => memberApi.updateHonoraryTitle(orgId, title!.id, payload(changes)),
    { enabled: title !== null },
  )

  async function save(e: FormEvent) {
    e.preventDefault()
    if (title) {
      if (!(await auto.flush())) return
      onDone()
      return
    }
    const ok = await form.submit(() => memberApi.createHonoraryTitle(orgId, payload(v)))
    if (ok) onDone()
  }

  return (
    <form className="subcard" onSubmit={save} aria-label="Ehrung bearbeiten">
      {title && <SaveStatus auto={auto} />}
      <div className="grid-2">
        <Field
          label="Bezeichnung"
          required
          value={v.name}
          error={form.errors.name}
          onChange={(e) => form.set('name', e.target.value)}
        />
        <SelectField
          label="Beitrag"
          value={v.fee_mode}
          error={form.errors.fee_mode}
          onChange={(e) => form.set('fee_mode', e.target.value as HonoraryFeeMode)}
        >
          {FEE_MODES.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </SelectField>
        {v.fee_mode === 'amount' && (
          <Field
            label="Jahresbeitrag in €"
            type="number"
            step="0.01"
            min="0"
            required
            value={v.fee_amount}
            error={form.errors.fee_amount}
            onChange={(e) => form.set('fee_amount', e.target.value)}
          />
        )}
        {v.fee_mode === 'discount' && (
          <Field
            label="Abschlag in %"
            type="number"
            step="0.01"
            min="0.01"
            max="100"
            required
            value={v.fee_discount_percent}
            error={form.errors.fee_discount_percent}
            onChange={(e) => form.set('fee_discount_percent', e.target.value)}
          />
        )}
      </div>
      <Checkbox
        label="nur Jahr der Verleihung (statt Zeitraum von–bis)"
        checked={v.year_only}
        onChange={(on) => form.set('year_only', on)}
      />
      {hasWebsite && (
        <>
          <Checkbox
            label="auf der Webseite zeigen (z. B. Ehrenmitglieder; nicht bei Widerspruch)"
            checked={v.is_public}
            onChange={(on) => form.set('is_public', on)}
          />
          {v.is_public && (
            <Field
              label="Mehrzahl (Überschrift auf der Webseite bei mehreren Trägern)"
              value={v.name_plural}
              placeholder={title?.plural || undefined}
              error={form.errors.name_plural}
              onChange={(e) => form.set('name_plural', e.target.value)}
            />
          )}
        </>
      )}
      {form.message?.kind === 'error' && <Alert kind="error">{form.message.text}</Alert>}
      <div className="button-row">
        <button
          type="submit"
          className={title ? 'button button-ghost' : 'button button-primary'}
          disabled={form.busy}
        >
          {title ? 'Schließen' : 'Anlegen'}
        </button>
        {!title && (
          <button type="button" className="button button-ghost" onClick={onCancel}>
            Abbrechen
          </button>
        )}
      </div>
    </form>
  )
}
