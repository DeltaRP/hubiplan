// Kasse: Konten und Kategorien verwalten.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../../api/client.ts'
import { euro, financeApi, parseAmount } from '../../api/finance.ts'
import type { Account, Category, CategoryUsage, FinanceSettings } from '../../api/finance.ts'
import { PERM } from '../../api/orgs.ts'
import { errorMessage, formatDate, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { Alert, Checkbox, Field, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg, useOrg } from '../../org/OrgContext.tsx'
import { confirmDialog } from '../../components/dialog.ts'
import { Term, Why } from '../../learning/Aids.tsx'
import { t } from '../../i18n/index.ts'

/** Aktuelles Jahr, beim Öffnen eines Formulars ermittelt (nicht beim Laden der Seite). */
function thisYear() {
  return new Date().getFullYear()
}

const KIND_LABEL = { bank: t('Bankkonto'), cash: t('Barkasse'), savings: t('Sparkonto') }

export function AccountsPage() {
  const org = useActiveOrg()
  const { refresh } = useOrg()
  const canEdit = org.permissions.includes(PERM.financeEdit)
  const [switchError, setSwitchError] = useState<string | null>(null)
  const settings = useLoad(() => financeApi.settings(org.id), [org.id])
  const datevOn = !!settings.data?.datev_enabled
  const { data, error, reload } = useLoad(() => financeApi.accounts(org.id), [org.id])
  const [editing, setEditing] = useState<Account | 'new' | null>(null)

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>{t('Konten')}</h2>
        {canEdit && editing === null && (
          <button
            type="button"
            className="button button-ghost push-right"
            onClick={() => setEditing('new')}
          >
            {t('Neues Konto')}
          </button>
        )}
      </div>
      <p className="muted small">
        {t(
          'Bankkonten, Barkassen und Sparkonten – von jeder Art beliebig viele. Der Anfangsbestand gilt zum Stichtag; Buchungen davor sind nicht möglich.',
        )}
      </p>
      {editing !== null && (
        <AccountForm
          // Je Objekt ein eigenes Formular: Werte und Autospeichern wechseln nie das Ziel
          key={editing === 'new' ? 'new' : editing.id}
          orgId={org.id}
          account={editing === 'new' ? null : editing}
          datev={datevOn}
          onDone={async () => {
            setEditing(null)
            await reload()
          }}
          onCancel={() => setEditing(null)}
        />
      )}
      {data.length === 0 ? (
        <p className="muted">{t('Noch keine Konten.')}</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>{t('Konto')}</th>
              <th>
                <Term k="opening_balance_term">{t('Anfangsbestand')}</Term>
              </th>
              <th className="num">{t('Bestand heute')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.map((a) => (
              <tr key={a.id} className={a.is_active ? undefined : 'muted'}>
                <td>
                  <strong>{a.name}</strong>
                  <div className="muted small">
                    {a.kind_label}
                    {a.iban && t(' · {x}', { x: a.iban.replace(/(.{4})/g, '$1 ').trim() })}
                    {!a.is_active && t(' · inaktiv')}
                  </div>
                </td>
                <td>
                  {euro(a.opening_balance)}
                  <div className="muted small">zum {formatDate(a.opening_date)}</div>
                </td>
                <td className="num">
                  <strong>{euro(a.balance)}</strong>
                  {a.planned_balance !== null && (
                    <div className="muted small">
                      {t('mit vorgemerkten Buchungen')} {euro(a.planned_balance)}
                    </div>
                  )}
                </td>
                <td className="actions">
                  {canEdit && (
                    <button type="button" className="link-button" onClick={() => setEditing(a)}>
                      {t('Bearbeiten')}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {canEdit && (
        <>
          <Checkbox
            label={t('Zählprotokoll und Kassenbericht für Feste nutzen')}
            checked={!!org.cash_counts_enabled}
            onChange={(on) =>
              void (async () => {
                setSwitchError(null)
                try {
                  await financeApi.updateSettings(org.id, { cash_counts_enabled: on })
                  await refresh()
                } catch (err) {
                  setSwitchError(errorMessage(err))
                }
              })()
            }
          />
          <p className="muted small">
            {t(
              'Zählprotokoll: Bargeld nach Scheinen und Münzen zählen und mit dem Kassenbuch vergleichen. Kassenbericht: Tageseinnahme einer offenen Kasse, etwa beim Getränkeverkauf am Fest, aus Anfangs- und Endbestand ermitteln und buchen.',
            )}
          </p>
          <Checkbox
            label={t('Rücklagen führen')}
            checked={!!org.reserves_enabled}
            onChange={(on) =>
              void (async () => {
                setSwitchError(null)
                try {
                  await financeApi.updateSettings(org.id, { reserves_enabled: on })
                  await refresh()
                } catch (err) {
                  setSwitchError(errorMessage(err))
                }
              })()
            }
          />
          <p className="muted small">
            {t(
              'Rücklagen nach § 62 AO binden einen Teil der Mittel für einen Zweck, etwa das nächste Schützenfest oder ein neues Zelt. Es wird kein Geld bewegt.',
            )}
          </p>
          {switchError && <Alert kind="error">{switchError}</Alert>}
          {settings.data && (
            <DatevSettings
              orgId={org.id}
              settings={settings.data}
              onChange={(next) => settings.setData(next)}
            />
          )}
        </>
      )}
    </div>
  )
}

function AccountForm({
  orgId,
  account,
  datev,
  onDone,
  onCancel,
}: {
  orgId: number
  account: Account | null
  /** DATEV-Export eingeschaltet: Feld für das Finanzkonto zeigen */
  datev: boolean
  onDone: () => void
  onCancel: () => void
}) {
  const form = useForm({
    name: account?.name ?? '',
    kind: account?.kind ?? 'bank',
    iban: account?.iban ?? '',
    bic: account?.bic ?? '',
    bank_name: account?.bank_name ?? '',
    opening_balance: account ? account.opening_balance.replace('.', ',') : '0,00',
    opening_date: account?.opening_date ?? `${thisYear()}-01-01`,
    is_active: account?.is_active ?? true,
    datev_account: account?.datev_account ?? '',
  })
  const { values: v, errors, set } = form

  // Bestehende Konten speichern automatisch, neue erst mit „Anlegen“
  const auto = useAutoSave(
    form,
    (changes) =>
      financeApi.updateAccount(orgId, account!.id, {
        ...changes,
        ...('opening_balance' in changes
          ? { opening_balance: parseAmount(changes.opening_balance ?? '') || '0' }
          : {}),
      }),
    { enabled: account !== null },
  )

  async function save(e: FormEvent) {
    e.preventDefault()
    if (account) {
      if (!(await auto.flush())) return
      onDone()
      return
    }
    const payload = { ...v, opening_balance: parseAmount(v.opening_balance) || '0' }
    const ok = await form.submit(() => financeApi.createAccount(orgId, payload))
    if (ok) onDone()
  }

  async function remove() {
    if (
      !account ||
      !(await confirmDialog({
        title: t('Konto „{name}“ löschen?', { name: account.name }),
        confirmLabel: t('Löschen'),
      }))
    )
      return
    const ok = await form.submit(() => financeApi.deleteAccount(orgId, account.id))
    if (ok !== undefined) onDone()
  }

  return (
    <form className="subcard" onSubmit={save}>
      <h3>{account ? t('Konto „{name}“', { name: account.name }) : t('Neues Konto')}</h3>
      {account && <SaveStatus auto={auto} />}
      <div className="grid-3">
        <Field
          label={t('Name')}
          required
          value={v.name}
          error={errors.name}
          onChange={(e) => set('name', e.target.value)}
        />
        <SelectField
          label={t('Art')}
          value={v.kind}
          onChange={(e) => set('kind', e.target.value as Account['kind'])}
        >
          {Object.entries(KIND_LABEL).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </SelectField>
        <Field
          label={t('Bank')}
          value={v.bank_name}
          error={errors.bank_name}
          onChange={(e) => set('bank_name', e.target.value)}
        />
      </div>
      {v.kind !== 'cash' && (
        <div className="grid-2">
          <Field
            label="IBAN"
            value={v.iban}
            error={errors.iban}
            onChange={(e) => set('iban', e.target.value)}
          />
          <Field
            label="BIC"
            value={v.bic}
            error={errors.bic}
            onChange={(e) => set('bic', e.target.value)}
          />
        </div>
      )}
      <div className="grid-3">
        <Field
          label={t('Anfangsbestand (€)')}
          inputMode="decimal"
          value={v.opening_balance}
          error={errors.opening_balance}
          onChange={(e) => set('opening_balance', e.target.value)}
        />
        <Field
          label={t('zum Stichtag')}
          type="date"
          required
          value={v.opening_date}
          error={errors.opening_date}
          onChange={(e) => set('opening_date', e.target.value)}
        />
        {datev && (
          <Field
            label={t('DATEV-Konto')}
            inputMode="numeric"
            placeholder={v.kind === 'cash' ? t('z. B. 1000') : t('z. B. 1200')}
            value={v.datev_account}
            error={errors.datev_account}
            onChange={(e) => set('datev_account', e.target.value)}
          />
        )}
      </div>
      <Why k="opening_balance" />
      <div className="grid-3">
        {account && (
          <div className="field">
            <span>&nbsp;</span>
            <Checkbox
              label="aktiv"
              checked={v.is_active}
              onChange={(val) => set('is_active', val)}
            />
          </div>
        )}
      </div>
      {form.message?.kind === 'error' && <Alert kind="error">{form.message.text}</Alert>}
      <div className="button-row">
        <button
          type="submit"
          className={account ? 'button button-ghost' : 'button button-primary'}
          disabled={form.busy}
        >
          {account ? t('Schließen') : t('Anlegen')}
        </button>
        {!account && (
          <button type="button" className="button button-ghost" onClick={onCancel}>
            {t('Abbrechen')}
          </button>
        )}
        {account && (
          <button type="button" className="button button-danger push-right" onClick={remove}>
            {t('Löschen')}
          </button>
        )}
      </div>
    </form>
  )
}

const CATEGORY_KIND = {
  both: t('Einnahmen und Ausgaben'),
  income: t('nur Einnahmen'),
  expense: t('nur Ausgaben'),
}

export function CategoriesPage() {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.financeEdit)
  const { data, error, reload } = useLoad(() => financeApi.categories(org.id), [org.id])
  const settings = useLoad(() => financeApi.settings(org.id), [org.id])
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)
  const [removing, setRemoving] = useState<{ category: Category; usage: CategoryUsage } | null>(
    null,
  )
  const [busy, setBusy] = useState(false)
  const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null)
  const form = useForm({ name: '', kind: 'both', tax_area: '' })

  if (error ?? settings.error) return <Alert kind="error">{error ?? settings.error}</Alert>
  if (!data || !settings.data) return <p className="muted">{t('Lädt …')}</p>
  const areas = settings.data.tax_areas_enabled ? settings.data.tax_areas : []
  const datevOn = !!settings.data.datev_enabled
  const current = data.filter((c) => c.is_active)
  const archived = data.filter((c) => !c.is_active)

  async function run(action: () => Promise<unknown>, success?: string) {
    setMessage(null)
    setBusy(true)
    try {
      await action()
      setRemoving(null)
      setRenaming(null)
      if (success) setMessage({ kind: 'success', text: success })
      await reload()
    } catch (err) {
      const text =
        err instanceof ApiError ? (Object.values(err.fieldErrors)[0] ?? err.message) : null
      setMessage({ kind: 'error', text: text ?? errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  async function askRemove(category: Category) {
    setMessage(null)
    try {
      setRemoving({ category, usage: await financeApi.categoryUsage(org.id, category.id) })
    } catch (err) {
      setMessage({ kind: 'error', text: errorMessage(err) })
    }
  }

  function confirmRemove() {
    if (!removing) return
    const { category, usage } = removing
    if (usage.deletable) {
      void run(
        () => financeApi.deleteCategory(org.id, category.id),
        t('„{name}“ wurde gelöscht.', { name: category.name }),
      )
    } else {
      void run(
        () => financeApi.archiveCategory(org.id, category.id),
        t('„{name}“ wurde archiviert.', { name: category.name }),
      )
    }
  }

  async function add(e: FormEvent) {
    e.preventDefault()
    const ok = await form.submit(
      () => financeApi.createCategory(org.id, form.values as Partial<Category>),
      t('Kategorie angelegt.'),
    )
    if (ok) {
      form.setValues({ name: '', kind: form.values.kind, tax_area: form.values.tax_area })
      await reload()
    }
  }

  return (
    <div className="card card-wide">
      <h2>{t('Kategorien')}</h2>
      <p className="muted small">
        {t(
          'Kategorien ordnen Einnahmen und Ausgaben, zum Beispiel Beiträge, Schützenfest, Getränke oder Saalmiete.',
        )}
        {areas.length > 0 && t(' Jede Kategorie gehört zu einem steuerlichen Bereich.')}
      </p>
      {canEdit && (
        <>
          <Checkbox
            label={t(
              'Kategorien den vier steuerlichen Bereichen zuordnen (ideeller Bereich, Vermögensverwaltung, Zweckbetrieb, wirtschaftlicher Geschäftsbetrieb)',
            )}
            checked={settings.data.tax_areas_enabled}
            onChange={(on) =>
              void run(async () => {
                settings.setData(await financeApi.updateSettings(org.id, { tax_areas_enabled: on }))
              })
            }
          />
          <p className="muted small">
            {t(
              'Ob die Kasse so unterteilt werden muss, entscheidet ihr selbst, zum Beispiel mit eurem Steuerberater. Name und Bereich einer Kategorie werden beim Jahresabschluss festgehalten: Spätere Änderungen gelten nur für noch offene Geschäftsjahre.',
            )}
          </p>
          <Why k="tax_areas" />
        </>
      )}
      {removing && (
        <div className="subcard" role="dialog" aria-label={t('Kategorie entfernen')}>
          {removing.usage.deletable ? (
            <p>
              {t('„{name}“ wird nirgends verwendet und wird', { name: removing.category.name })}{' '}
              <strong>{t('gelöscht')}</strong>.
            </p>
          ) : (
            <>
              <p>
                {t('„{name}“ wird noch verwendet und wird deshalb', {
                  name: removing.category.name,
                })}{' '}
                <strong>archiviert</strong> {t('statt gelöscht:')}
              </p>
              <ul>
                {removing.usage.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
              <p className="muted small">
                {t(
                  'Archivierte Kategorien stehen für neue Buchungen nicht mehr zur Auswahl. Bestehende Buchungen und Kassenberichte bleiben unverändert, und die Kategorie lässt sich jederzeit wiederherstellen.',
                )}
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
              {removing.usage.deletable ? t('Löschen') : t('Archivieren')}
            </button>
            <button type="button" className="button button-ghost" onClick={() => setRemoving(null)}>
              {t('Abbrechen')}
            </button>
          </div>
        </div>
      )}
      {message && <Alert kind={message.kind}>{message.text}</Alert>}
      {current.length === 0 ? (
        <p className="muted">{t('Noch keine Kategorien.')}</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>{t('Kategorie')}</th>
              <th>{t('gilt für')}</th>
              {areas.length > 0 && <th>{t('steuerlicher Bereich')}</th>}
              {org.donations_enabled && <th>{t('Spenden')}</th>}
              {datevOn && <th>{t('DATEV-Konto')}</th>}
              <th className="num">{t('Buchungen')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {current.map((c) => (
              <tr key={c.id}>
                <td>
                  {renaming?.id === c.id ? (
                    <CategoryRename
                      orgId={org.id}
                      category={c}
                      onDone={(name) =>
                        void run(
                          async () => {},
                          name !== c.name
                            ? t('„{name}“ heißt jetzt „{name2}“.', { name: c.name, name2: name })
                            : undefined,
                        )
                      }
                    />
                  ) : (
                    <strong>{c.name}</strong>
                  )}
                </td>
                <td>
                  {canEdit ? (
                    <select
                      aria-label={t('{name}: gilt für', { name: c.name })}
                      value={c.kind}
                      onChange={(e) =>
                        void run(() =>
                          financeApi.updateCategory(org.id, c.id, {
                            kind: e.target.value as Category['kind'],
                          }),
                        )
                      }
                    >
                      {Object.entries(CATEGORY_KIND).map(([k, label]) => (
                        <option key={k} value={k}>
                          {label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    c.kind_label
                  )}
                </td>
                {areas.length > 0 && (
                  <td>
                    {canEdit ? (
                      <select
                        aria-label={t('{name}: steuerlicher Bereich', { name: c.name })}
                        value={c.tax_area}
                        onChange={(e) =>
                          void run(() =>
                            financeApi.updateCategory(org.id, c.id, { tax_area: e.target.value }),
                          )
                        }
                      >
                        <option value="">{t('ohne Zuordnung')}</option>
                        {areas.map((a) => (
                          <option key={a.value} value={a.value}>
                            {a.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      c.tax_area_label || '–'
                    )}
                  </td>
                )}
                {org.donations_enabled && (
                  <td>
                    {c.kind !== 'expense' && (
                      <input
                        type="checkbox"
                        aria-label={t('{name}: Spenden (Zuwendungsbestätigung möglich)', {
                          name: c.name,
                        })}
                        title={t('Einnahmen lassen sich unter Zuwendungsbestätigungen übernehmen')}
                        checked={c.donations}
                        disabled={!canEdit}
                        onChange={(e) =>
                          void run(() =>
                            financeApi.updateCategory(org.id, c.id, {
                              donations: e.target.checked,
                            }),
                          )
                        }
                      />
                    )}
                  </td>
                )}
                {datevOn && (
                  <td>
                    {canEdit ? (
                      <input
                        size={8}
                        inputMode="numeric"
                        aria-label={t('{name}: DATEV-Konto', { name: c.name })}
                        defaultValue={c.datev_account ?? ''}
                        onBlur={(e) => {
                          const value = e.target.value.trim()
                          if (value !== (c.datev_account ?? ''))
                            void run(() =>
                              financeApi.updateCategory(org.id, c.id, { datev_account: value }),
                            )
                        }}
                      />
                    ) : (
                      c.datev_account || '–'
                    )}
                  </td>
                )}
                <td className="num">{c.booking_count}</td>
                <td className="actions">
                  {canEdit && (
                    <>
                      <button
                        type="button"
                        className="link-button"
                        aria-label={t('{name} umbenennen', { name: c.name })}
                        onClick={() => {
                          setMessage(null)
                          setRenaming({ id: c.id, name: c.name })
                        }}
                      >
                        {t('Umbenennen')}
                      </button>{' '}
                      <button
                        type="button"
                        className="link-button"
                        aria-label={t('{name} löschen', { name: c.name })}
                        onClick={() => void askRemove(c)}
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
          <h3>{t('Archivierte Kategorien')}</h3>
          <p className="muted small">
            {t(
              'Nicht mehr für neue Buchungen wählbar, in Buchungen, Filtern und Kassenberichten weiter sichtbar.',
            )}
          </p>
          <ul className="role-list">
            {archived.map((c) => (
              <li key={c.id} className="role-row">
                <strong>{c.name}</strong>
                <span className="muted small">
                  {c.booking_count} {c.booking_count === 1 ? t('Buchung') : t('Buchungen')}
                </span>
                {canEdit && (
                  <button
                    type="button"
                    className="button button-ghost push-right"
                    disabled={busy}
                    aria-label={t('{name} wiederherstellen', { name: c.name })}
                    onClick={() =>
                      void run(
                        () => financeApi.restoreCategory(org.id, c.id),
                        t('„{name}“ ist wieder verfügbar.', { name: c.name }),
                      )
                    }
                  >
                    {t('Wiederherstellen')}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {canEdit && (
        <form className="subcard" onSubmit={add}>
          <h3>{t('Neue Kategorie')}</h3>
          <div className="grid-3">
            <Field
              label={t('Name')}
              required
              value={form.values.name}
              error={form.errors.name}
              onChange={(e) => form.set('name', e.target.value)}
            />
            <SelectField
              label={t('gilt für')}
              value={form.values.kind}
              onChange={(e) => form.set('kind', e.target.value)}
            >
              {Object.entries(CATEGORY_KIND).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </SelectField>
            {areas.length > 0 && (
              <SelectField
                label={t('steuerlicher Bereich')}
                value={form.values.tax_area}
                onChange={(e) => form.set('tax_area', e.target.value)}
              >
                <option value="">{t('ohne Zuordnung')}</option>
                {areas.map((a) => (
                  <option key={a.value} value={a.value}>
                    {a.label}
                  </option>
                ))}
              </SelectField>
            )}
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

/** Kategorie umbenennen; der Name speichert automatisch, „Schließen“ wartet darauf und schließt. */
function CategoryRename({
  orgId,
  category,
  onDone,
}: {
  orgId: number
  category: Category
  onDone: (name: string) => void
}) {
  const form = useForm({ name: category.name })
  const auto = useAutoSave(form, (changes) =>
    financeApi.updateCategory(orgId, category.id, { name: changes.name?.trim() }),
  )
  return (
    <form
      className="inline-edit"
      onSubmit={(e) => {
        e.preventDefault()
        void auto.flush().then((ok) => {
          if (ok) onDone(form.values.name.trim())
        })
      }}
    >
      <input
        aria-label={t('Neuer Name für {name}', { name: category.name })}
        value={form.values.name}
        maxLength={100}
        autoFocus
        onChange={(e) => form.set('name', e.target.value)}
      />
      <button type="submit" className="link-button">
        {t('Schließen')}
      </button>
      {auto.state !== 'idle' && <SaveStatus auto={auto} />}
      {form.errors.name && <Alert kind="error">{form.errors.name}</Alert>}
    </form>
  )
}

/** DATEV-Export für die Steuerberatung: ein/aus und Stammdaten des Mandanten. */
function DatevSettings({
  orgId,
  settings,
  onChange,
}: {
  orgId: number
  settings: FinanceSettings
  onChange: (next: FinanceSettings) => void
}) {
  const [error, setError] = useState<string | null>(null)
  async function save(data: Partial<FinanceSettings>) {
    setError(null)
    try {
      onChange(await financeApi.updateSettings(orgId, data))
    } catch (err) {
      setError(errorMessage(err))
    }
  }
  const blur =
    (field: 'datev_consultant' | 'datev_client' | 'datev_chart' | 'datev_account_length') =>
    (e: { target: { value: string } }) => {
      const value = e.target.value.trim()
      if (value !== String(settings[field] ?? ''))
        void save({ [field]: field === 'datev_account_length' ? Number(value) : value })
    }
  return (
    <>
      <Checkbox
        label={t('DATEV-Export für die Steuerberatung nutzen')}
        checked={!!settings.datev_enabled}
        onChange={(on) => void save({ datev_enabled: on })}
      />
      {settings.datev_enabled && (
        <>
          <div className="grid-4">
            <Field
              label={t('Beraternummer')}
              inputMode="numeric"
              defaultValue={settings.datev_consultant ?? ''}
              onBlur={blur('datev_consultant')}
            />
            <Field
              label={t('Mandantennummer')}
              inputMode="numeric"
              defaultValue={settings.datev_client ?? ''}
              onBlur={blur('datev_client')}
            />
            <Field
              label={t('Sachkontenlänge')}
              type="number"
              min={4}
              max={8}
              defaultValue={settings.datev_account_length ?? 4}
              onBlur={blur('datev_account_length')}
            />
            <Field
              label={t('Kontenrahmen')}
              placeholder={t('z. B. SKR 49')}
              defaultValue={settings.datev_chart ?? ''}
              onBlur={blur('datev_chart')}
            />
          </div>
          <p className="muted small">
            {t(
              'Die Angaben bekommt ihr von eurer Steuerberatung. Tragt bei jedem Konto das DATEV-Finanzkonto (z. B. 1200 Bank, 1000 Kasse) und unter Kategorien das Sachkonto ein. Den Buchungsstapel gibt es dann unter Abschluss & Berichte › Jahresabschluss.',
            )}
          </p>
          <Why k="datev_accounts" />
        </>
      )}
      {error && <Alert kind="error">{error}</Alert>}
    </>
  )
}
