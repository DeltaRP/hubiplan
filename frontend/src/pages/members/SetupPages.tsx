// Mitglieder › Einrichtung: mitgliederbezogene Einstellungen der Organisation
// (Jubiläen und Dauer, Mitgliederbereich und Fotos). Gespeichert wird wie im
// Organisationsformular automatisch, aber nur mit den Feldern dieser Seite.
import type { ReactNode } from 'react'
import { orgApi, PERM } from '../../api/orgs.ts'
import type { OrgDetail } from '../../api/orgs.ts'
import { ListInput } from '../../components/ListField.tsx'
import { parseNumberList } from '../../components/lists.ts'
import { DATE_PRECISION_OPTIONS, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import type { DatePrecision } from '../../components/forms.ts'
import { Alert, Checkbox, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg, useOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'
import { t } from '../../i18n/index.ts'

type Form = ReturnType<typeof useForm<OrgDetail>>

const DURATION_FIELDS: (keyof OrgDetail)[] = [
  'jubilee_years',
  'unit_jubilee_years',
  'date_precision',
  'federation_duration_rule',
]
const PORTAL_FIELDS: (keyof OrgDetail)[] = [
  'member_portal_enabled',
  'contact_changes_need_approval',
  'photo_approval_required',
]

/** Lädt die Organisation und zeigt ein automatisch speicherndes Teilformular. */
function OrgSettingsCard({
  fields,
  title,
  children,
}: {
  fields: (keyof OrgDetail)[]
  title: string
  children: (form: Form, detail: OrgDetail) => ReactNode
}) {
  const org = useActiveOrg()
  const { data, error, setData } = useLoad(() => orgApi.detail(org.id), [org.id])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  return (
    <SettingsForm key={data.id} detail={data} fields={fields} title={title} onSaved={setData}>
      {children}
    </SettingsForm>
  )
}

function SettingsForm({
  detail,
  fields,
  title,
  onSaved,
  children,
}: {
  detail: OrgDetail
  fields: (keyof OrgDetail)[]
  title: string
  onSaved: (d: OrgDetail) => void
  children: (form: Form, detail: OrgDetail) => ReactNode
}) {
  const { can, refresh } = useOrg()
  const editable = can(PERM.orgEdit)
  const form = useForm(detail)
  const auto = useAutoSave(
    form,
    (changes) => {
      const payload = Object.fromEntries(
        fields.filter((key) => key in changes).map((key) => [key, changes[key]]),
      ) as Partial<OrgDetail>
      return orgApi.update(detail.id, payload)
    },
    {
      enabled: editable,
      onSaved: (saved) => {
        onSaved(saved as OrgDetail)
        void refresh()
      },
    },
  )
  return (
    <form className="card card-wide" onSubmit={(e) => e.preventDefault()}>
      {editable && <SaveStatus auto={auto} />}
      <h2>{title}</h2>
      <fieldset disabled={!editable}>{children(form, detail)}</fieldset>
      {!editable && (
        <p className="muted small">{t('Du kannst diese Angaben ansehen, aber nicht ändern.')}</p>
      )}
    </form>
  )
}

/** Jubiläumsstufen, Genauigkeit und (Dachverband) die Regel für die Dauer. */
export function MemberDurationSettings() {
  const tm = useTerms()
  return (
    <OrgSettingsCard fields={DURATION_FIELDS} title={t('Jubiläen und Mitgliedsdauer')}>
      {({ values: v, set, errors }, detail) => (
        <>
          <ListInput
            label={t('Jubiläumsstufen (Jahre, durch Komma getrennt)')}
            value={v.jubilee_years}
            parse={parseNumberList}
            error={errors.jubilee_years}
            onChange={(years) => set('jubilee_years', years)}
          />
          <ListInput
            label={t('Jubiläen {e_gen} und der {pl} (Jahre seit Gründung)', {
              e_gen: tm.e_gen,
              pl: tm.pl,
            })}
            value={v.unit_jubilee_years ?? []}
            parse={parseNumberList}
            error={errors.unit_jubilee_years}
            hint={t(
              'Gezählt wird ab dem Gründungsjahr, jahresgenau (z. B. 100 Jahre im ganzen Jahr).',
            )}
            onChange={(years) => set('unit_jubilee_years', years)}
          />
          <SelectField
            label={t('Genauigkeit für Mitgliedschaften und Jubiläen')}
            value={v.date_precision}
            error={errors.date_precision}
            hint={t(
              'Gilt für die Anzeige von Ein- und Austritt und für die Jubiläen. Gespeichert wird immer tagesgenau. Jahresgenau: Eintritt 2001 ergibt 25 Jahre im ganzen Jahr 2026.',
            )}
            onChange={(e) => set('date_precision', e.target.value as DatePrecision)}
          >
            {DATE_PRECISION_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </SelectField>
          {detail.type === 'federation' && (
            <SelectField
              label={t('Was zählt für die Dauer {e_im}?', { e_im: tm.e_im })}
              value={v.federation_duration_rule}
              error={errors.federation_duration_rule}
              onChange={(e) =>
                set(
                  'federation_duration_rule',
                  e.target.value as OrgDetail['federation_duration_rule'],
                )
              }
            >
              <option value="all_reported">{t('alle gemeldeten Zeiten')}</option>
              <option value="active_reported">{t('nur gemeldete aktive Zeiten')}</option>
            </SelectField>
          )}
        </>
      )}
    </OrgSettingsCard>
  )
}

/** Mitgliederbereich (Anmeldung der Mitglieder), Änderungsmeldungen und Fotos. */
export function MemberPortalSettings() {
  const tm = useTerms()
  return (
    <OrgSettingsCard fields={PORTAL_FIELDS} title={t('Mitgliederbereich und Fotos')}>
      {({ values: v, set }) => (
        <>
          <h3>{t('Zugänge für Mitglieder')}</h3>
          <Checkbox
            label={t(
              'Mitgliederbereich: Mitglieder können sich anmelden, ihre Daten ansehen und Änderungen melden',
            )}
            checked={v.member_portal_enabled}
            onChange={(val) => set('member_portal_enabled', val)}
          />
          <Checkbox
            label={t(
              'Änderungen der Mitglieder an Kontaktdaten und Anschrift erst nach Bestätigung durch {e_akk} übernehmen (sonst gelten sie sofort)',
              { e_akk: tm.e_akk },
            )}
            checked={v.contact_changes_need_approval}
            onChange={(val) => set('contact_changes_need_approval', val)}
          />
          <h3>{t('Mitgliederfotos')}</h3>
          <Checkbox
            label={t(
              'Fotos, die Mitglieder über ihren Upload-Link hochladen, erst nach Freigabe durch den Vorstand anzeigen',
            )}
            checked={v.photo_approval_required}
            onChange={(val) => set('photo_approval_required', val)}
          />
        </>
      )}
    </OrgSettingsCard>
  )
}
