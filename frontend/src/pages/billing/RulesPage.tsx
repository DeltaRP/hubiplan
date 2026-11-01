// Finanzen › Einstellungen: Beitragssätze, Altersstufen, Mahnstufen, Rechnung & Lastschrift.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { billingApi } from '../../api/billing.ts'
import type { BillingSettings, FeeRateRow, Rhythm } from '../../api/billing.ts'
import { euro, parseAmount } from '../../api/finance.ts'
import { errorMessage, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { Alert, Checkbox, Field, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg, useOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'
import { HowTo, Term, Why } from '../../learning/Aids.tsx'
import { locale } from '../../i18n/index.ts'
import { t } from '../../i18n/index.ts'

function useBillingSettings() {
  const org = useActiveOrg()
  const settings = useLoad(() => billingApi.settings(org.id), [org.id])
  return { org, settings }
}

/** Beitragssätze: je Mitgliedsart (Verein) bzw. je gemeldetem Mitglied (Dachverband) und Altersstufen. */
export function FeeRulesPage() {
  const { org, settings } = useBillingSettings()
  if (settings.error) return <Alert kind="error">{settings.error}</Alert>
  if (!settings.data) return <p className="muted">{t('Lädt …')}</p>
  const s = settings.data
  const federation = s.org_type === 'federation'
  return (
    <div className="stack">
      {federation ? (
        <ClubRatesCard
          key={org.id}
          orgId={org.id}
          settings={s}
          onSaved={(d) => settings.setData(d)}
        />
      ) : (
        <FeesCard orgId={org.id} canEdit={s.can_edit} />
      )}
      <AgeRatesCard orgId={org.id} canEdit={s.can_edit} federation={federation} />
    </div>
  )
}

export function DunningLevelsPage() {
  const { org, settings } = useBillingSettings()
  if (settings.error) return <Alert kind="error">{settings.error}</Alert>
  if (!settings.data) return <p className="muted">{t('Lädt …')}</p>
  return <DunningLevelsCard orgId={org.id} canEdit={settings.data.can_edit} />
}

/** Abrechnungsrhythmus, Konto und Kategorie, Rechnungstexte, Umsatzsteuer, SEPA. */
export function BillingSettingsPage() {
  const { org, settings } = useBillingSettings()
  const { refresh } = useOrg()
  if (settings.error) return <Alert kind="error">{settings.error}</Alert>
  if (!settings.data) return <p className="muted">{t('Lädt …')}</p>
  const s = settings.data
  return (
    <SettingsCard
      key={org.id}
      orgId={org.id}
      settings={s}
      onSaved={(d) => {
        settings.setData(d)
        // Menü „Lastschriften“ ein- oder ausblenden
        if (d.sepa_enabled !== s.sepa_enabled) void refresh()
      }}
    />
  )
}

function FeesCard({ orgId, canEdit }: { orgId: number; canEdit: boolean }) {
  const { data, error, setData } = useLoad(() => billingApi.fees(orgId), [orgId])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  return <FeesForm orgId={orgId} rows={data} canEdit={canEdit} onSaved={setData} />
}

function FeesForm({
  orgId,
  rows,
  canEdit,
  onSaved,
}: {
  orgId: number
  rows: FeeRateRow[]
  canEdit: boolean
  onSaved: (rows: FeeRateRow[]) => void
}) {
  const form = useForm<Record<string, string>>(
    Object.fromEntries(
      rows.map((r) => [String(r.member_type), r.amount ? r.amount.replace('.', ',') : '']),
    ),
  )

  const auto = useAutoSave(
    form,
    (_changes, values) =>
      billingApi.saveFees(
        orgId,
        rows.map((r) => {
          const raw = values[String(r.member_type)]?.trim() ?? ''
          return { member_type: r.member_type, amount: raw ? parseAmount(raw) : null }
        }),
      ),
    { enabled: canEdit, onSaved: (result) => onSaved(result as FeeRateRow[]) },
  )

  return (
    <form className="card card-wide" onSubmit={(e) => e.preventDefault()}>
      <h2>{t('Jahresbeitrag je Mitgliedsart')}</h2>
      {canEdit && rows.length > 0 && <SaveStatus auto={auto} />}
      <HowTo k="calc_fee" />
      <p className="muted small">
        {t(
          'Der Betrag gilt für ein ganzes Geschäftsjahr. Bei halbjährlicher, vierteljährlicher oder monatlicher Abrechnung wird er aufgeteilt. Leer heißt beitragsfrei.',
        )}
      </p>
      {rows.length === 0 ? (
        <p className="muted">
          {t('Noch keine Mitgliedsarten. Lege sie zuerst unter')}{' '}
          <Link to="/mitglieder/einrichtung/mitgliedsarten">
            {t('Mitglieder → Einrichtung → Mitgliedsarten')}
          </Link>{' '}
          an.
        </p>
      ) : (
        <div className="grid-3">
          {rows.map((r) => (
            <Field
              key={r.member_type}
              label={t('{name} (€ im Jahr)', { name: r.name })}
              inputMode="decimal"
              disabled={!canEdit}
              placeholder="beitragsfrei"
              value={form.values[String(r.member_type)] ?? ''}
              error={form.errors[String(r.member_type)]}
              onChange={(e) => form.set(String(r.member_type), e.target.value)}
            />
          ))}
        </div>
      )}
    </form>
  )
}

function AgeRatesCard({
  orgId,
  canEdit,
  federation,
}: {
  orgId: number
  canEdit: boolean
  federation: boolean
}) {
  const tm = useTerms()
  const { data, error, reload } = useLoad(() => billingApi.ageRates(orgId), [orgId])
  const types = useLoad(
    () => (federation ? Promise.resolve([]) : billingApi.fees(orgId)),
    [orgId, federation],
  )
  const [message, setMessage] = useState<string | null>(null)
  const form = useForm({
    name: '',
    member_type: '',
    min_age: '',
    max_age: '',
    mode: 'discount',
    value: '',
  })
  const v = form.values

  async function add(e: FormEvent) {
    e.preventDefault()
    const value = parseAmount(v.value)
    const ok = await form.submit(
      () =>
        billingApi.createAgeRate(orgId, {
          name: v.name,
          member_type: v.member_type ? Number(v.member_type) : null,
          min_age: v.min_age ? Number(v.min_age) : null,
          max_age: v.max_age ? Number(v.max_age) : null,
          amount: v.mode === 'amount' ? value : null,
          discount_percent: v.mode === 'discount' ? value : null,
        }),
      t('Altersstufe angelegt.'),
    )
    if (ok) {
      form.setValues({ ...v, name: '', min_age: '', max_age: '', value: '' })
      await reload()
    }
  }

  async function remove(id: number) {
    setMessage(null)
    try {
      await billingApi.deleteAgeRate(orgId, id)
      await reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return null
  return (
    <div className="card card-wide">
      <h2>{t('Altersstufen')}</h2>
      <Why k="age_brackets" />
      <p className="muted small">
        {t('Zum Beispiel Jugend bis 17 Jahre mit halbem Beitrag. Maßgeblich ist das Alter am')}{' '}
        <Term k="cutoff_date">{t('Stichtag')}</Term>
        {t(', dem Beginn des Geschäftsjahres.')}
        {federation
          ? t(' Die Stufe gilt für die gemeldeten Mitglieder der {pl}.', { pl: tm.pl })
          : t(' Eine Stufe für eine bestimmte Mitgliedsart geht einer allgemeinen vor.')}
      </p>
      {data.length === 0 ? (
        <p className="muted">{t('Keine Altersstufen.')}</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>{t('Stufe')}</th>
              <th>{t('Alter')}</th>
              <th>{t('gilt für')}</th>
              <th>{t('Beitrag')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.map((a) => (
              <tr key={a.id}>
                <td>
                  <strong>{a.name}</strong>
                </td>
                <td>
                  {a.min_age !== null && a.max_age !== null
                    ? t('{min_age} bis {max_age} Jahre', { min_age: a.min_age, max_age: a.max_age })
                    : a.max_age !== null
                      ? t('bis {max_age} Jahre', { max_age: a.max_age })
                      : t('ab {min_age} Jahren', { min_age: a.min_age })}
                </td>
                <td>{a.member_type_name ?? t('alle Mitgliedsarten')}</td>
                <td>
                  {a.amount !== null
                    ? t('{x} im Jahr', { x: euro(a.amount) })
                    : t('{x} % Abschlag', {
                        x: Number(a.discount_percent).toLocaleString(locale()),
                      })}
                </td>
                <td className="actions">
                  {canEdit && (
                    <button type="button" className="link-button" onClick={() => void remove(a.id)}>
                      {t('Löschen')}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {message && <Alert kind="error">{message}</Alert>}
      {canEdit && (
        <form className="subcard" onSubmit={add}>
          <h3>{t('Neue Altersstufe')}</h3>
          <div className="grid-3">
            <Field
              label={t('Bezeichnung')}
              required
              placeholder={t('z. B. Jugend')}
              value={v.name}
              error={form.errors.name}
              onChange={(e) => form.set('name', e.target.value)}
            />
            <Field
              label={t('ab Alter')}
              type="number"
              min={0}
              value={v.min_age}
              error={form.errors.min_age}
              onChange={(e) => form.set('min_age', e.target.value)}
            />
            <Field
              label={t('bis Alter (einschließlich)')}
              type="number"
              min={0}
              value={v.max_age}
              error={form.errors.max_age}
              onChange={(e) => form.set('max_age', e.target.value)}
            />
            {!federation && (
              <SelectField
                label={t('gilt für')}
                value={v.member_type}
                onChange={(e) => form.set('member_type', e.target.value)}
              >
                <option value="">{t('alle Mitgliedsarten')}</option>
                {(types.data ?? []).map((t) => (
                  <option key={t.member_type} value={t.member_type}>
                    {t.name}
                  </option>
                ))}
              </SelectField>
            )}
            <SelectField
              label={t('Beitrag')}
              value={v.mode}
              onChange={(e) => form.set('mode', e.target.value)}
            >
              <option value="discount">{t('Abschlag in Prozent')}</option>
              <option value="amount">
                {federation
                  ? t('eigener Betrag je Mitglied in €')
                  : t('eigener Jahresbeitrag in €')}
              </option>
            </SelectField>
            <Field
              label={v.mode === 'discount' ? t('Abschlag (%)') : t('Jahresbeitrag (€)')}
              inputMode="decimal"
              required
              value={v.value}
              error={form.errors.amount ?? form.errors.discount_percent}
              onChange={(e) => form.set('value', e.target.value)}
            />
          </div>
          {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
          <button type="submit" className="button button-primary" disabled={form.busy}>
            {t('Anlegen')}
          </button>
        </form>
      )}
    </div>
  )
}

function SettingsCard({
  orgId,
  settings,
  onSaved,
}: {
  orgId: number
  settings: BillingSettings
  onSaved: (s: BillingSettings) => void
}) {
  const form = useForm({
    rhythm: settings.rhythm,
    due_days: String(settings.due_days),
    pro_rata: settings.pro_rata,
    account: settings.account ? String(settings.account) : '',
    category: settings.category ? String(settings.category) : '',
    intro_text: settings.intro_text,
    footer_text: settings.footer_text,
    qr_code: settings.qr_code,
    vat_enabled: settings.vat_enabled,
    vat_rate: settings.vat_rate.replace('.', ','),
    tax_number: settings.tax_number,
    sepa_enabled: settings.sepa_enabled,
    creditor_id: settings.creditor_id,
    prenotification_days: String(settings.prenotification_days),
  })
  const v = form.values
  const canEdit = settings.can_edit

  const auto = useAutoSave(
    form,
    (_changes, values) =>
      billingApi.updateSettings(orgId, {
        ...values,
        due_days: Number(values.due_days) || 0,
        account: values.account ? Number(values.account) : null,
        category: values.category ? Number(values.category) : null,
        vat_rate: parseAmount(values.vat_rate) || '19',
        prenotification_days: Number(values.prenotification_days) || 14,
      }),
    { enabled: canEdit, onSaved: (result) => onSaved(result as BillingSettings) },
  )

  return (
    <form className="card card-wide" onSubmit={(e) => e.preventDefault()}>
      <h2>{t('Abrechnung und Rechnung')}</h2>
      {canEdit && <SaveStatus auto={auto} />}
      <div className="aid-row">
        <Why k="billing_cycle" />
        <Why k="due_days" />
        <Why k="pro_rata" />
        <Why k="giro_qr" />
      </div>
      <fieldset disabled={!canEdit}>
        <div className="grid-3">
          <SelectField
            label={t('Abrechnungsrhythmus')}
            value={v.rhythm}
            onChange={(e) => form.set('rhythm', e.target.value as Rhythm)}
          >
            {settings.rhythms.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </SelectField>
          <Field
            label={t('Zahlungsziel (Tage)')}
            type="number"
            min={0}
            value={v.due_days}
            error={form.errors.due_days}
            onChange={(e) => form.set('due_days', e.target.value)}
          />
          <div className="field">
            <span>&nbsp;</span>
            <Checkbox
              label={t('Eintritt im laufenden Zeitraum anteilig je angefangenem Monat')}
              checked={v.pro_rata}
              onChange={(val) => form.set('pro_rata', val)}
            />
          </div>
          <SelectField
            label={t('Konto für Überweisungen')}
            value={v.account}
            error={form.errors.account}
            hint={t('steht mit IBAN auf der Rechnung')}
            onChange={(e) => form.set('account', e.target.value)}
          >
            <option value="">{t('kein Konto')}</option>
            {settings.accounts
              .filter((a) => a.kind !== 'cash')
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                  {a.has_iban ? '' : ' (ohne IBAN)'}
                </option>
              ))}
          </SelectField>
          <SelectField
            label={t('Kategorie für Zahlungseingänge')}
            value={v.category}
            error={form.errors.category}
            hint={t('Zahlungen werden damit in der Kasse gebucht')}
            onChange={(e) => form.set('category', e.target.value)}
          >
            <option value="">{t('bitte wählen')}</option>
            {settings.categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </SelectField>
          <div className="field">
            <span>&nbsp;</span>
            <Checkbox
              label={t('QR-Code für die Banking-App aufdrucken')}
              checked={v.qr_code}
              onChange={(val) => form.set('qr_code', val)}
            />
          </div>
        </div>
        {settings.accounts.length === 0 && (
          <p className="muted small">
            {t('Konten und Kategorien legst du unter')}{' '}
            <Link to="/finanzen/einstellungen/konten">{t('Einrichtung › Konten')}</Link> an.
          </p>
        )}
        {/* Im Arbeitsbereich einer Untereinheit gibt es keine Lastschrift */}
        {settings.org_type !== 'unit' && (
          <>
            <h3>{t('SEPA-Lastschrift')}</h3>
            <div className="aid-row">
              <Why k="sepa_use" />
              {v.sepa_enabled && <Why k="prenotification" />}
            </div>
            <Checkbox
              label={t(
                'SEPA-Lastschrift nutzen (Mandate, Lastschriftläufe, Mandat im Mitgliederbereich)',
              )}
              checked={v.sepa_enabled}
              onChange={(val) => form.set('sepa_enabled', val)}
            />
            {v.sepa_enabled && (
              <div className="grid-3">
                <Field
                  label={t('Gläubiger-Identifikationsnummer')}
                  placeholder={t('z. B. DE98ZZZ09999999999')}
                  value={v.creditor_id}
                  error={form.errors.creditor_id}
                  hint={t('bei der Bundesbank beantragt')}
                  onChange={(e) => form.set('creditor_id', e.target.value)}
                />
                <Field
                  label={t('Vorabankündigung (Tage vor dem Einzug)')}
                  type="number"
                  min={1}
                  max={30}
                  value={v.prenotification_days}
                  error={form.errors.prenotification_days}
                  onChange={(e) => form.set('prenotification_days', e.target.value)}
                />
              </div>
            )}
            <p className="muted small">
              {v.sepa_enabled
                ? t(
                    'Eingezogen wird auf das Konto für Überweisungen oben. Ohne Gläubiger-ID ist keine Lastschrift möglich.',
                  )
                : t(
                    'Ausgeschaltet erscheinen Lastschriften und Mandate nirgends in der Oberfläche. Bereits erfasste Mandate bleiben gespeichert.',
                  )}
            </p>
          </>
        )}
        <h3>{t('Umsatzsteuer')}</h3>
        <Why k="vat_show" />
        <div className="grid-3">
          <div className="field">
            <span>&nbsp;</span>
            <Checkbox
              label={t('Umsatzsteuer auf Rechnungen ausweisen (nur für steuerpflichtige Posten)')}
              checked={v.vat_enabled}
              onChange={(val) => form.set('vat_enabled', val)}
            />
          </div>
          {v.vat_enabled && (
            <>
              <Field
                label={t('üblicher Steuersatz (%)')}
                inputMode="decimal"
                value={v.vat_rate}
                error={form.errors.vat_rate}
                onChange={(e) => form.set('vat_rate', e.target.value)}
              />
              <Field
                label={t('Steuernummer oder USt-IdNr.')}
                value={v.tax_number}
                error={form.errors.tax_number}
                onChange={(e) => form.set('tax_number', e.target.value)}
              />
            </>
          )}
        </div>
        <p className="muted small">
          {t(
            'Mitgliedsbeiträge sind nicht steuerbar. Den Steuersatz wählst du je Posten, etwa für Verkäufe im wirtschaftlichen Geschäftsbetrieb. Die Beträge sind Bruttobeträge.',
          )}
        </p>
        <div className="grid-2">
          <label className="field">
            <span>{t('Text vor den Posten')}</span>
            <textarea
              rows={3}
              value={v.intro_text}
              onChange={(e) => form.set('intro_text', e.target.value)}
            />
          </label>
          <label className="field">
            <span>{t('Text unter der Rechnung')}</span>
            <textarea
              rows={3}
              placeholder={t('z. B. Vereinsregister, Steuernummer, Dank')}
              value={v.footer_text}
              onChange={(e) => form.set('footer_text', e.target.value)}
            />
          </label>
        </div>
      </fieldset>
    </form>
  )
}

function ClubRatesCard({
  orgId,
  settings,
  onSaved,
}: {
  orgId: number
  settings: BillingSettings
  onSaved: (s: BillingSettings) => void
}) {
  const tm = useTerms()
  const show = (x: string | null) => (x ? x.replace('.', ',') : '')
  const form = useForm({
    club_rate_active: show(settings.club_rate_active),
    club_rate_passive: show(settings.club_rate_passive),
    club_base_amount: show(settings.club_base_amount),
  })
  const v = form.values
  const canEdit = settings.can_edit

  const auto = useAutoSave(
    form,
    (changes) =>
      billingApi.updateSettings(
        orgId,
        Object.fromEntries(Object.entries(changes).map(([k, x]) => [k, x ? parseAmount(x) : null])),
      ),
    { enabled: canEdit, onSaved: (result) => onSaved(result as BillingSettings) },
  )

  return (
    <form className="card card-wide" onSubmit={(e) => e.preventDefault()}>
      <h2>
        {t('Verbandsbeitrag der')} {tm.pl}
      </h2>
      {canEdit && <SaveStatus auto={auto} />}
      <HowTo k="calc_federation_fee" />
      <p className="muted small">
        {t(
          'Jahresbetrag je gemeldetem Mitglied. Gezählt werden die Mitglieder, deren Mitgliedsart an {e_akk} gemeldet wird, am ersten Tag des Abrechnungszeitraums. Leer heißt kein Beitrag.',
          { e_akk: tm.e_akk },
        )}
      </p>
      <fieldset disabled={!canEdit}>
        <div className="grid-3">
          <Field
            label={t('je aktivem Mitglied (€ im Jahr)')}
            inputMode="decimal"
            value={v.club_rate_active}
            error={form.errors.club_rate_active}
            onChange={(e) => form.set('club_rate_active', e.target.value)}
          />
          <Field
            label={t('je passivem Mitglied (€ im Jahr)')}
            inputMode="decimal"
            value={v.club_rate_passive}
            error={form.errors.club_rate_passive}
            onChange={(e) => form.set('club_rate_passive', e.target.value)}
          />
          <Field
            label={t('Grundbetrag je {sg} (€ im Jahr)', { sg: tm.sg })}
            inputMode="decimal"
            value={v.club_base_amount}
            error={form.errors.club_base_amount}
            onChange={(e) => form.set('club_base_amount', e.target.value)}
          />
        </div>
      </fieldset>
    </form>
  )
}

function DunningLevelsCard({ orgId, canEdit }: { orgId: number; canEdit: boolean }) {
  const { data, error, reload } = useLoad(() => billingApi.dunningLevels(orgId), [orgId])
  const [message, setMessage] = useState<string | null>(null)
  const form = useForm({ name: '', days: '14', fee: '', text: '' })
  const v = form.values

  async function add(e: FormEvent) {
    e.preventDefault()
    const next = Math.max(0, ...(data ?? []).map((d) => d.level)) + 1
    const ok = await form.submit(
      () =>
        billingApi.createDunningLevel(orgId, {
          level: next,
          name: v.name,
          days: Number(v.days) || 0,
          fee: parseAmount(v.fee) || '0',
          text: v.text,
        }),
      t('Mahnstufe angelegt.'),
    )
    if (ok) {
      form.setValues({ name: '', days: String((Number(v.days) || 0) + 14), fee: '', text: '' })
      await reload()
    }
  }

  async function remove(id: number) {
    setMessage(null)
    try {
      await billingApi.deleteDunningLevel(orgId, id)
      await reload()
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return null
  return (
    <div className="card card-wide">
      <h2>
        <Term k="dunning_level">{t('Mahnstufen')}</Term>
      </h2>
      <div className="aid-row">
        <Why k="dunning_levels" />
        <HowTo k="calc_dunning" />
      </div>
      <p className="muted small">
        {t(
          'Zum Beispiel Zahlungserinnerung 14 Tage nach Fälligkeit, 1. Mahnung nach 28 Tagen mit 5 € Gebühr. Fällige Mahnungen erscheinen unter Mahnungen.',
        )}
      </p>
      {data.length === 0 ? (
        <p className="muted">{t('Keine Mahnstufen.')}</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>{t('Stufe')}</th>
              <th>{t('fällig nach')}</th>
              <th className="num">{t('Gebühr')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.id}>
                <td>
                  <strong>
                    {d.level}. {d.name}
                  </strong>
                </td>
                <td>
                  {d.days} {t('Tagen über Fälligkeit')}
                </td>
                <td className="num">{Number(d.fee) ? euro(d.fee) : '–'}</td>
                <td className="actions">
                  {canEdit && (
                    <button type="button" className="link-button" onClick={() => void remove(d.id)}>
                      {t('Löschen')}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {message && <Alert kind="error">{message}</Alert>}
      {canEdit && (
        <form className="subcard" onSubmit={add}>
          <h3>{t('Neue Mahnstufe')}</h3>
          <div className="grid-3">
            <Field
              label={t('Bezeichnung')}
              required
              placeholder={t('z. B. Zahlungserinnerung')}
              value={v.name}
              error={form.errors.name}
              onChange={(e) => form.set('name', e.target.value)}
            />
            <Field
              label={t('Tage nach Fälligkeit')}
              type="number"
              min={0}
              value={v.days}
              error={form.errors.days}
              onChange={(e) => form.set('days', e.target.value)}
            />
            <Field
              label={t('Gebühr (€, optional)')}
              inputMode="decimal"
              value={v.fee}
              error={form.errors.fee}
              onChange={(e) => form.set('fee', e.target.value)}
            />
          </div>
          <label className="field">
            <span>{t('Text im Schreiben (optional)')}</span>
            <textarea
              rows={3}
              placeholder={t('leer = Standardtext')}
              value={v.text}
              onChange={(e) => form.set('text', e.target.value)}
            />
          </label>
          {form.message && <Alert kind={form.message.kind}>{form.message.text}</Alert>}
          <button type="submit" className="button button-primary" disabled={form.busy}>
            {t('Anlegen')}
          </button>
        </form>
      )}
    </div>
  )
}
