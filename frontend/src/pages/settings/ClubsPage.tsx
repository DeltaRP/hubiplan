// Hauptmenü › Untereinheiten einer Einheit ohne eigene Mitglieder: Einheiten darunter mit
// ihrem Baum (nur Namen), Stammdaten pflegen, deaktivieren, neu anlegen oder importieren.
import { useEffect, useRef, useState } from 'react'
import { orgApi } from '../../api/orgs.ts'
import type { FederationClub } from '../../api/orgs.ts'
import { ClubCreateForm, ImportSection } from '../../components/DataTransfer.tsx'
import { DataTable } from '../../components/DataTable.tsx'
import type { Column } from '../../components/DataTable.tsx'
import { alertDialog, confirmDialog } from '../../components/dialog.ts'
import { errorMessage, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { DeleteIcon, EditIcon, IconButton, RestoreIcon } from '../../components/icons.tsx'
import { Alert, Checkbox, Field, SaveStatus } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'

export function ClubsPage() {
  const tm = useTerms()
  const org = useActiveOrg()
  const { data, error, reload } = useLoad(() => orgApi.clubs(org.id), [org.id])
  const [selected, setSelected] = useState<number | null>(null)
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (selected !== null) panel.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
  }, [selected])

  async function setActive(club: FederationClub, active: boolean) {
    if (!active) {
      const ok = await confirmDialog({
        title: `„${club.name}“ löschen?`,
        message:
          `${tm.Nom} wird deaktiviert: Danach kann sich dort niemand mehr anmelden, der ` +
          'Eintrag erscheint nur noch unter „nur inaktive“. Mitglieder und alle Daten bleiben ' +
          'erhalten, du kannst das jederzeit wieder rückgängig machen.',
        confirmLabel: 'Löschen',
      })
      if (!ok) return
    }
    try {
      await orgApi.updateClub(org.id, club.id, { is_active: active })
      reload()
    } catch (err) {
      await alertDialog({ title: 'Nicht gespeichert', message: errorMessage(err) })
    }
  }

  const columns: Column<FederationClub>[] = [
    {
      key: 'name',
      label: 'Name',
      value: (c) => c.name,
      searchText: (c) => `${c.name} ${c.short_name}`,
      render: (c) => (
        <span className="cell-with-logo">
          {c.logo_url && <img src={c.logo_url} alt="" className="cell-logo" />}
          {c.name}
        </span>
      ),
    },
    { key: 'short_name', label: 'Kurzname', value: (c) => c.short_name, optional: true },
    {
      key: 'units',
      label: 'Untereinheiten',
      value: (c) => c.units?.length ?? 0,
      searchText: (c) => (c.units ?? []).map((u) => u.name).join(' '),
      render: (c) =>
        c.units && c.units.length > 0 ? (
          <details>
            <summary>
              {c.units.length} {c.department_label_plural ?? ''}
            </summary>
            <ul className="plain-list small">
              {c.units.map((u) => (
                <li key={u.id}>{u.name}</li>
              ))}
            </ul>
          </details>
        ) : (
          '–'
        ),
      optional: true,
    },
    {
      key: 'founding_year',
      label: 'Gründungsjahr',
      value: (c) => c.founding_year,
      numeric: true,
      optional: true,
    },
    {
      key: 'city',
      label: 'Ort',
      value: (c) => c.city,
      searchText: (c) => `${c.street} ${c.postal_code} ${c.city}`,
      render: (c) => [c.postal_code, c.city].filter(Boolean).join(' '),
      filter: { allLabel: 'alle Orte' },
    },
    {
      key: 'contact_email',
      label: 'E-Mail',
      value: (c) => c.contact_email,
      render: (c) =>
        c.contact_email ? <a href={`mailto:${c.contact_email}`}>{c.contact_email}</a> : '',
      optional: true,
    },
    {
      key: 'status',
      label: 'Status',
      value: (c) => (c.is_active ? 'aktiv' : 'inaktiv'),
      filter: {
        allLabel: 'aktive und inaktive',
        initial: 'aktiv',
        options: [
          { value: 'aktiv', label: 'nur aktive' },
          { value: 'inaktiv', label: 'nur inaktive' },
        ],
      },
    },
  ]

  const current = data?.find((c) => c.id === selected) ?? null

  return (
    <div className="stack">
      <div className="card card-wide">
        <h2>{tm.Pl}</h2>
        {error && <Alert kind="error">{error}</Alert>}
        {!data ? (
          !error && <p className="muted">Lädt …</p>
        ) : (
          <DataTable
            label={tm.Pl}
            rows={data}
            columns={columns}
            rowKey={(c) => c.id}
            initialSort={{ key: 'name' }}
            searchPlaceholder={`${tm.Pl} durchsuchen: Name, Ort, E-Mail`}
            emptyText={`Noch keine ${tm.pl}.`}
            countText={(n, total) =>
              n === total ? `${total} ${total === 1 ? tm.sg : tm.pl}` : `${n} von ${total}`
            }
            rowClassName={(c) =>
              [!c.is_active && 'inactive', c.id === selected && 'selected']
                .filter(Boolean)
                .join(' ') || undefined
            }
            actions={(c) => (
              <>
                <IconButton
                  label={`${c.name} bearbeiten`}
                  icon={<EditIcon />}
                  aria-pressed={c.id === selected}
                  onClick={() => setSelected((s) => (s === c.id ? null : c.id))}
                />
                {c.is_active ? (
                  <IconButton
                    label={`${c.name} löschen`}
                    icon={<DeleteIcon />}
                    danger
                    onClick={() => void setActive(c, false)}
                  />
                ) : (
                  <IconButton
                    label={`${c.name} wieder aktivieren`}
                    icon={<RestoreIcon />}
                    onClick={() => void setActive(c, true)}
                  />
                )}
              </>
            )}
          />
        )}
      </div>
      {current && (
        <div ref={panel}>
          <ClubEditCard
            key={current.id}
            orgId={org.id}
            club={current}
            onSaved={reload}
            onClose={() => setSelected(null)}
          />
        </div>
      )}
      <ClubCreateForm federationId={org.id} onDone={reload} />
      <ImportSection base={{ org: org.id }} target="federation" onImported={reload} />
    </div>
  )
}

function ClubEditCard({
  orgId,
  club,
  onSaved,
  onClose,
}: {
  orgId: number
  club: FederationClub
  onSaved: () => void
  onClose: () => void
}) {
  const tm = useTerms()
  const form = useForm({
    name: club.name,
    short_name: club.short_name,
    founding_year: club.founding_year === null ? '' : String(club.founding_year),
    street: club.street,
    postal_code: club.postal_code,
    city: club.city,
    contact_email: club.contact_email,
    contact_phone: club.contact_phone,
    website: club.website,
    is_active: club.is_active,
  })
  const auto = useAutoSave(
    form,
    (changes) => {
      const payload: Record<string, unknown> = { ...changes }
      if ('founding_year' in changes) {
        payload.founding_year = changes.founding_year ? Number(changes.founding_year) : null
      }
      return orgApi.updateClub(orgId, club.id, payload as Partial<FederationClub>)
    },
    { onSaved: () => onSaved() },
  )
  const v = form.values

  async function finish() {
    if (!(await auto.flush())) return
    onClose()
  }

  return (
    <form className="card card-wide" onSubmit={(e) => e.preventDefault()}>
      <div className="card-head">
        <h2>{club.name} bearbeiten</h2>
      </div>
      <SaveStatus auto={auto} />
      <div className="grid-3">
        <Field
          label="Vollständiger Name"
          required
          value={v.name}
          error={form.errors.name}
          onChange={(e) => form.set('name', e.target.value)}
        />
        <Field
          label="Kurzname (optional)"
          maxLength={50}
          value={v.short_name}
          error={form.errors.short_name}
          onChange={(e) => form.set('short_name', e.target.value)}
        />
        <Field
          label="Gründungsjahr"
          type="number"
          min={800}
          max={2100}
          value={v.founding_year}
          error={form.errors.founding_year}
          onChange={(e) => form.set('founding_year', e.target.value)}
        />
        <Field
          label="Straße"
          value={v.street}
          error={form.errors.street}
          onChange={(e) => form.set('street', e.target.value)}
        />
        <Field
          label="PLZ"
          maxLength={10}
          value={v.postal_code}
          error={form.errors.postal_code}
          onChange={(e) => form.set('postal_code', e.target.value)}
        />
        <Field
          label="Ort"
          value={v.city}
          error={form.errors.city}
          onChange={(e) => form.set('city', e.target.value)}
        />
        <Field
          label="E-Mail"
          type="email"
          value={v.contact_email}
          error={form.errors.contact_email}
          onChange={(e) => form.set('contact_email', e.target.value)}
        />
        <Field
          label="Telefon"
          value={v.contact_phone}
          error={form.errors.contact_phone}
          onChange={(e) => form.set('contact_phone', e.target.value)}
        />
        <Field
          label="Website"
          type="url"
          value={v.website}
          error={form.errors.website}
          onChange={(e) => form.set('website', e.target.value)}
        />
      </div>
      <Checkbox
        label={v.name ? `${v.name} ist aktiv` : 'aktiv'}
        checked={v.is_active}
        onChange={(on) => form.set('is_active', on)}
      />
      <p className="muted small">
        Weitere Einstellungen (Rollen, Erscheinungsbild, Module) pflegt {tm.nom} selbst.
      </p>
      <div className="button-row">
        <button type="button" className="button button-ghost" onClick={() => void finish()}>
          Schließen
        </button>
      </div>
    </form>
  )
}
