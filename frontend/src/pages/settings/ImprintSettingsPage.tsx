import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { imprintApi, imprintPath, privacyPath } from '../../api/imprint.ts'
import type { ImprintFields, ImprintState } from '../../api/imprint.ts'
import { orgApi, PERM, unitName } from '../../api/orgs.ts'
import type { Department } from '../../api/orgs.ts'
import { useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { MemberPrivacyEditor } from './PrivacySettingsPage.tsx'
import { TextArea } from './TextArea.tsx'
import { Alert, Checkbox, Field, LoadError, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg, useOrg } from '../../org/OrgContext.tsx'
import { Term, Why } from '../../learning/Aids.tsx'

const FIELDS: (keyof ImprintFields)[] = [
  'mode',
  'external_url',
  'name',
  'legal_form',
  'street',
  'postal_code',
  'city',
  'representatives',
  'email',
  'phone',
  'registered',
  'register_court',
  'register_number',
  'vat_id',
  'responsible',
  'data_protection_officer',
  'extra_text',
]

function pick(state: ImprintState): ImprintFields {
  return Object.fromEntries(FIELDS.map((k) => [k, state.imprint[k]])) as unknown as ImprintFields
}

/** Hinweis auf fehlende Angaben, z. B. auf der Startseite. */
export function ImprintMissing({ missing }: { missing: string[] }) {
  if (missing.length === 0) return null
  return (
    <Alert kind="info">
      Im Impressum fehlen noch Angaben: {missing.join(', ')}.{' '}
      <Link to="/einstellungen/impressum">Impressum ergänzen</Link>
    </Alert>
  )
}

export function ImprintEditor({
  state,
  editable,
  save,
}: {
  state: ImprintState
  editable: boolean
  save: (changes: Partial<ImprintFields>) => Promise<ImprintState>
}) {
  const [current, setCurrent] = useState(state)
  const form = useForm(pick(state))
  const { values: v, set, errors } = form
  const auto = useAutoSave(form, (changes) => save(changes), {
    enabled: editable,
    onSaved: (saved) => setCurrent(saved as ImprintState),
  })
  const isPlatform = state.organization.type === 'platform'
  const isUnit = state.organization.type === 'unit'
  const p = current.preview
  const key = isPlatform ? null : current.imprint.public_key
  // Sprung aus der Prüfliste der Webseite, z. B. ?feld=verantwortlich
  const [params] = useSearchParams()
  const jumpTo = params.get('feld')
  useEffect(() => {
    if (!jumpTo) return
    const el = document.getElementById(jumpTo)
    el?.scrollIntoView?.({ block: 'center' })
    el?.focus()
  }, [jumpTo])

  return (
    <form className="card card-wide" onSubmit={(e) => e.preventDefault()}>
      {editable && <SaveStatus auto={auto} />}
      <h2>Impressum {isPlatform ? 'der Plattform' : state.organization.name}</h2>
      <p className="muted small">
        HUBIplan zeigt die Angaben auf einer öffentlichen Seite und verlinkt sie in jeder Mail und
        auf den öffentlichen Seiten. Ob die Angaben vollständig und richtig sind, muss{' '}
        {isPlatform ? 'der Betreiber' : 'die Einheit'} selbst prüfen (keine Rechtsberatung).
      </p>
      <p className="small">
        Öffentlich: <Link to={imprintPath(key)}>Impressum</Link> ·{' '}
        <Link to={privacyPath(key)}>
          {isPlatform ? 'Datenschutzerklärung' : 'Datenschutzhinweise'}
        </Link>
      </p>
      {!isPlatform && (
        <p className="muted small">
          Die Datenschutzhinweise für Mitglieder und für die Webseite stehen gemeinsam unter{' '}
          <Link to="/einstellungen/datenschutz">Einstellungen › Datenschutz</Link>.
        </p>
      )}
      {current.missing.length > 0 && (
        <Alert kind="info">Es fehlen noch: {current.missing.join(', ')}.</Alert>
      )}
      <fieldset disabled={!editable}>
        {!isPlatform && (
          <SelectField
            label="Impressum"
            value={v.mode}
            error={errors.mode}
            onChange={(e) => set('mode', e.target.value as ImprintFields['mode'])}
          >
            <option value="inherit">von der übergeordneten Einheit übernehmen</option>
            <option value="own">eigenes Impressum</option>
            <option value="link">auf eigenes Impressum verlinken (z. B. eigene Website)</option>
          </SelectField>
        )}
        {v.mode === 'inherit' && !current.owner.is_self && (
          <p className="muted">
            Es gilt das Impressum von {current.owner.name}
            {isUnit ? '' : ' (bzw. der Plattform, wenn darüber keine Einheit eines hat)'}.
          </p>
        )}
        {v.mode === 'link' && (
          <Field
            label="Adresse des eigenen Impressums"
            type="url"
            placeholder="https://"
            value={v.external_url}
            error={errors.external_url}
            onChange={(e) => set('external_url', e.target.value)}
          />
        )}
        {v.mode === 'own' && (
          <>
            <p className="muted small">
              Leere Felder werden aus den Stammdaten übernommen (Einstellungen › Organisation).
            </p>
            <div className="grid-2">
              <Field
                label={isPlatform ? 'Betreiber (Name bzw. Firma)' : 'Name'}
                value={v.name}
                placeholder={p.name}
                error={errors.name}
                onChange={(e) => set('name', e.target.value)}
              />
              <Field
                label="Rechtsform"
                value={v.legal_form}
                placeholder={
                  isPlatform
                    ? 'z. B. Einzelunternehmen, GmbH'
                    : v.registered
                      ? 'eingetragener Verein'
                      : 'z. B. nicht eingetragener Verein'
                }
                error={errors.legal_form}
                onChange={(e) => set('legal_form', e.target.value)}
              />
            </div>
            <h3>Anschrift (ladungsfähig, kein Postfach)</h3>
            <Field
              label="Straße und Hausnummer"
              value={v.street}
              placeholder={p.address.street}
              error={errors.street}
              onChange={(e) => set('street', e.target.value)}
            />
            <div className="grid-3">
              <Field
                label="PLZ"
                value={v.postal_code}
                placeholder={p.address.postal_code}
                error={errors.postal_code}
                onChange={(e) => set('postal_code', e.target.value)}
              />
              <Field
                label="Ort"
                value={v.city}
                placeholder={p.address.city}
                error={errors.city}
                onChange={(e) => set('city', e.target.value)}
              />
            </div>
            <h3>
              <Term k="board_26">Vertretungsberechtigt</Term>
            </h3>
            {!isPlatform && (
              <p className="muted small">
                {current.representatives.length > 0
                  ? `Aus den Rollen: ${current.representatives
                      .map((r) => `${r.name} (${r.role})`)
                      .join(', ')}.`
                  : 'Noch keine Rolle mit „vertritt die Einheit (§ 26 BGB)“ besetzt.'}{' '}
                Das Kennzeichen setzt du unter{' '}
                <Link to="/einstellungen/rollen">Rollen &amp; Benutzer</Link>. Ein Text hier ersetzt
                die Angaben aus den Rollen.
              </p>
            )}
            <TextArea
              label={
                isPlatform
                  ? 'Vertreten durch (bei Firmen oder Vereinen)'
                  : 'Vertreten durch (optional)'
              }
              value={v.representatives}
              error={errors.representatives}
              onChange={(val) => set('representatives', val)}
            />
            <h3>Kontakt</h3>
            <p className="muted small">
              Nötig sind zwei schnelle Wege, üblich sind E-Mail und Telefon.
            </p>
            <div className="grid-2">
              <Field
                label="E-Mail"
                type="email"
                value={v.email}
                placeholder={p.email}
                error={errors.email}
                onChange={(e) => set('email', e.target.value)}
              />
              <Field
                label="Telefon"
                value={v.phone}
                placeholder={p.phone}
                error={errors.phone}
                onChange={(e) => set('phone', e.target.value)}
              />
            </div>
            <h3>
              <Term k="register">Register</Term> und <Term k="vat_id">Steuer</Term>
            </h3>
            <Checkbox
              label={
                isPlatform
                  ? 'Im Handels- oder Vereinsregister eingetragen'
                  : 'Eingetragener Verein (e.V., im Vereinsregister)'
              }
              checked={v.registered}
              onChange={(val) => set('registered', val)}
            />
            <p className="muted small">
              {v.registered
                ? 'Registergericht und Registernummer gehören dann ins Impressum und auf den Briefbogen.'
                : 'Ohne Registereintrag (z. B. nicht eingetragener Verein) entfallen die Registerangaben.'}
            </p>
            <div className="grid-3">
              {v.registered && (
                <>
                  <Field
                    label="Registergericht"
                    value={v.register_court}
                    placeholder="z. B. Amtsgericht Neuss"
                    required
                    error={errors.register_court}
                    onChange={(e) => set('register_court', e.target.value)}
                  />
                  <Field
                    label="Registernummer"
                    value={v.register_number}
                    placeholder="z. B. VR 1234"
                    required
                    error={errors.register_number}
                    onChange={(e) => set('register_number', e.target.value)}
                  />
                </>
              )}
              <Field
                label="USt-IdNr. (falls vorhanden)"
                value={v.vat_id}
                error={errors.vat_id}
                onChange={(e) => set('vat_id', e.target.value)}
              />
            </div>
            <h3>Weitere Angaben (optional)</h3>
            <TextArea
              id="verantwortlich"
              label="Verantwortlich nach § 18 Abs. 2 MStV (Name und Anschrift)"
              hint="Empfohlen, sobald die Webseite eigene Texte hat (Begrüßung, Chronik), und bei einer Vereinszeitung."
              value={v.responsible}
              error={errors.responsible}
              onChange={(val) => set('responsible', val)}
            />
            <TextArea
              label="Datenschutzbeauftragte(r)"
              hint="Pflicht erst, wenn mindestens 20 Personen ständig mit Personendaten arbeiten."
              value={v.data_protection_officer}
              error={errors.data_protection_officer}
              onChange={(val) => set('data_protection_officer', val)}
            />
            <Why k="dpo" />
            <TextArea
              label="Weiterer Text"
              value={v.extra_text}
              error={errors.extra_text}
              onChange={(val) => set('extra_text', val)}
            />
          </>
        )}
      </fieldset>
    </form>
  )
}

/** Einstellungen › Impressum: die Einheit selbst und ihre Untereinheiten. */
export function ImprintSettingsPage() {
  const org = useActiveOrg()
  const { can } = useOrg()
  const editable = can(PERM.orgEdit)
  const [unitId, setUnitId] = useState<number | null>(null)
  const units = useLoad(
    () => (org.type === 'club' ? orgApi.departments(org.id) : Promise.resolve([] as Department[])),
    [org.id],
  )
  const state = useLoad(
    () => (unitId ? imprintApi.unit(org.id, unitId) : imprintApi.get(org.id)),
    [org.id, unitId],
  )
  const list = units.data ?? []

  return (
    <>
      {units.error && (
        <LoadError
          message={`Die ${org.department_label_plural} konnten nicht geladen werden; ihre Impressen sind deshalb gerade nicht wählbar. ${units.error}`}
          onRetry={() => void units.reload()}
        />
      )}
      {list.length > 0 && (
        <div className="card card-wide">
          <SelectField
            label="Impressum für"
            value={unitId ?? ''}
            hint={`${org.department_label_plural} übernehmen standardmäßig das Impressum von ${org.name}.`}
            onChange={(e) => setUnitId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">{org.name}</option>
            {list.map((d) => (
              <option key={d.id} value={d.id}>
                {unitName(d)}
              </option>
            ))}
          </SelectField>
        </div>
      )}
      {state.error && <Alert kind="error">{state.error}</Alert>}
      {!state.data && !state.error && <p className="muted">Lädt …</p>}
      {state.data && state.data.organization.id === (unitId ?? org.id) && (
        <ImprintEditor
          key={state.data.organization.id}
          state={state.data}
          editable={editable}
          save={(changes) =>
            unitId
              ? imprintApi.updateUnit(org.id, unitId, changes)
              : imprintApi.update(org.id, changes)
          }
        />
      )}
    </>
  )
}

/** Plattform › Impressum, darunter die Datenschutzerklärung der Plattform. */
export function PlatformImprintPage() {
  const { data, error } = useLoad(() => imprintApi.platform(), [])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>
  return (
    <>
      <ImprintEditor state={data} editable save={(changes) => imprintApi.updatePlatform(changes)} />
      <MemberPrivacyEditor
        state={data}
        editable
        save={(changes) => imprintApi.updatePlatform(changes)}
        publish={() => imprintApi.publishPrivacy(null)}
      />
    </>
  )
}
