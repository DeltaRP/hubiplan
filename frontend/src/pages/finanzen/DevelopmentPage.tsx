// Finanzen › Entwicklung: Kontostände, Einnahmen und Ausgaben über die Zeit,
// Kategorien im Vergleich zum Vorjahreszeitraum.
import { Link } from 'react-router-dom'
import { euro } from '../../api/finance.ts'
import { statsApi } from '../../api/statistics.ts'
import type { FinanceStats } from '../../api/statistics.ts'
import { BarList, ChartCard, TimeChart } from '../../components/charts/Charts.tsx'
import {
  EXPENSE,
  INCOME,
  PREVIOUS,
  PRIMARY,
  foldSeries,
} from '../../components/charts/chartData.ts'
import { RangePicker } from '../../components/charts/RangePicker.tsx'
import { useRange } from '../../components/charts/range.ts'
import { formatDate, useLoad } from '../../components/forms.ts'
import { Alert } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { locale } from '../../i18n/index.ts'
import { t } from '../../i18n/index.ts'

const num = (v: string | null) => (v === null ? null : Number(v))
const money = (n: number) => euro(n)
/** Kurz für Achsen: 12.500 € statt 12.500,00 € */
const axisMoney = (n: number) =>
  t('{x} €', { x: n.toLocaleString(locale(), { maximumFractionDigits: Math.abs(n) < 10 ? 2 : 0 }) })

function Compare({ now, before }: { now: string; before: string }) {
  const a = Number(now)
  const b = Number(before)
  if (b === 0)
    return (
      <p className="small muted">
        {t('Vorjahreszeitraum:')} {euro(before)}
      </p>
    )
  const pct = Math.round(((a - b) / Math.abs(b)) * 100)
  return (
    <p className="small muted">
      {pct > 0 ? `+${pct}` : pct < 0 ? `−${-pct}` : '±0'}{' '}
      {t('% zum Vorjahreszeitraum ({x})', { x: euro(before) })}
    </p>
  )
}

export function FinanceDevelopment({ canEdit }: { canEdit: boolean }) {
  const org = useActiveOrg()
  const range = useRange()
  const key = JSON.stringify(range.query)
  const { data, error } = useLoad(() => statsApi.finance(org.id, range.query), [org.id, key])
  return (
    <div className="stack">
      <RangePicker
        range={range}
        info={
          data
            ? t('{x} bis {x2}', { x: formatDate(data.von), x2: formatDate(data.bis) })
            : undefined
        }
      />
      {error && <Alert kind="error">{error}</Alert>}
      {!data && !error && <p className="muted">{t('Lädt …')}</p>}
      {data &&
        (data.accounts.length === 0 ? (
          <div className="card empty-state">
            <p>{t('Für diesen Zeitraum gibt es noch keine Konten.')}</p>
            {canEdit && (
              <p>
                <Link to="/finanzen/einstellungen/konten">{t('Konto anlegen')}</Link>
              </p>
            )}
          </div>
        ) : (
          <FinanceCharts data={data} />
        ))}
    </div>
  )
}

function FinanceCharts({ data }: { data: FinanceStats }) {
  const s = data.summary
  const labels = data.buckets.map((b) => b.label)
  const per = data.raster === 'monat' ? t('je Monat') : t('je Geschäftsjahr')
  const change = Number(s.balance_end) - Number(s.balance_start)
  const accounts = foldSeries(
    data.accounts.map((a) => ({
      key: String(a.id),
      name: a.name,
      values: a.values.map((v) => Number(v ?? 0)),
    })),
  ).map((serie) => {
    // Konten erst ab ihrem Stichtag zeichnen
    const account = data.accounts.find((a) => String(a.id) === serie.key)
    return account ? { ...serie, values: account.values.map(num) } : serie
  })
  const previous = t('{x} bis {x2}', {
    x: formatDate(data.previous.von),
    x2: formatDate(data.previous.bis),
  })
  const categoryRows = (kind: 'income' | 'expense') =>
    data.categories
      .filter((c) => Number(c[kind]) > 0 || Number(c[`previous_${kind}`]) > 0)
      .sort((a, b) => Number(b[kind]) - Number(a[kind]))
      .map((c) => ({
        key: String(c.id),
        label: c.name,
        values: [Number(c[`previous_${kind}`]), Number(c[kind])],
      }))
  // Ohne Buchungen im Vorjahreszeitraum nur den gewählten Zeitraum zeigen
  const hasPrevious = data.categories.some(
    (c) => Number(c.previous_income) > 0 || Number(c.previous_expense) > 0,
  )
  const compareSeries = (color: string) =>
    hasPrevious
      ? [
          {
            key: 'vorher',
            name: t('Vorjahreszeitraum ({previous})', { previous }),
            color: PREVIOUS,
          },
          { key: 'jetzt', name: t('Gewählter Zeitraum'), color },
        ]
      : [{ key: 'jetzt', name: t('Gewählter Zeitraum'), color }]
  const strip = (rows: ReturnType<typeof categoryRows>) =>
    hasPrevious ? rows : rows.map((r) => ({ ...r, values: [r.values[1]] }))
  const incomeRows = strip(categoryRows('income'))
  const expenseRows = strip(categoryRows('expense'))

  return (
    <>
      <div className="tiles tiles-figures">
        <div className="card tile">
          <h2>{t('Einnahmen')}</h2>
          <p className="amount-big amount-in">{euro(s.income)}</p>
          <Compare now={s.income} before={s.previous_income} />
        </div>
        <div className="card tile">
          <h2>{t('Ausgaben')}</h2>
          <p className="amount-big amount-out">{euro(s.expense)}</p>
          <Compare now={s.expense} before={s.previous_expense} />
        </div>
        <div className="card tile">
          <h2>{t('Ergebnis')}</h2>
          <p className={`amount-big ${Number(s.result) < 0 ? 'amount-out' : 'amount-in'}`}>
            {euro(s.result)}
          </p>
          <p className="small muted">
            {t('Vorjahreszeitraum:')} {euro(s.previous_result)}
          </p>
        </div>
        <div className="card tile">
          <h2>
            {t('Kontostand am')} {formatDate(data.bis)}
          </h2>
          <p className="amount-big">{euro(s.balance_end)}</p>
          <p className="small muted">
            {change >= 0 ? '+' : '−'}
            {euro(Math.abs(change))} seit {formatDate(data.von)}
          </p>
        </div>
      </div>

      <ChartCard
        title={t('Kontostand gesamt')}
        note={
          data.raster === 'monat'
            ? t('Summe aller Konten am Ende jedes Monats')
            : t('Summe aller Konten am Ende jedes Geschäftsjahres')
        }
      >
        <TimeChart
          title={t('Kontostand gesamt')}
          kind="line"
          labels={labels}
          format={money}
          axisFormat={axisMoney}
          series={[
            {
              key: 'summe',
              name: t('Kontostand'),
              color: PRIMARY,
              values: data.buckets.map((b) => num(b.balance)),
            },
          ]}
        />
      </ChartCard>

      {data.accounts.length > 1 && (
        <ChartCard title={t('Kontostände je Konto')}>
          <TimeChart
            title={t('Kontostände je Konto')}
            kind="line"
            labels={labels}
            format={money}
            axisFormat={axisMoney}
            series={accounts}
          />
        </ChartCard>
      )}

      <ChartCard
        title={t('Einnahmen und Ausgaben {per}', { per })}
        note={t('Ohne Umbuchungen zwischen Konten')}
      >
        <TimeChart
          title={t('Einnahmen und Ausgaben {per}', { per })}
          kind="bar"
          labels={labels}
          format={money}
          axisFormat={axisMoney}
          series={[
            {
              key: 'ein',
              name: t('Einnahmen'),
              color: INCOME,
              values: data.buckets.map((b) => Number(b.income)),
            },
            {
              key: 'aus',
              name: t('Ausgaben'),
              color: EXPENSE,
              values: data.buckets.map((b) => Number(b.expense)),
            },
          ]}
        />
      </ChartCard>

      <ChartCard title={t('Ergebnis {per}', { per })} note={t('Einnahmen minus Ausgaben')}>
        <TimeChart
          title={t('Ergebnis {per}', { per })}
          kind="bar"
          labels={labels}
          format={money}
          axisFormat={axisMoney}
          series={[
            {
              key: 'ergebnis',
              name: t('Ergebnis'),
              color: PRIMARY,
              values: data.buckets.map((b) => Number(b.result)),
            },
          ]}
        />
      </ChartCard>

      <div className="chart-pair">
        <ChartCard title={t('Einnahmen nach Kategorie')}>
          {incomeRows.length === 0 ? (
            <p className="muted">{t('Keine Einnahmen.')}</p>
          ) : (
            <BarList
              head={t('Kategorie')}
              format={money}
              series={compareSeries(INCOME)}
              rows={incomeRows}
            />
          )}
        </ChartCard>
        <ChartCard title={t('Ausgaben nach Kategorie')}>
          {expenseRows.length === 0 ? (
            <p className="muted">{t('Keine Ausgaben.')}</p>
          ) : (
            <BarList
              head={t('Kategorie')}
              format={money}
              series={compareSeries(EXPENSE)}
              rows={expenseRows}
            />
          )}
        </ChartCard>
      </div>
    </>
  )
}
