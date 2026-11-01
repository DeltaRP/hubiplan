// Kasse: Zählprotokoll (Kassensturz) und Kassenbericht für Feste (offene Ladenkasse).
// Einmal gespeichert, lässt sich ein Protokoll nicht mehr ändern; Differenz bzw.
// Tageseinnahme werden gebucht, das PDF hängt als Beleg an den Buchungen.
import { useState } from 'react'
import type { FormEvent } from 'react'
import { cashCountApi, DENOMINATIONS, euro, financeApi, parseAmount } from '../../api/finance.ts'
import type { CashCount, CashCountInput } from '../../api/finance.ts'
import { errorMessage, formatDate, useLoad } from '../../components/forms.ts'
import { Alert, Field, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { HowTo, Term, Why } from '../../learning/Aids.tsx'
import { t } from '../../i18n/index.ts'

function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function coinLabel(cents: number): string {
  return cents >= 100 ? t('{x} €', { x: cents / 100 }) : t('{cents} ct', { cents })
}

function cents(value: string): number {
  const n = Number(parseAmount(value || '0'))
  return Number.isFinite(n) ? Math.round(n * 100) : 0
}

export function CashCountsPage({ canEdit }: { canEdit: boolean }) {
  const org = useActiveOrg()
  const { data, error, reload } = useLoad(() => cashCountApi.list(org.id), [org.id])
  const [form, setForm] = useState<'count' | 'event' | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>

  return (
    <div className="card card-wide">
      <div className="card-head">
        <h2>{t('Kassenzählung')}</h2>
        {canEdit && form === null && (
          <span className="push-right">
            <button type="button" className="button button-ghost" onClick={() => setForm('count')}>
              {t('Kasse zählen')}
            </button>{' '}
            <button type="button" className="button button-ghost" onClick={() => setForm('event')}>
              {t('Kassenbericht Fest')}
            </button>
          </span>
        )}
      </div>
      <p className="muted small">
        {t('Das')} <strong>{t('Zählprotokoll')}</strong> (
        <Term k="cash_count_term">{t('Kassensturz')}</Term>
        {t(
          ') vergleicht das gezählte Bargeld mit dem Kassenbuch; eine Differenz wird mit Grund gebucht. Der',
        )}{' '}
        <strong>{t('Kassenbericht')}</strong> {t('ermittelt die Tageseinnahme einer')}{' '}
        <Term k="open_till">{t('offenen Ladenkasse')}</Term>
        {t(
          ', etwa am Getränkestand: Endbestand minus Wechselgeld plus bar bezahlte Ausgaben und Entnahmen. Gespeicherte Protokolle lassen sich nicht mehr ändern.',
        )}
      </p>
      <Why k="cash_count" />
      <Why k="event_cash" />
      {notice && <Alert kind="success">{notice}</Alert>}
      {form && (
        <CashCountForm
          kind={form}
          onCancel={() => setForm(null)}
          onSaved={async (saved) => {
            setForm(null)
            setNotice(
              t('{kind_label} vom {x} gespeichert', {
                kind_label: saved.kind_label,
                x: formatDate(saved.date),
              }) +
                (saved.bookings.length
                  ? t(', gebucht als {x}.', { x: saved.bookings.map((b) => b.number).join(', ') })
                  : '.'),
            )
            await reload()
          }}
        />
      )}
      {data.results.length === 0 ? (
        <p className="muted">{t('Noch keine Zählungen.')}</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>{t('Datum')}</th>
              <th>{t('Art')}</th>
              <th className="num">{t('gezählt')}</th>
              <th className="num">{t('Ergebnis')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.results.map((c) => (
              <tr key={c.id}>
                <td>{formatDate(c.date)}</td>
                <td>
                  <strong>{c.title || c.kind_label}</strong>
                  <div className="muted small">
                    {c.title ? t('{kind_label} · ', { kind_label: c.kind_label }) : ''}
                    {c.account_name} {t('· gezählt von')} {c.counted_by}
                    {c.bookings.length > 0 &&
                      t(' · gebucht als {x}', { x: c.bookings.map((b) => b.number).join(', ') })}
                  </div>
                </td>
                <td className="num">{euro(c.counted)}</td>
                <td className="num">
                  {c.kind === 'count'
                    ? t('Differenz {x}', { x: euro(c.difference) })
                    : t('Einnahme {x}', { x: euro(c.takings) })}
                </td>
                <td className="actions">
                  <a
                    className="link-button"
                    href={cashCountApi.pdfUrl(org.id, c.id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    PDF
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function CashCountForm({
  kind,
  onCancel,
  onSaved,
}: {
  kind: 'count' | 'event'
  onCancel: () => void
  onSaved: (saved: CashCount) => Promise<void>
}) {
  const org = useActiveOrg()
  const accounts = useLoad(() => financeApi.accounts(org.id), [org.id])
  const categories = useLoad(() => financeApi.categories(org.id), [org.id])
  const cashAccounts = (accounts.data ?? []).filter((a) => a.kind === 'cash' && a.is_active)
  const [account, setAccount] = useState('')
  const [date, setDate] = useState(todayIso)
  const [title, setTitle] = useState('')
  const [counts, setCounts] = useState<Record<string, string>>({})
  const [opening, setOpening] = useState('')
  const [expenses, setExpenses] = useState('')
  const [withdrawals, setWithdrawals] = useState('')
  const [lines, setLines] = useState<{ category: string; amount: string }[]>([
    { category: '', amount: '' },
  ])
  const [note, setNote] = useState('')
  const [category, setCategory] = useState('')
  const [countedBy, setCountedBy] = useState('')
  const [witness, setWitness] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const chosen = account || (cashAccounts.length === 1 ? String(cashAccounts[0].id) : '')
  const counted = DENOMINATIONS.reduce((sum, c) => sum + c * (Number(counts[c] || 0) || 0), 0)
  const takings = counted - cents(opening) + cents(expenses) + cents(withdrawals)
  const split = lines.reduce((sum, l) => sum + cents(l.amount), 0)
  const incomeCats = (categories.data ?? []).filter((c) => c.is_active && c.kind !== 'expense')
  const allCats = (categories.data ?? []).filter((c) => c.is_active)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const denominations: Record<string, number> = {}
    for (const c of DENOMINATIONS) {
      const n = Number(counts[c] || 0)
      if (n) denominations[String(c)] = n
    }
    const data: CashCountInput = {
      kind,
      account: Number(chosen),
      date,
      title,
      denominations,
      note,
      counted_by: countedBy,
      witness,
    }
    if (kind === 'count') data.category = category ? Number(category) : null
    else {
      data.opening = parseAmount(opening)
      data.expenses = parseAmount(expenses)
      data.withdrawals = parseAmount(withdrawals)
      data.lines = lines
        .filter((l) => l.category && l.amount)
        .map((l) => ({ category: Number(l.category), amount: parseAmount(l.amount) }))
    }
    try {
      await onSaved(await cashCountApi.create(org.id, data))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="subcard" onSubmit={(e) => void submit(e)}>
      <h3>{kind === 'count' ? t('Zählprotokoll') : t('Kassenbericht für ein Fest')}</h3>
      {accounts.data && cashAccounts.length === 0 && (
        <Alert kind="info">{t('Bitte zuerst unter Konten eine Barkasse anlegen.')}</Alert>
      )}
      <div className="grid-2">
        <SelectField
          label={t('Barkasse')}
          value={chosen}
          onChange={(e) => setAccount(e.target.value)}
          required
        >
          <option value="">{t('bitte wählen')}</option>
          {cashAccounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </SelectField>
        <Field
          label={t('Datum')}
          type="date"
          value={date}
          max={todayIso()}
          onChange={(e) => setDate(e.target.value)}
          required
        />
      </div>
      {kind === 'event' && (
        <Field
          label={t('Fest bzw. Verkaufsstand')}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t('z. B. Schützenfest Getränkezelt')}
          required
        />
      )}
      <fieldset>
        <legend>{kind === 'count' ? t('Gezähltes Bargeld') : t('Endbestand nach dem Fest')}</legend>
        <div className="grid-4">
          {DENOMINATIONS.map((c) => (
            <Field
              key={c}
              label={coinLabel(c)}
              type="number"
              min={0}
              step={1}
              inputMode="numeric"
              value={counts[c] ?? ''}
              onChange={(e) => setCounts({ ...counts, [c]: e.target.value })}
            />
          ))}
        </div>
        <p>
          <strong>
            {t('Summe:')} {euro(counted / 100)}
          </strong>
        </p>
      </fieldset>
      {kind === 'count' ? (
        <>
          <Field
            label={t('Grund bei einer Differenz')}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            hint={t('Nur nötig, wenn das gezählte Geld nicht zum Kassenbuch passt.')}
          />
          <SelectField
            label={t('Kategorie für eine Differenz')}
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">{t('keine Differenz')}</option>
            {allCats.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </SelectField>
        </>
      ) : (
        <>
          <div className="grid-3">
            <Field
              label={t('Anfangsbestand (Wechselgeld) in €')}
              inputMode="decimal"
              value={opening}
              onChange={(e) => setOpening(e.target.value)}
            />
            <Field
              label={t('bar bezahlte Ausgaben in €')}
              inputMode="decimal"
              value={expenses}
              onChange={(e) => setExpenses(e.target.value)}
              hint={t('Mit Beleg getrennt als Ausgabe buchen.')}
            />
            <Field
              label={t('Entnahmen in €')}
              inputMode="decimal"
              value={withdrawals}
              onChange={(e) => setWithdrawals(e.target.value)}
              hint={t('Zwischendurch abgeschöpftes Geld, z. B. zur Bank gebracht.')}
            />
          </div>
          <p>
            <strong>
              {t('Tageseinnahme:')} {euro(takings / 100)}
            </strong>
          </p>
          <HowTo k="calc_takings" />
          <fieldset>
            <legend>{t('Aufteilung der Einnahme')}</legend>
            {lines.map((l, i) => (
              <div className="grid-2" key={i}>
                <SelectField
                  label={t('Kategorie')}
                  value={l.category}
                  onChange={(e) =>
                    setLines(
                      lines.map((x, j) => (j === i ? { ...x, category: e.target.value } : x)),
                    )
                  }
                >
                  <option value="">{t('bitte wählen')}</option>
                  {incomeCats.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </SelectField>
                <Field
                  label={t('Betrag in €')}
                  inputMode="decimal"
                  value={l.amount}
                  onChange={(e) =>
                    setLines(lines.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))
                  }
                />
              </div>
            ))}
            <button
              type="button"
              className="link-button"
              onClick={() => setLines([...lines, { category: '', amount: '' }])}
            >
              {t('weitere Kategorie')}
            </button>
            {split !== takings && (
              <p className="muted small">
                {t('Noch aufzuteilen:')} {euro((takings - split) / 100)}
              </p>
            )}
          </fieldset>
          <Field label={t('Bemerkung')} value={note} onChange={(e) => setNote(e.target.value)} />
        </>
      )}
      <div className="grid-2">
        <Field
          label={t('Gezählt von')}
          value={countedBy}
          onChange={(e) => setCountedBy(e.target.value)}
          required
        />
        <Field
          label={t('Zweite Person (empfohlen)')}
          value={witness}
          onChange={(e) => setWitness(e.target.value)}
        />
      </div>
      {error && <Alert kind="error">{error}</Alert>}
      <div className="button-row">
        <button type="submit" className="button button-primary" disabled={busy || !chosen}>
          {t('Speichern und buchen')}
        </button>
        <button type="button" className="button button-ghost" onClick={onCancel}>
          {t('Abbrechen')}
        </button>
      </div>
    </form>
  )
}
