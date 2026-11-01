// Mitgliederentwicklung: Bestand, Ein- und Austritte, Arten, Abteilungen bzw.
// Vereine und Altersstruktur im gewählten Zeitraum.
import { statsApi } from '../../api/statistics.ts'
import type { AgeSummary, MemberStats, RangeQuery } from '../../api/statistics.ts'
import { BarList, ChartCard, TimeChart } from '../../components/charts/Charts.tsx'
import {
  EXPENSE,
  INCOME,
  PREVIOUS,
  PRIMARY,
  allSeries,
  foldSeries,
} from '../../components/charts/chartData.ts'
import { RangePicker } from '../../components/charts/RangePicker.tsx'
import { useRange } from '../../components/charts/range.ts'
import { formatDate, useLoad } from '../../components/forms.ts'
import { Alert } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { useTerms } from '../../org/terms.ts'
import { HowTo } from '../../learning/Aids.tsx'
import { ownMembers } from './access.ts'
import { locale } from '../../i18n/index.ts'
import { t } from '../../i18n/index.ts'

/** Mitglieder › Entwicklung: eigene Mitglieder (``own``) oder alle Einheiten darunter
 *  (``all``, mit Freigabe der Plattform). */
export function MembersDevelopmentPage({ view = 'own' }: { view?: 'own' | 'all' }) {
  const tm = useTerms()
  const org = useActiveOrg()
  // Ohne eigene Mitglieder gibt es nur die Sicht auf alle darunter
  const federation = view === 'all' || (org.type === 'federation' && !ownMembers(org))
  return (
    <section>
      <div className="page-head">
        <div>
          <p className="muted small eyebrow">{t('Mitglieder')}</p>
          <h1>{t('Entwicklung')}</h1>
        </div>
      </div>
      <MemberDevelopment
        scope={`org-${org.id}-${federation ? 'all' : 'own'}`}
        load={(q) => (federation ? statsApi.federation(org.id, q) : statsApi.club(org.id, q))}
        note={
          federation
            ? t('Gezählt werden Mitgliedschaften mit einer an {e_akk} gemeldeten Mitgliedsart.', {
                e_akk: tm.e_akk,
              })
            : undefined
        }
      />
    </section>
  )
}

const count = (n: number) => n.toLocaleString(locale())
const signed = (n: number) => (n > 0 ? `+${count(n)}` : n < 0 ? `−${count(-n)}` : '±0')

export function MemberDevelopment({
  load,
  scope,
  note,
}: {
  load: (q: RangeQuery) => Promise<MemberStats>
  /** Kennung der Sicht (Organisation bzw. Abteilung) für das Neuladen */
  scope: string
  note?: string
}) {
  // Standard: letzte 5 Jahre nach Jahren; monatlich ist für kleine Einheiten zu fein
  const range = useRange('5j')
  const key = JSON.stringify(range.query)
  const { data, error } = useLoad(() => load(range.query), [scope, key])
  const loaded = data

  return (
    <div className="stack">
      <RangePicker
        range={range}
        info={
          loaded
            ? t('{x} bis {x2}', { x: formatDate(loaded.von), x2: formatDate(loaded.bis) })
            : undefined
        }
      />
      {note && <p className="muted small">{note}</p>}
      {error && <Alert kind="error">{error}</Alert>}
      {!loaded && !error && <p className="muted">{t('Lädt …')}</p>}
      {loaded && <MemberCharts data={loaded} />}
    </div>
  )
}

function MemberCharts({ data }: { data: MemberStats }) {
  const s = data.summary
  const labels = data.buckets.map((b) => b.label)
  const per = data.raster === 'monat' ? t('je Monat') : t('je Jahr')
  const change = s.end - s.start
  if (s.start === 0 && s.end === 0 && s.entries === 0 && s.exits === 0)
    return (
      <div className="card empty-state">
        <p>{t('In diesem Zeitraum gibt es keine Mitglieder.')}</p>
      </div>
    )
  // Alle Untereinheiten einzeln; in der Legende ein- und ausblendbar (Ralf 2026-10-29)
  const groups = allSeries(
    data.groups.map((g) => ({ key: String(g.id ?? 'ohne'), name: g.name, values: g.values })),
    'ohne',
  )
  const types = foldSeries(
    data.types.map((t) => ({ key: String(t.id), name: t.name, values: t.values })),
  )
  return (
    <>
      <div className="tiles tiles-figures">
        <div className="card tile">
          <h2>
            {t('Mitglieder am')} {formatDate(data.bis)}
          </h2>
          <p className="amount-big">{count(s.end)}</p>
          <p className="small muted">
            {signed(change)} seit {formatDate(data.von)} ({count(s.start)})
          </p>
          <p className="small muted">{t('Bestand nach den Austritten dieses Tages')}</p>
        </div>
        <div className="card tile">
          <h2>{t('Eintritte')}</h2>
          <p className="amount-big">{count(s.entries)}</p>
        </div>
        <div className="card tile">
          <h2>{t('Austritte')}</h2>
          <p className="amount-big">{count(s.exits)}</p>
        </div>
      </div>
      <HowTo k="calc_members_on_date" />

      <ChartCard
        title={t('Mitgliederbestand')}
        note={t('Bestand am Ende jedes {x}, nach den Austritten des Tages', {
          x: data.raster === 'monat' ? 'Monats' : 'Jahres',
        })}
      >
        <TimeChart
          title={t('Mitgliederbestand')}
          kind="line"
          labels={labels}
          format={count}
          series={[
            {
              key: 'bestand',
              name: t('Mitglieder'),
              color: PRIMARY,
              values: data.buckets.map((b) => b.count),
            },
          ]}
        />
      </ChartCard>

      <ChartCard title={t('Eintritte und Austritte {per}', { per })}>
        <TimeChart
          title={t('Eintritte und Austritte {per}', { per })}
          kind="bar"
          labels={labels}
          format={count}
          series={[
            {
              key: 'ein',
              name: t('Eintritte'),
              color: INCOME,
              values: data.buckets.map((b) => b.entries),
            },
            {
              key: 'aus',
              name: t('Austritte'),
              color: EXPENSE,
              values: data.buckets.map((b) => b.exits),
            },
          ]}
        />
      </ChartCard>

      {types.length > 0 && (
        <ChartCard title={t('Nach Mitgliedsart')}>
          <TimeChart
            title={t('Mitglieder nach Mitgliedsart')}
            kind="line"
            labels={labels}
            format={count}
            series={types}
          />
        </ChartCard>
      )}

      {groups.length > 1 && (
        <ChartCard title={t('Nach {groups_title}', { groups_title: data.groups_title })}>
          <TimeChart
            title={t('Mitglieder nach {groups_title}', { groups_title: data.groups_title })}
            kind="line"
            labels={labels}
            format={count}
            series={groups}
            toggleable
          />
        </ChartCard>
      )}

      <div className="chart-pair">
        <ChartCard
          title={t('Altersstruktur')}
          note={
            <AgeSummaries
              items={[
                [formatDate(data.ages.start_on ?? data.von), data.ages.start_summary],
                [formatDate(data.bis), data.ages.end_summary],
              ]}
            />
          }
        >
          <BarList
            head={t('Alter')}
            format={count}
            series={[
              {
                key: 'start',
                name: t('am {x}', { x: formatDate(data.ages.start_on ?? data.von) }),
                color: PREVIOUS,
              },
              { key: 'end', name: t('am {x}', { x: formatDate(data.bis) }), color: PRIMARY },
            ]}
            rows={data.ages.groups.map((g, i) => ({
              key: g,
              label: g,
              values: [data.ages.start[i], data.ages.end[i]],
            }))}
          />
        </ChartCard>
        <ChartCard title={t('Austrittsgründe')}>
          {data.exit_reasons.length === 0 ? (
            <p className="muted">{t('Keine Austritte im Zeitraum.')}</p>
          ) : (
            <BarList
              head={t('Grund')}
              format={count}
              series={[{ key: 'n', name: t('Austritte'), color: EXPENSE }]}
              rows={data.exit_reasons.map((r) => ({
                key: r.reason,
                label: r.label,
                values: [r.count],
              }))}
            />
          )}
        </ChartCard>
      </div>
    </>
  )
}

const oneDecimal = (n: number) =>
  n.toLocaleString(locale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 })

/** Durchschnittsalter (± Standardabweichung) zu beiden Stichtagen */
function AgeSummaries({ items }: { items: [string, AgeSummary | undefined][] }) {
  const shown = items.flatMap(([day, s]) =>
    s && s.mean !== null ? [{ day, mean: s.mean, sd: s.sd, count: s.count }] : [],
  )
  if (shown.length === 0) return null
  return (
    <dl className="age-summary">
      {shown.map(({ day, mean, sd, count }) => (
        <div key={day}>
          <dt>
            {t('Durchschnittsalter am')} {day}
          </dt>
          <dd>
            {oneDecimal(mean)} {t('Jahre')}
            {sd !== null && (
              <>
                {' '}
                (<abbr title={t('Standardabweichung über den ganzen Bestand')}>SD</abbr>{' '}
                {oneDecimal(sd)})
              </>
            )}
            , {count.toLocaleString(locale())} {count === 1 ? t('Person') : t('Personen')}
          </dd>
        </div>
      ))}
    </dl>
  )
}
