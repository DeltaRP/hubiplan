import { FiscalYearFields } from '../../components/FiscalYearFields.tsx'
import { orgApi, PERM } from '../../api/orgs.ts'
import type { OrgDetail, Role } from '../../api/orgs.ts'
import { Alert, Checkbox, Field, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { SocialLinksPanel } from '../../components/SocialLinksPanel.tsx'
import { StatutePanel } from '../../components/StatutePanel.tsx'
import { useActiveOrg, useOrg } from '../../org/OrgContext.tsx'
import { LabelFields } from '../../components/LabelFields.tsx'
import { buildFederationTerms, buildTerms } from '../../org/terms.ts'
import { Why } from '../../learning/Aids.tsx'

export function OrganizationPage() {
  const org = useActiveOrg()
  const { data, error, setData } = useLoad(() => orgApi.detail(org.id), [org.id])
  const canEditRoles = org.permissions.includes(PERM.rolesManage)
  const roles = useLoad(
    () => (canEditRoles ? orgApi.roles(org.id) : Promise.resolve([] as Role[])),
    [org.id, canEditRoles],
  )

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">Lädt …</p>
  return (
    <>
      <OrganizationForm key={data.id} detail={data} roles={roles.data ?? []} onSaved={setData} />
      {(data.type === 'club' || data.type === 'federation') && (
        <SocialLinksPanel orgId={org.id} editable={org.permissions.includes(PERM.orgEdit)} />
      )}
      {data.type !== 'platform' && (
        <>
          <div className="card card-wide">
            <StatutePanel orgId={org.id} />
          </div>
          <div className="card card-wide">
            <StatutePanel orgId={org.id} kind="fee_rules" />
          </div>
          <div className="card card-wide">
            <StatutePanel orgId={org.id} kind="founding_deed" />
          </div>
        </>
      )}
    </>
  )
}

function OrganizationForm({
  detail,
  roles,
  onSaved,
}: {
  detail: OrgDetail
  roles: Role[]
  onSaved: (d: OrgDetail) => void
}) {
  const { can, refresh } = useOrg()
  const editable = can(PERM.orgEdit)
  const form = useForm(detail)
  const { values: v, set, errors } = form
  const isPlatform = detail.type === 'platform'
  const preview = buildTerms(
    v.department_label,
    v.department_label_plural,
    v.department_label_gender,
    v.department_label_genitive,
  )

  const auto = useAutoSave(
    form,
    (changes) => {
      const payload = Object.fromEntries(
        EDITABLE.filter((key) => key in changes).map((key) => [key, changes[key]]),
      ) as Partial<OrgDetail>
      return orgApi.update(detail.id, payload)
    },
    {
      enabled: editable,
      onSaved: (saved) => {
        if ((saved as OrgDetail).type !== detail.type) {
          // Mit dem Schalter „führt eigene Mitglieder“ ändern sich Menü und Einstellungen
          window.location.reload()
          return
        }
        onSaved(saved as OrgDetail)
        void refresh()
      },
    },
  )

  const boardRoles = roles.filter((r) => r.is_board)
  const contact = detail.contact_effective

  return (
    <form className="card card-wide" onSubmit={(e) => e.preventDefault()}>
      {editable && <SaveStatus auto={auto} />}
      <h2>{detail.type_label}</h2>
      {detail.parent_name && <p className="muted">Gehört zu: {detail.parent_name}</p>}
      <fieldset disabled={!editable}>
        <div className="grid-2">
          <Field
            label={isPlatform ? 'Name' : 'Vollständiger Name'}
            required
            value={v.name}
            error={errors.name}
            hint={
              isPlatform ? undefined : 'Erscheint auf Rechnungen, Ausweisen, PDFs und in Mails.'
            }
            onChange={(e) => set('name', e.target.value)}
          />
          {!isPlatform && (
            <Field
              label="Kurzname (optional)"
              maxLength={50}
              value={v.short_name ?? ''}
              error={errors.short_name}
              hint="Für Navigation, Listen und Auswahlfelder. Leer = vollständiger Name."
              onChange={(e) => set('short_name', e.target.value)}
            />
          )}
          {!isPlatform && (
            <Field
              label="Gründungsjahr"
              type="number"
              required
              min={800}
              max={2100}
              value={v.founding_year ?? ''}
              error={errors.founding_year}
              onChange={(e) => set('founding_year', e.target.value ? Number(e.target.value) : null)}
            />
          )}
        </div>

        {!isPlatform && (
          <>
            <h3>Anschrift</h3>
            <Field
              label="Straße und Hausnummer"
              required
              value={v.street}
              error={errors.street}
              onChange={(e) => set('street', e.target.value)}
            />
            <div className="grid-3">
              <Field
                label="PLZ"
                required
                value={v.postal_code}
                error={errors.postal_code}
                onChange={(e) => set('postal_code', e.target.value)}
              />
              <Field
                label="Ort"
                required
                value={v.city}
                error={errors.city}
                onChange={(e) => set('city', e.target.value)}
              />
              <Field
                label="Land"
                value={v.country}
                error={errors.country}
                onChange={(e) => set('country', e.target.value)}
              />
            </div>
          </>
        )}

        <h3>Kontakt</h3>
        {!isPlatform && (
          <SelectField
            label="Kontaktdaten"
            value={v.contact_source}
            error={errors.contact_source}
            onChange={(e) => set('contact_source', e.target.value as OrgDetail['contact_source'])}
          >
            <option value="own">eigene Angaben</option>
            <option value="role">von einer Vorstandsrolle übernehmen</option>
          </SelectField>
        )}
        {v.contact_source === 'role' ? (
          <>
            <SelectField
              label="Rolle"
              value={v.contact_role ?? ''}
              error={errors.contact_role}
              onChange={(e) => set('contact_role', e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">– bitte wählen –</option>
              {boardRoles.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
              {!canListRoles(roles, v.contact_role) && v.contact_role && (
                <option value={v.contact_role}>{contact.role ?? 'gewählte Rolle'}</option>
              )}
            </SelectField>
            <p className="muted small">
              Die Kontaktdaten kommen von der Person, die die Rolle gerade innehat. Wechselt die
              Person, ändern sich die Kontaktdaten automatisch.
              {contact.source === 'role' &&
                ` Aktuell: ${contact.holder ?? 'niemand'}${contact.email ? `, ${contact.email}` : ''}.`}
            </p>
          </>
        ) : (
          <div className="grid-2">
            <Field
              label="E-Mail"
              type="email"
              value={v.contact_email}
              error={errors.contact_email}
              onChange={(e) => set('contact_email', e.target.value)}
            />
            <Field
              label="Telefon"
              value={v.contact_phone}
              error={errors.contact_phone}
              onChange={(e) => set('contact_phone', e.target.value)}
            />
          </div>
        )}
        <Field
          label="Website"
          type="url"
          placeholder="https://"
          value={v.website}
          error={errors.website}
          onChange={(e) => set('website', e.target.value)}
        />

        {detail.type === 'federation' && (
          <FederationNameGrammar
            name={v.short_name?.trim() || v.name}
            gender={v.name_gender ?? 'm'}
            genitive={v.name_genitive ?? ''}
            errors={errors}
            onGender={(g) => set('name_gender', g)}
            onGenitive={(g) => set('name_genitive', g)}
          />
        )}
        {!isPlatform && (
          <>
            <h3>Bezeichnung dieser Einheit</h3>
            <p className="muted small">
              Wie heißt diese Einheit in den Texten der App? Zum Beispiel Verein, Gesellschaft,
              Dachverband oder Bruderschaft.
            </p>
            <LabelFields
              testId="own-terms-preview"
              value={{
                label: v.label ?? '',
                plural: v.label_plural ?? '',
                gender: v.label_gender ?? 'm',
                genitive: v.label_genitive ?? '',
                labelEn: v.label_en ?? '',
                pluralEn: v.label_plural_en ?? '',
              }}
              errors={{
                label: errors.label,
                plural: errors.label_plural,
                gender: errors.label_gender,
                genitive: errors.label_genitive,
              }}
              onChange={(l) => {
                set('label', l.label)
                set('label_plural', l.plural)
                set('label_gender', l.gender)
                set('label_genitive', l.genitive)
                set('label_en', l.labelEn ?? '')
                set('label_plural_en', l.pluralEn ?? '')
              }}
            />
          </>
        )}
        {(detail.type === 'club' || detail.type === 'federation') && (
          <>
            <h3>Bezeichnung der Untereinheiten</h3>
            <p className="muted small">
              {detail.type === 'club'
                ? 'Wie sollen die Untereinheiten heißen? Zum Beispiel Zug, Sparte, Kompanie oder Gruppe.'
                : 'Wie heißen die Einheiten, die zu dieser Einheit gehören? Zum Beispiel Verein oder Gesellschaft.'}
            </p>
            <LabelFields
              preview="children"
              testId="dept-terms-preview"
              value={{
                label: v.department_label,
                plural: v.department_label_plural,
                gender: v.department_label_gender,
                genitive: v.department_label_genitive,
                labelEn: v.department_label_en ?? '',
                pluralEn: v.department_label_plural_en ?? '',
              }}
              errors={{
                label: errors.department_label,
                plural: errors.department_label_plural,
                gender: errors.department_label_gender,
                genitive: errors.department_label_genitive,
              }}
              onChange={(l) => {
                set('department_label', l.label)
                set('department_label_plural', l.plural)
                set('department_label_gender', l.gender)
                set('department_label_genitive', l.genitive)
                set('department_label_en', l.labelEn ?? '')
                set('department_label_plural_en', l.pluralEn ?? '')
              }}
            />
          </>
        )}
        {(detail.can_switch_members || detail.type === 'federation') && (
          <>
            <Checkbox
              label={
                detail.type === 'federation'
                  ? `Führt eigene Mitglieder (z. B. passive Mitglieder ohne Mitgliedschaft in ${preview.einem})`
                  : 'Führt eigene Mitglieder (Mitgliederliste, Mitgliedsarten, Ein- und Austritt)'
              }
              checked={!!v.keeps_members}
              onChange={(val) => set('keeps_members', val)}
            />
            {errors.keeps_members && <Alert kind="error">{errors.keeps_members}</Alert>}
          </>
        )}
        {detail.type === 'club' && (
          <>
            <Checkbox
              label={`Ein Mitglied darf mehreren ${preview.pl_dat} gleichzeitig angehören`}
              checked={v.allow_multiple_departments}
              onChange={(val) => set('allow_multiple_departments', val)}
            />
            <Checkbox
              label={`${preview.pl} arbeiten selbst: Inhaber von Rollen mit Rechten verwalten ihre ${preview.pl}`}
              checked={v.department_access_enabled}
              onChange={(val) => set('department_access_enabled', val)}
            />
          </>
        )}
        {!isPlatform && (
          <>
            <h3>Geschäftsjahr</h3>
            <Why k="fiscal_year" />
            <FiscalYearFields
              month={v.fiscal_start_month}
              day={v.fiscal_start_day}
              error={errors.fiscal_start_month ?? errors.fiscal_start_day}
              onChange={(m, d) => {
                set('fiscal_start_month', m)
                set('fiscal_start_day', d)
              }}
            />
            <p className="muted small">
              Mitgliederbezogene Einstellungen wie Jubiläumsstufen und Zusatzfelder stehen unter
              Mitglieder → Einrichtung.
            </p>
          </>
        )}
      </fieldset>

      {!editable && (
        <p className="muted small">Du kannst diese Angaben ansehen, aber nicht ändern.</p>
      )}
    </form>
  )
}

const EDITABLE: (keyof OrgDetail)[] = [
  'name',
  'short_name',
  'founding_year',
  'street',
  'postal_code',
  'city',
  'country',
  'contact_source',
  'contact_role',
  'contact_email',
  'contact_phone',
  'website',
  'name_gender',
  'name_genitive',
  'label',
  'label_plural',
  'label_gender',
  'label_genitive',
  'label_en',
  'label_plural_en',
  'department_label',
  'department_label_plural',
  'department_label_gender',
  'department_label_genitive',
  'department_label_en',
  'department_label_plural_en',
  'allow_multiple_departments',
  'keeps_members',
  'department_access_enabled',
  'fiscal_start_month',
  'fiscal_start_day',
]

/** Dachverband: wie sein Name in den Texten seiner Vereine erscheint. */
function FederationNameGrammar({
  name,
  gender,
  genitive,
  errors,
  onGender,
  onGenitive,
}: {
  name: string
  gender: 'f' | 'm' | 'n'
  genitive: string
  errors: Record<string, string>
  onGender: (g: 'f' | 'm' | 'n') => void
  onGenitive: (g: string) => void
}) {
  const tm = buildFederationTerms(name, gender, genitive)
  return (
    <>
      <h3>Name in den Texten der Untereinheiten</h3>
      <p className="muted small">
        Die Untereinheiten sehen in ihren Texten den Namen dieser Einheit (Kurzname, falls gesetzt).
        Damit Artikel und Fälle stimmen:
      </p>
      <div className="grid-2">
        <SelectField
          label="Artikel"
          value={gender}
          error={errors.name_gender}
          onChange={(e) => onGender(e.target.value as 'f' | 'm' | 'n')}
        >
          <option value="m">der (z. B. der BSV)</option>
          <option value="f">die (z. B. die Bruderschaft)</option>
          <option value="n">das (z. B. das Korps)</option>
        </SelectField>
        <Field
          label="Genitiv, nur falls abweichend"
          placeholder={name}
          hint="Leer lassen, wenn die Form im Beispiel unten stimmt."
          value={genitive}
          error={errors.name_genitive}
          onChange={(e) => onGenitive(e.target.value)}
        />
      </div>
      <p className="muted small" data-testid="fed-terms-preview">
        So erscheint es: an {tm.dv_akk} melden · Mitglied {tm.dv_im} · Rundschreiben {tm.dv_gen} ·{' '}
        {tm.dv_Vom}
      </p>
    </>
  )
}

function canListRoles(roles: Role[], id: number | null) {
  return id === null || roles.some((r) => r.id === id)
}
