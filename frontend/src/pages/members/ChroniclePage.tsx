// Mitglieder › Würdenträger: Würden (frei benannt, z. B. König, Prinz, Zugkönig),
// Regentschaften mit Begleitpersonen und Foto, Excel-Import der Königsliste.
import { useEffect, useRef, useState } from 'react'
import { Route, Routes } from 'react-router-dom'
import { newRequestKey } from '../../api/client.ts'
import { honorsApi } from '../../api/honors.ts'
import type {
  Companion,
  Dignity,
  HonorsPerson,
  ImportRow,
  Origin,
  Reign,
  ReignInput,
  SharedDignity,
} from '../../api/honors.ts'
import { orgApi, PERM } from '../../api/orgs.ts'
import { DataTable } from '../../components/DataTable.tsx'
import type { Column } from '../../components/DataTable.tsx'
import { confirmDialog } from '../../components/dialog.ts'
import { MemberPicker } from '../../components/MemberPicker.tsx'
import { errorMessage, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { DeleteIcon, EditIcon, IconButton } from '../../components/icons.tsx'
import { Alert, Checkbox, Field, LoadError, SaveStatus, SelectField } from '../../components/ui.tsx'
import { SortableList, SortHint } from '../../components/Sortable.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { HowTo } from '../../learning/Aids.tsx'
import { MembersSection } from '../MembersPage.tsx'
import { useImageCrop } from '../../components/ImageCrop.tsx'
import { RightsHint } from '../../components/RightsHint.tsx'

/** Aktuelles Jahr, beim Öffnen eines Formulars ermittelt (nicht beim Laden der Seite). */
function thisYear() {
  return new Date().getFullYear()
}

export function ChroniclePage() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.membersEdit)
  const tabs = [
    { to: '/mitglieder/wuerdentraeger', label: 'Regentschaften' },
    { to: '/mitglieder/wuerdentraeger/wuerden', label: 'Würden' },
    ...(canEdit ? [{ to: '/mitglieder/wuerdentraeger/import', label: 'Import' }] : []),
  ]
  return (
    <MembersSection title="Würdenträger" tabs={tabs}>
      <Routes>
        <Route index element={<ReignsPanel />} />
        <Route path="wuerden" element={<DignitiesPanel />} />
        {canEdit && <Route path="import" element={<ImportPanel />} />}
      </Routes>
    </MembersSection>
  )
}

// --- Regentschaften ---

function ReignsPanel() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.membersEdit)
  const dignities = useLoad(() => honorsApi.dignities(org.id), [org.id])
  const reigns = useLoad(() => honorsApi.reigns(org.id), [org.id])
  const origins = useLoad(() => honorsApi.origins(org.id), [org.id])
  const shared = useLoad(() => honorsApi.shared(org.id), [org.id])
  const [editing, setEditing] = useState<Reign | 'new' | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  if (dignities.error || reigns.error)
    return <Alert kind="error">{dignities.error ?? reigns.error}</Alert>
  if (!dignities.data || !reigns.data) return <p className="muted">Lädt …</p>
  const usable = dignities.data.filter((d) => !d.is_archived)

  async function remove(r: Reign) {
    const ok = await confirmDialog({
      title: 'Regentschaft löschen?',
      message: `${r.dignity_name} ${r.period_text}: ${r.display_name}`,
      confirmLabel: 'Löschen',
    })
    if (!ok) return
    try {
      await honorsApi.deleteReign(org.id, r.id)
      await reigns.reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  const columns: Column<Reign>[] = [
    {
      key: 'year',
      label: 'Jahr',
      value: (r) => r.year ?? Number((r.valid_from ?? '0').slice(0, 4)),
      render: (r) => r.period_text,
      numeric: true,
    },
    { key: 'dignity', label: 'Würde', value: (r) => r.dignity_name, filter: true },
    {
      key: 'name',
      label: 'Name',
      value: (r) => r.numbered_name,
      render: (r) => (
        <>
          {r.numbered_name}
          {r.person === null && <span className="muted small"> (kein Mitglied verknüpft)</span>}
        </>
      ),
    },
    {
      key: 'companions',
      label: 'Begleitung',
      value: (r) => r.companions.map((c) => `${c.label}: ${c.display_name}`).join(', '),
      optional: true,
    },
    { key: 'origin', label: 'Aus', value: (r) => r.origin_text, filter: true, optional: true },
    { key: 'note', label: 'Bemerkung', value: (r) => r.note, optional: true },
    { key: 'photo', label: 'Foto', value: (r) => (r.photo ? 'ja' : ''), optional: true },
  ]

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>Regentschaften</h2>
        {canEdit && editing === null && usable.length > 0 && (
          <button
            type="button"
            className="button button-ghost push-right"
            onClick={() => setEditing('new')}
          >
            Neue Regentschaft
          </button>
        )}
      </div>
      <p className="muted small">
        Wer in welchem Jahr welche Würde trug, mit Begleitpersonen. Personen aus der Zeit vor
        HUBIplan tragt ihr als Namen ein. Auf der Webseite erscheinen Namen, solange die Person
        nicht widersprochen hat; Fotos verknüpfter Mitglieder nur mit Einwilligung.
      </p>
      {usable.length === 0 && (
        <Alert kind="info">Legt zuerst unter „Würden“ an, welche Würden es gibt.</Alert>
      )}
      {editing !== null && (
        <ReignForm
          key={editing === 'new' ? 'new' : editing.id}
          reign={editing === 'new' ? null : editing}
          dignities={dignities.data.filter(
            (d) => !d.is_archived || (editing !== 'new' && d.id === editing.dignity),
          )}
          origins={origins.data ?? []}
          onDone={async () => {
            setEditing(null)
            await reigns.reload()
          }}
          onCancel={() => setEditing(null)}
        />
      )}
      {message && <Alert kind="error">{message}</Alert>}
      <DataTable
        label="Regentschaften"
        rows={reigns.data}
        rowKey={(r) => r.id}
        columns={columns}
        initialSort={{ key: 'year', dir: 'desc' }}
        emptyText="Noch keine Regentschaften erfasst."
        actions={
          canEdit
            ? (r) => (
                <>
                  <IconButton
                    label={`${r.display_name} ${r.period_text} bearbeiten`}
                    icon={<EditIcon />}
                    onClick={() => setEditing(r)}
                  />
                  <IconButton
                    label={`${r.display_name} ${r.period_text} löschen`}
                    icon={<DeleteIcon />}
                    danger
                    onClick={() => void remove(r)}
                  />
                </>
              )
            : undefined
        }
      />
      {(shared.data ?? []).map((d) => (
        <SharedCard key={d.id} dignity={d} />
      ))}
    </div>
  )
}

/** Würde der Einheit darüber mit den Trägern, die aus dieser Einheit kamen (nur lesen). */
function SharedCard({ dignity }: { dignity: SharedDignity }) {
  type Row = SharedDignity['reigns'][number]
  const columns: Column<Row>[] = [
    {
      key: 'year',
      label: 'Jahr',
      value: (r) => r.year,
      render: (r) => r.period_text,
      numeric: true,
    },
    { key: 'name', label: 'Name', value: (r) => r.numbered_name },
    {
      key: 'companions',
      label: 'Begleitung',
      value: (r) => r.companions.map((c) => `${c.label}: ${c.name}`).join(', '),
      optional: true,
    },
    { key: 'note', label: 'Bemerkung', value: (r) => r.note, optional: true },
  ]
  return (
    <section className="subcard">
      <h3>
        {dignity.name} ({dignity.owner})
      </h3>
      <p className="muted small">
        Diese Würde vergibt {dignity.owner}. Hier stehen die Träger, die aus eurer Einheit kamen;
        ändern kann sie nur {dignity.owner}.
      </p>
      <DataTable
        label={`${dignity.name} (${dignity.owner})`}
        rows={dignity.reigns}
        rowKey={(r) => r.id}
        columns={columns}
        initialSort={{ key: 'year', dir: 'desc' }}
        emptyText="Keine Träger aus eurer Einheit."
      />
    </section>
  )
}

/** Woher der Würdenträger kam: Auswahl einer Einheit darunter oder frei als Text. */
function OriginField({
  origins,
  origin,
  name,
  onChange,
}: {
  origins: Origin[]
  origin: number | null
  name: string
  onChange: (origin: number | null, name: string) => void
}) {
  const [free, setFree] = useState(origin === null && name !== '')
  const value = origin !== null ? String(origin) : free ? 'frei' : ''
  return (
    <div className="grid-2">
      <SelectField
        label="Aus (Herkunft des Würdenträgers)"
        value={value}
        hint="Einheiten darunter sehen bei weitergegebenen Würden nur ihre eigenen Träger."
        onChange={(e) => {
          const v = e.target.value
          setFree(v === 'frei')
          if (v === 'frei' || v === '') onChange(null, v === 'frei' ? name : '')
          else onChange(Number(v), '')
        }}
      >
        <option value="">keine Angabe</option>
        {origins.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
        <option value="frei">andere (frei eingeben)</option>
      </SelectField>
      {free && (
        <Field
          label="Aus (frei)"
          value={name}
          placeholder="z. B. ein aufgelöster Zug"
          onChange={(e) => onChange(null, e.target.value)}
        />
      )}
    </div>
  )
}

/** Mitglied (auch ehemaliges) oder Name als Text. */
export function PersonField({
  label,
  person,
  name,
  onChange,
}: {
  label: string
  person: number | null
  name: string
  onChange: (person: number | null, name: string) => void
}) {
  const org = useActiveOrg()
  if (person !== null) {
    return (
      <div className="field">
        <span>{label}</span>
        <p>
          {name}{' '}
          <button type="button" className="link-button" onClick={() => onChange(null, name)}>
            Verknüpfung lösen
          </button>
        </p>
      </div>
    )
  }
  return (
    <div className="grid-2">
      <Field
        label={`${label} (Name)`}
        value={name}
        hint="Für frühere Jahre und Nichtmitglieder."
        onChange={(e) => onChange(null, e.target.value)}
      />
      <MemberPicker<HonorsPerson>
        orgId={org.id}
        value={null}
        label="oder Mitglied wählen"
        search={(term) => honorsApi.people(org.id, term)}
        onChange={(m) => m && onChange(m.id, `${m.first_name} ${m.last_name}`.trim())}
      />
    </div>
  )
}

function ReignForm({
  reign,
  dignities,
  origins,
  onDone,
  onCancel,
}: {
  reign: Reign | null
  dignities: Dignity[]
  origins: Origin[]
  onDone: () => void
  onCancel: () => void
}) {
  const org = useActiveOrg()
  const form = useForm<ReignInput>({
    dignity: reign?.dignity ?? dignities.find((d) => !d.is_archived)?.id ?? dignities[0].id,
    // Bestehende Werte unverändert übernehmen: ein Zeitraum bleibt Zeitraum (UI-Audit NMF-02)
    year: reign ? reign.year : thisYear(),
    end_year: reign?.end_year ?? null,
    ordinal: reign?.ordinal ?? null,
    valid_from: reign?.valid_from ?? null,
    valid_until: reign?.valid_until ?? null,
    person: reign?.person ?? null,
    name: reign?.display_name ?? '',
    note: reign?.note ?? '',
    // Neu: leer lassen, damit der Server die Untereinheit des Mitglieds vorbelegt
    ...(reign ? { origin: reign.origin, origin_name: reign.origin_name } : {}),
    companions: (reign?.companions ?? []).map((c) => ({
      label: c.label,
      person: c.person,
      name: c.display_name ?? c.name,
    })),
  })
  const { values: v, set, errors } = form
  const [period, setPeriod] = useState(!!reign && !reign.year && !!reign.valid_from)
  // Neue Regentschaft: Foto erst mit „Anlegen“ übernehmen, „Abbrechen“ verwirft es (UI-Audit NMF-03).
  // Bestehende Regentschaft: Foto wird wie alle Felder sofort gespeichert.
  const [photo, setPhoto] = useState(reign?.photo ?? null)
  const [photoBusy, setPhotoBusy] = useState(false)
  const [photoError, setPhotoError] = useState<string | null>(null)
  const [photoFile, setPhotoFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const previewRef = useRef<string | null>(null)
  const shownPhoto = reign ? (photo?.small_url ?? null) : preview
  const crop = useImageCrop({ title: 'Fotoausschnitt festlegen' })

  // Bestehende Regentschaften speichern automatisch, neue erst mit „Anlegen“
  const auto = useAutoSave(
    form,
    (_changes, values) => honorsApi.updateReign(org.id, reign!.id, values),
    { enabled: reign !== null },
  )

  async function changePhoto(file: File | null) {
    if (!reign) {
      choosePhoto(file)
      return
    }
    if (
      file === null &&
      !(await confirmDialog({
        title: 'Foto entfernen?',
        message: 'Das Foto wird aus der Chronik gelöscht.',
        confirmLabel: 'Entfernen',
      }))
    )
      return
    setPhotoBusy(true)
    setPhotoError(null)
    try {
      if (file) setPhoto(await honorsApi.uploadPhoto(org.id, reign.id, file))
      else {
        await honorsApi.deletePhoto(org.id, reign.id)
        setPhoto(null)
      }
    } catch (err) {
      setPhotoError(`Das Foto wurde nicht gespeichert: ${errorMessage(err)}`)
    } finally {
      setPhotoBusy(false)
    }
  }

  function choosePhoto(file: File | null) {
    if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    previewRef.current = file ? URL.createObjectURL(file) : null
    setPreview(previewRef.current)
    setPhotoFile(file)
  }

  useEffect(
    () => () => {
      if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    },
    [],
  )

  function setCompanion(index: number, patch: Partial<Companion>) {
    set(
      'companions',
      v.companions.map((c, i) => (i === index ? { ...c, ...patch } : c)),
    )
  }

  function choosePeriod(on: boolean) {
    setPeriod(on)
    // Widersprechende Angaben bewusst leeren: entweder Jahr oder Zeitraum
    if (on) form.setValues({ ...v, year: null, end_year: null })
    else form.setValues({ ...v, year: v.year ?? thisYear(), valid_from: null, valid_until: null })
  }

  async function create() {
    const saved = await honorsApi.createReign(org.id, v)
    try {
      if (photoFile) await honorsApi.uploadPhoto(org.id, saved.id, photoFile)
    } catch (err) {
      throw new Error(`Die Regentschaft ist angelegt, das Foto aber nicht: ${errorMessage(err)}`)
    }
    onDone()
  }

  return (
    <form
      className="subcard"
      onSubmit={(e) => {
        e.preventDefault()
        if (reign) {
          void auto.flush().then((ok) => {
            if (ok && !photoBusy) onDone()
          })
          return
        }
        void form.submit(create)
      }}
    >
      <h3>{reign ? 'Regentschaft bearbeiten' : 'Neue Regentschaft'}</h3>
      {reign && <SaveStatus auto={auto} />}
      <div className="grid-2">
        <SelectField
          label="Würde"
          value={String(v.dignity)}
          error={errors.dignity}
          onChange={(e) => set('dignity', Number(e.target.value))}
        >
          {dignities.map((d) => (
            <option key={d.id} value={d.id}>
              {d.unit_name ? `${d.name} (${d.unit_name})` : d.name}
              {d.is_archived ? ' (nicht mehr verwendet)' : ''}
            </option>
          ))}
        </SelectField>
        <fieldset className="field">
          <legend>Angabe</legend>
          <label className="checkbox">
            <input type="radio" checked={!period} onChange={() => choosePeriod(false)} /> Jahr oder
            Jahre
          </label>
          <label className="checkbox">
            <input type="radio" checked={period} onChange={() => choosePeriod(true)} /> Zeitraum mit
            Datum
          </label>
        </fieldset>
      </div>
      {period ? (
        <div className="grid-2">
          <Field
            label="Zeitraum der Regentschaft: von"
            type="date"
            value={v.valid_from ?? ''}
            error={errors.valid_from ?? errors.year}
            onChange={(e) => set('valid_from', e.target.value || null)}
          />
          <Field
            label="Bis (leer = noch im Amt)"
            type="date"
            value={v.valid_until ?? ''}
            error={errors.valid_until}
            onChange={(e) => set('valid_until', e.target.value || null)}
          />
        </div>
      ) : (
        <div className="grid-2">
          <Field
            label={v.end_year ? 'Startjahr' : 'Jahr'}
            type="number"
            min={1000}
            max={2999}
            value={v.year ?? ''}
            error={errors.year}
            onChange={(e) => set('year', e.target.value ? Number(e.target.value) : null)}
          />
          <Field
            label="Endjahr (leer = nur ein Jahr)"
            type="number"
            min={1000}
            max={2999}
            value={v.end_year ?? ''}
            error={errors.end_year}
            onChange={(e) => set('end_year', e.target.value ? Number(e.target.value) : null)}
          />
        </div>
      )}
      <PersonField
        label="Würdenträger"
        person={v.person}
        name={v.name}
        onChange={(person, name) => form.setValues({ ...v, person, name })}
      />
      {errors.name && <Alert kind="error">{errors.name}</Alert>}
      {errors.person && <Alert kind="error">{errors.person}</Alert>}
      <OriginField
        origins={origins}
        origin={v.origin ?? null}
        name={v.origin_name ?? ''}
        onChange={(origin, origin_name) => form.setValues({ ...v, origin, origin_name })}
      />
      {errors.origin && <Alert kind="error">{errors.origin}</Alert>}
      {dignities.find((d) => d.id === v.dignity)?.numbered && (
        <Field
          label="Ordnungszahl (leer = automatisch je Vorname)"
          type="number"
          min={1}
          max={3999}
          value={v.ordinal ?? ''}
          placeholder={reign?.ordinal ? undefined : reign?.ordinal_text || undefined}
          error={errors.ordinal}
          onChange={(e) => set('ordinal', e.target.value ? Number(e.target.value) : null)}
        />
      )}
      <h4>Begleitpersonen</h4>
      {v.companions.map((c, i) => (
        <div key={i} className="subcard">
          <div className="grid-2">
            <Field
              label="Funktion"
              value={c.label}
              placeholder="z. B. Königin, Minister"
              onChange={(e) => setCompanion(i, { label: e.target.value })}
            />
            <button
              type="button"
              className="link-button"
              onClick={() =>
                set(
                  'companions',
                  v.companions.filter((_, j) => j !== i),
                )
              }
            >
              Begleitperson entfernen
            </button>
          </div>
          <PersonField
            label="Begleitperson"
            person={c.person}
            name={c.name}
            onChange={(person, name) => setCompanion(i, { person, name })}
          />
        </div>
      ))}
      {errors.companions && <Alert kind="error">{errors.companions}</Alert>}
      <button
        type="button"
        className="button button-ghost"
        onClick={() => set('companions', [...v.companions, { label: '', person: null, name: '' }])}
      >
        Begleitperson hinzufügen
      </button>
      <Field
        label="Bemerkung"
        value={v.note}
        placeholder="z. B. Jubiläumskönig"
        onChange={(e) => set('note', e.target.value)}
      />
      <div className="field">
        <span>Foto (z. B. Königspaar)</span>
        {shownPhoto && <img src={shownPhoto} alt="" width={200} />}
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          aria-label="Foto auswählen"
          disabled={photoBusy}
          onChange={(e) => {
            const file = e.target.files?.[0] ?? null
            e.target.value = ''
            if (file)
              void crop.pick(file).then((cropped) => {
                if (cropped) void changePhoto(cropped)
              })
          }}
        />
        {crop.dialog}
        <RightsHint />
        {shownPhoto && (
          <button
            type="button"
            className="link-button"
            disabled={photoBusy}
            onClick={() => void changePhoto(null)}
          >
            Foto entfernen
          </button>
        )}
        {photoBusy && <p className="muted small">Foto wird gespeichert …</p>}
        {photoError && <Alert kind="error">{photoError}</Alert>}
        <small className="muted">
          {reign
            ? 'Wird sofort übernommen, verkleinert und ohne Metadaten gespeichert.'
            : 'Wird mit „Anlegen“ übernommen, verkleinert und ohne Metadaten gespeichert.'}{' '}
          Auf der Webseite erscheint es nur, wenn alle verknüpften Mitglieder in Fotos eingewilligt
          haben.
        </small>
      </div>
      {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
      <div className="button-row">
        <button
          type="submit"
          className={reign ? 'button button-ghost' : 'button button-primary'}
          disabled={form.busy || photoBusy}
        >
          {reign ? 'Schließen' : 'Anlegen'}
        </button>
        {!reign && (
          <button type="button" className="button" onClick={onCancel}>
            Abbrechen
          </button>
        )}
      </div>
    </form>
  )
}

// --- Würden ---

function DignitiesPanel() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.membersEdit)
  const { data, error, reload } = useLoad(() => honorsApi.dignities(org.id), [org.id])
  // Untereinheiten (Züge) gibt es nur bei Vereinen; die oberste Einheit mit eigenen
  // Mitgliedern hat keine, dort würde die Abfrage scheitern
  const club = org.type === 'club'
  const units = useLoad(
    () => (club ? orgApi.departments(org.id) : Promise.resolve([])),
    [org.id, club],
  )
  const [editing, setEditing] = useState<Dignity | 'new' | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [sorting, setSorting] = useState(false)

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>

  // Je Einheit eine Liste: erst die eigenen Würden, dann die der Untereinheiten
  const groups = [...new Set(data.map((d) => d.unit))].map((unit) => ({
    unit,
    name: data.find((d) => d.unit === unit)?.unit_name ?? org.name,
    items: data.filter((d) => d.unit === unit),
  }))
  groups.sort((a, b) => (a.unit === null ? -1 : b.unit === null ? 1 : 0))

  async function remove(d: Dignity) {
    setMessage(null)
    const ok = await confirmDialog({
      title: 'Würde löschen?',
      message:
        d.reign_count > 0
          ? `„${d.name}“ wird mit allen ${d.reign_count} Regentschaften gelöscht, samt Begleitpersonen und Fotos. Das lässt sich nicht rückgängig machen.`
          : `„${d.name}“ wird gelöscht.`,
      confirmLabel: 'Löschen',
    })
    if (!ok) return
    try {
      await honorsApi.deleteDignity(org.id, d.id, d.reign_count > 0)
      await reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  const columns: Column<Dignity>[] = [
    { key: 'name', label: 'Würde', value: (d) => d.name },
    {
      key: 'unit',
      label: 'Gehört zu',
      value: (d) => d.unit_name ?? org.name,
      filter: true,
    },
    {
      key: 'public',
      label: 'Webseite',
      value: (d) => (d.is_public ? 'öffentlich' : 'nicht öffentlich'),
      optional: true,
    },
    {
      key: 'status',
      label: 'Status',
      value: (d) => (d.is_archived ? 'nicht mehr verwendet' : 'aktiv'),
      filter: { initial: 'aktiv' },
    },
    { key: 'count', label: 'Regentschaften', value: (d) => d.reign_count, numeric: true },
  ]

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>Würden</h2>
        {canEdit && editing === null && (
          <div className="button-row push-right">
            {groups.some((g) => g.items.length > 1) && (
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
                Neue Würde
              </button>
            )}
          </div>
        )}
      </div>
      <p className="muted small">
        Welche Würden es gibt, legt ihr selbst fest, z. B. König, Prinz, Schülerprinz oder Kaiser.
        Würden einer Untereinheit (z. B. Zugkönig) erscheinen auf deren Seite. Eine Würde trägt
        jemand für eine Zeit, meist ein Jahr, danach folgt der Nächste. Dauerhafte Auszeichnungen
        wie Ehrenmitglied sind dagegen Ehrungen (Mitglieder › Einrichtung › Ehrungen).
      </p>
      {editing !== null && units.error && (
        <LoadError
          message={`Die Untereinheiten konnten nicht geladen werden; die Zuordnung zu einer Untereinheit ist deshalb gerade nicht wählbar. ${units.error}`}
          onRetry={() => void units.reload()}
        />
      )}
      {editing !== null && (
        <DignityForm
          key={editing === 'new' ? 'new' : editing.id}
          dignity={editing === 'new' ? null : editing}
          units={units.data ?? []}
          onDone={async () => {
            setEditing(null)
            await reload()
          }}
          onCancel={() => setEditing(null)}
        />
      )}
      {message && <Alert kind="error">{message}</Alert>}
      {sorting ? (
        <>
          <SortHint website={org.modules.includes('website')} />
          {groups.map((g) => (
            <div key={g.unit ?? 0}>
              {groups.length > 1 && <h3>{g.name}</h3>}
              <SortableList
                ariaLabel={`Reihenfolge der Würden: ${g.name}`}
                items={g.items}
                id={(d) => d.id}
                label={(d) => d.name}
                render={(d) => (
                  <span className={d.is_archived ? 'muted' : undefined}>
                    {d.name}
                    {d.is_archived && ' (nicht mehr verwendet)'}
                  </span>
                )}
                onReorder={(ids) =>
                  honorsApi.reorderDignities(org.id, g.unit, ids).then(() => reload())
                }
              />
            </div>
          ))}
        </>
      ) : (
        <DataTable
          label="Würden"
          rows={data}
          rowKey={(d) => d.id}
          columns={columns}
          emptyText="Noch keine Würden angelegt."
          rowClassName={(d) => (d.is_archived ? 'inactive' : undefined)}
          actions={
            canEdit
              ? (d) => (
                  <>
                    <IconButton
                      label={`${d.name} bearbeiten`}
                      icon={<EditIcon />}
                      onClick={() => setEditing(d)}
                    />
                    <IconButton
                      label={`${d.name} löschen`}
                      icon={<DeleteIcon />}
                      danger
                      onClick={() => void remove(d)}
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

function DignityForm({
  dignity,
  units,
  onDone,
  onCancel,
}: {
  dignity: Dignity | null
  units: { id: number; name: string }[]
  onDone: () => void
  onCancel: () => void
}) {
  const org = useActiveOrg()
  const form = useForm({
    name: dignity?.name ?? '',
    unit: dignity?.unit ?? null,
    is_public: dignity?.is_public ?? true,
    is_archived: dignity?.is_archived ?? false,
    numbered: dignity?.numbered ?? false,
    count_each_reign: dignity?.count_each_reign ?? false,
    share_down: dignity?.share_down ?? false,
    name_plural: dignity?.name_plural ?? '',
  })
  const { values: v, set, errors } = form
  // Bestehende Würden speichern automatisch, neue erst mit „Anlegen“
  const auto = useAutoSave(
    form,
    (changes) => honorsApi.updateDignity(org.id, dignity!.id, changes),
    { enabled: dignity !== null },
  )
  return (
    <form
      className="subcard"
      onSubmit={(e) => {
        e.preventDefault()
        if (dignity) {
          void auto.flush().then((ok) => {
            if (ok) onDone()
          })
          return
        }
        void form.submit(async () => {
          await honorsApi.createDignity(org.id, v)
          onDone()
        })
      }}
    >
      {dignity && <SaveStatus auto={auto} />}
      <div className="grid-2">
        <Field
          label="Bezeichnung"
          value={v.name}
          required
          error={errors.name}
          onChange={(e) => set('name', e.target.value)}
        />
        <Field
          label="Mehrzahl (für Überschrift und Menü der Webseite)"
          value={v.name_plural}
          placeholder={dignity?.plural || undefined}
          error={errors.name_plural}
          onChange={(e) => set('name_plural', e.target.value)}
        />
        <SelectField
          label="Gehört zu"
          value={v.unit === null ? '' : String(v.unit)}
          error={errors.unit}
          onChange={(e) => set('unit', e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">{org.name}</option>
          {units.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
            </option>
          ))}
        </SelectField>
      </div>
      <Checkbox
        label="In der Chronik auf der Webseite zeigen"
        checked={v.is_public}
        onChange={(on) => set('is_public', on)}
      />
      <Checkbox
        label="An Untereinheiten weitergeben"
        hint="Vereine bzw. Züge darunter sehen die Träger, die aus ihnen kamen (Feld „Aus“), und können sie auf ihrer Webseite zeigen."
        checked={v.share_down}
        onChange={(on) => set('share_down', on)}
      />
      <Checkbox
        label="Ordnungszahl je Vorname (der erste Michael ist „Michael I.“, der zweite „Michael II.“)"
        checked={v.numbered}
        onChange={(on) => set('numbered', on)}
      />
      {v.numbered && <HowTo k="how_regnal_number" />}
      {v.numbered && (
        <Checkbox
          label="Bei mehrfacher Würde neu zählen (zweimal Otto Muster: Otto I. und Otto II.; sonst behält er seine Zahl)"
          checked={v.count_each_reign}
          onChange={(on) => set('count_each_reign', on)}
        />
      )}
      {dignity && (
        <Checkbox
          label="Nicht mehr verwendet (bisherige Regentschaften bleiben)"
          checked={v.is_archived}
          onChange={(on) => set('is_archived', on)}
        />
      )}
      {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
      <div className="button-row">
        <button
          type="submit"
          className={dignity ? 'button button-ghost' : 'button button-primary'}
          disabled={form.busy}
        >
          {dignity ? 'Schließen' : 'Anlegen'}
        </button>
        {!dignity && (
          <button type="button" className="button" onClick={onCancel}>
            Abbrechen
          </button>
        )}
      </div>
    </form>
  )
}

// --- Import ---

interface Decision {
  take: boolean
  person_id: number | null
  companions: (number | null)[]
}

function ImportPanel() {
  const org = useActiveOrg()
  const [rows, setRows] = useState<ImportRow[] | null>(null)
  // Ein Schlüssel je Vorschau: nochmal „Übernehmen“ (z. B. nach Verbindungsabbruch)
  // legt nichts doppelt an
  const [requestKey, setRequestKey] = useState(newRequestKey)
  const [newDignities, setNewDignities] = useState<string[]>([])
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function read(file: File) {
    setError(null)
    setResult(null)
    setBusy(true)
    try {
      const data = await honorsApi.importPreview(org.id, file)
      setRows(data.rows)
      setRequestKey(newRequestKey())
      setNewDignities(data.new_dignities)
      setDecisions(
        data.rows.map((r) => ({
          take: r.errors.length === 0 && !r.duplicate,
          person_id: r.person_id,
          companions: r.companions.map((c) => c.person_id),
        })),
      )
    } catch (err) {
      setRows(null)
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  function decide(index: number, patch: Partial<Decision>) {
    setDecisions((all) => all.map((d, i) => (i === index ? { ...d, ...patch } : d)))
  }

  async function commit() {
    if (!rows) return
    setBusy(true)
    setError(null)
    try {
      const chosen = rows
        .map((r, i) => ({ r, d: decisions[i] }))
        .filter(({ r, d }) => d.take && r.errors.length === 0 && r.year !== null)
        .map(({ r, d }) => ({
          year: r.year as number,
          end_year: r.end_year ?? null,
          dignity: r.dignity,
          name: r.name,
          person_id: d.person_id,
          note: r.note,
          ordinal: r.ordinal ?? null,
          origin: r.origin ?? null,
          origin_name: r.origin_name ?? '',
          companions: r.companions.map((c, j) => ({
            label: c.label,
            name: c.name,
            person_id: d.companions[j],
          })),
        }))
      const res = await honorsApi.importRows(org.id, chosen, requestKey)
      setResult(
        `${res.created} Regentschaften übernommen.` +
          (res.dignities_created.length
            ? ` Neu angelegte Würden: ${res.dignities_created.join(', ')}. Sie sind erst intern; unter „Würden“ könnt ihr sie zur Veröffentlichung freigeben.`
            : ''),
      )
      setRows(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const count = rows ? decisions.filter((d, i) => d.take && rows[i].errors.length === 0).length : 0

  return (
    <div className="card card-wide">
      <h2>Königsliste importieren</h2>
      <p className="muted small">
        Excel- oder CSV-Datei mit den Spalten <strong>Jahr</strong>, <strong>Würde</strong>,{' '}
        <strong>Name</strong> und optional <strong>Endjahr</strong> (für Würden über mehrere Jahre),{' '}
        <strong>Begleitung</strong> (z. B. „Königin: Erika Beispiel; Minister: Max Muster“),{' '}
        <strong>Bemerkung</strong>, <strong>Ordnungszahl</strong> (z. B. „IV“ aus einer alten Liste;
        leer zählt HUBIplan selbst) und <strong>Aus</strong> (Zug oder Verein, aus dem der
        Würdenträger kam). HUBIplan schlägt zu jedem Namen passende Mitglieder vor; prüft die
        Zuordnung, bevor ihr übernehmt. Unbekannte Würden werden angelegt, zunächst nur intern.
      </p>
      <input
        type="file"
        accept=".xlsx,.xlsm,.csv,.txt"
        aria-label="Datei auswählen"
        disabled={busy}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void read(file)
        }}
      />
      {error && <Alert kind="error">{error}</Alert>}
      {result && <Alert kind="success">{result}</Alert>}
      {rows && (
        <>
          {newDignities.length > 0 && (
            <Alert kind="info">
              Neue Würden werden angelegt: {newDignities.join(', ')}. Sie erscheinen nicht auf der
              Webseite, bis ihr sie unter „Würden“ freigebt.
            </Alert>
          )}
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Übernehmen</th>
                  <th>Zeile</th>
                  <th>Jahr</th>
                  <th>Würde</th>
                  <th>Name und Zuordnung</th>
                  <th>Zahl</th>
                  <th>Begleitung</th>
                  <th>Bemerkung</th>
                  <th>Aus</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.line} className={r.errors.length ? 'inactive' : undefined}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Zeile ${r.line} übernehmen`}
                        checked={decisions[i].take}
                        disabled={r.errors.length > 0}
                        onChange={(e) => decide(i, { take: e.target.checked })}
                      />
                    </td>
                    <td>{r.line}</td>
                    <td>{r.end_year ? `${r.year}–${r.end_year}` : (r.year ?? '')}</td>
                    <td>{r.dignity}</td>
                    <td>
                      {r.name}
                      {r.errors.length > 0 && (
                        <div className="field-error small">{r.errors.join(' ')}</div>
                      )}
                      {r.duplicate && <div className="muted small">Schon vorhanden.</div>}
                      {r.name && (
                        <CandidateSelect
                          label={`Zuordnung Zeile ${r.line}`}
                          candidates={r.candidates}
                          value={decisions[i].person_id}
                          onChange={(id) => decide(i, { person_id: id })}
                        />
                      )}
                    </td>
                    <td>{r.ordinal_text}</td>
                    <td>
                      {r.companions.map((c, j) => (
                        <div key={j}>
                          {c.label}: {c.name}
                          <CandidateSelect
                            label={`Zuordnung ${c.label} Zeile ${r.line}`}
                            candidates={c.candidates ?? []}
                            value={decisions[i].companions[j]}
                            onChange={(id) =>
                              decide(i, {
                                companions: decisions[i].companions.map((x, k) =>
                                  k === j ? id : x,
                                ),
                              })
                            }
                          />
                        </div>
                      ))}
                    </td>
                    <td>{r.note}</td>
                    <td>
                      {r.origin_text}
                      {r.origin_name && <span className="muted small"> (frei)</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="button-row">
            <button
              type="button"
              className="button button-primary"
              disabled={busy || count === 0}
              onClick={() => void commit()}
            >
              {count} Regentschaften übernehmen
            </button>
          </div>
        </>
      )}
    </div>
  )
}

export function CandidateSelect({
  label,
  candidates,
  value,
  onChange,
}: {
  label: string
  candidates: { id: number; name: string; birth_year: number | null }[]
  value: number | null
  onChange: (id: number | null) => void
}) {
  if (candidates.length === 0) return <div className="muted small">kein passendes Mitglied</div>
  return (
    <select
      aria-label={label}
      value={value === null ? '' : String(value)}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
    >
      <option value="">nur Name (kein Mitglied)</option>
      {candidates.map((c) => (
        <option key={c.id} value={c.id}>
          {c.name}
          {c.birth_year ? ` (geb. ${c.birth_year})` : ''}
        </option>
      ))}
    </select>
  )
}
