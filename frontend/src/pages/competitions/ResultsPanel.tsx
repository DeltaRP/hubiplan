// Auswertung: Ranglisten je Wertung mit Preisplätzen, offene Stechen, Kennzahlen, Ausgaben.
import { Fragment } from 'react'
import {
  competitionsApi,
  orgShootoffApi,
  type BirdState,
  type CompetitionDetail,
  type StandingBlock,
  type Stats,
} from '../../api/competitions.ts'
import { useLoad } from '../../components/forms.ts'
import { Alert, LoadError } from '../../components/ui.tsx'
import { ShootoffBlock } from './Shootoffs.tsx'
import { HowTo, Term } from '../../learning/Aids.tsx'
import { t } from '../../i18n/index.ts'

export function ResultsPanel({
  org,
  comp,
  onChanged,
}: {
  org: number
  comp: CompetitionDetail
  onChanged: () => void
}) {
  const standings = useLoad(() => competitionsApi.standings(org, comp.id), [org, comp.id])
  const shootoffs = useLoad(() => competitionsApi.shootoffs(org, comp.id), [org, comp.id])
  const closed = comp.status === 'endgueltig'

  function reload() {
    void standings.reload()
    void shootoffs.reload()
  }

  if (standings.error) return <LoadError message={standings.error} onRetry={reload} />
  const data = standings.data
  if (!data) return <p className="muted">{t('Wird geladen …')}</p>
  const exp = (q: string) => competitionsApi.exportUrl(org, comp.id, q)

  return (
    <>
      <div className="button-row">
        <a className="button button-ghost" href={exp('als=pdf')} target="_blank" rel="noreferrer">
          {t('Ergebnisliste (PDF)')}
        </a>
        <a className="button button-ghost" href={exp('als=xlsx')}>
          {t('Excel')}
        </a>
        <button type="button" className="button button-ghost" onClick={reload}>
          {t('Aktualisieren')}
        </button>
      </div>
      {data.bird && <BirdResults bird={data.bird} />}
      {data.open_shootoffs > 0 && (
        <Alert kind="info">
          <Term k="comp_tie">{t('Gleichstand')}</Term> auf{' '}
          <Term k="comp_prize_place">{t('Preisplätzen')}</Term>
          {t(': Stechen nötig. Erst danach lässt sich der Wettbewerb endgültig abschließen.')}
        </Alert>
      )}
      {data.scorings.map((block) => {
        const own = (shootoffs.data ?? []).filter((so) => so.scoring === block.scoring)
        return (
          <div className="card card-wide" key={block.scoring}>
            <h2>{block.name}</h2>
            {comp.own ? <StandingTable block={block} /> : <ForeignTable block={block} />}
            <ShootoffBlock
              api={orgShootoffApi(org, comp.id)}
              comp={comp}
              block={block}
              shootoffs={own}
              closed={closed}
              onChanged={reload}
            />
            {block.without_value.length > 0 && (
              <p className="muted small">
                {t('Ohne Ergebnis:')} {block.without_value.map((w) => w.name).join(', ')}
              </p>
            )}
          </div>
        )
      })}
      {'count' in data.stats && <StatsCard stats={data.stats as Stats} />}
      <p className="muted small">
        {t('Zustand ändern und abschließen unter „Einrichten“.')}{' '}
        <button type="button" className="link-button" onClick={onChanged}>
          {t('Neu laden')}
        </button>
      </p>
    </>
  )
}

function BirdResults({ bird }: { bird: BirdState }) {
  const st = bird.stats
  return (
    <>
      <div className="card card-wide">
        <h2>{t('Pfänderliste')}</h2>
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>
                  <Term k="comp_prize">{t('Pfand')}</Term>
                </th>
                <th>{t('Schütze')}</th>
                <th>{t('Einheit / Verein')}</th>
                <th className="num">{t('Schuss Nr.')}</th>
                <th className="num">{t('Schüsse')}</th>
                <th>{t('Preis')}</th>
              </tr>
            </thead>
            <tbody>
              {bird.prizes.map((p) => (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td>{p.winner_name || <span className="muted">{t('hängt noch')}</span>}</td>
                  <td>{p.unit_name || p.club}</td>
                  <td className="num">{p.shot_number ?? ''}</td>
                  <td className="num">{p.shots_for ?? ''}</td>
                  <td>{p.award}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="card card-wide">
        <h2>{t('Kennzahlen')}</h2>
        <dl className="stats-list">
          <dt>{t('Schüsse insgesamt')}</dt>
          <dd>{st.shots}</dd>
          <dt>{t('Schützen')}</dt>
          <dd>
            {st.starters}{' '}
            {t('({members} Mitglieder, {guests} Gäste)', {
              members: st.members,
              guests: st.guests,
            })}
          </dd>
          {st.rounds ? (
            <>
              <dt>
                <Term k="comp_round">{t('Runden')}</Term>
              </dt>
              <dd>{st.rounds}</dd>
            </>
          ) : null}
          {st.duration_minutes !== null ? (
            <>
              <dt>{t('Dauer')}</dt>
              <dd>
                {st.duration_minutes} {t('Minuten')}
              </dd>
            </>
          ) : null}
          {st.per_unit.map((u) => (
            <Fragment key={u.name}>
              <dt>
                {t('Pfänder')} {u.name}
              </dt>
              <dd>{u.count}</dd>
            </Fragment>
          ))}
        </dl>
        {(bird.draw.missing.length > 0 || bird.draw.gaps.length > 0) && (
          <p className="muted small">
            {bird.draw.missing.length ? (
              <>
                {t('Ohne')} <Term k="comp_lot">{t('Losnummer')}</Term>:{' '}
                {bird.draw.missing.join(', ')}.{' '}
              </>
            ) : null}
            {bird.draw.gaps.length
              ? t('Nicht vergebene Nummern: {x}.', { x: bird.draw.gaps.join(', ') })
              : ''}
          </p>
        )}
      </div>
    </>
  )
}

function ForeignTable({ block }: { block: StandingBlock }) {
  const team = block.kind === 'mannschaft'
  if (!block.rows.length)
    return (
      <p className="muted">{team ? t('Noch keine Mannschaften.') : t('Noch keine Schützen.')}</p>
    )
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th className="num">{t('Platz')}</th>
            <th>{team ? t('Mannschaft') : t('Name')}</th>
            <th>{team ? t('Schützen') : t('Einheit')}</th>
            <th className="num">{t('Wert')}</th>
            <th>{t('Bemerkung')}</th>
          </tr>
        </thead>
        <tbody>
          {block.rows.map((r) => (
            <tr key={r.key} className={r.prize ? 'row-prize' : undefined}>
              <td className="num">
                {r.place ? `${r.place}.` : '–'}
                {r.place && block.field_size
                  ? t(' von {field_size}', { field_size: block.field_size })
                  : ''}
              </td>
              <td>{r.name}</td>
              <td>{team ? (r.members ?? []).join(', ') : r.unit_name || r.club}</td>
              <td className="num">{r.value_text}</td>
              <td>{r.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StandingTable({ block }: { block: StandingBlock }) {
  const unit = block.kind === 'einheit'
  const hasShootoff = block.rows.some((r) => r.shootoff && Object.keys(r.shootoff).length)
  if (!block.rows.length) return <p className="muted">{t('Noch keine Ergebnisse.')}</p>
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th className="num">{t('Platz')}</th>
            <th>{unit ? t('Einheit') : t('Name')}</th>
            <th>{unit ? t('Schützen') : t('Einheit / Verein')}</th>
            {unit && <th>{t('Bester Schütze')}</th>}
            <th className="num">{t('Wert')}</th>
            {hasShootoff && (
              <th className="num">
                <Term k="comp_shootoff">{t('Stechen')}</Term>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((r) => (
            <tr key={r.key} className={r.prize ? 'row-prize' : undefined}>
              <td className="num">{r.place ? `${r.place}.` : '–'}</td>
              <td>
                {r.name}
                {r.out_of_competition ? (
                  <>
                    {' '}
                    (<Term k="comp_ooc">{t('außer Konkurrenz')}</Term>)
                  </>
                ) : null}
                {r.guest ? (
                  <span className="muted">
                    {' '}
                    · <Term k="comp_guest">{t('Gast')}</Term>
                  </span>
                ) : null}
              </td>
              <td>{unit ? r.count : r.unit_name || r.club}</td>
              {unit && <td>{r.best}</td>}
              <td className="num">
                {r.value_text || <span className="muted">{r.reason}</span>}
                {r.decided_by ? (
                  <span className="muted small" title={t('entschieden durch')}>
                    {' '}
                    · {r.decided_by}
                  </span>
                ) : null}
              </td>
              {hasShootoff && (
                <td className="num">{Object.values(r.shootoff ?? {}).join(' / ')}</td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {unit ? <HowTo k="how_comp_unit" /> : <HowTo k="how_comp_ranking" />}
    </div>
  )
}

function StatsCard({ stats }: { stats: Stats }) {
  return (
    <div className="card card-wide">
      <h2>{t('Kennzahlen')}</h2>
      <dl className="stats-list">
        <dt>{t('Schützen')}</dt>
        <dd>
          {stats.count}{' '}
          {t('({members} Mitglieder, {guests} Gäste)', {
            members: stats.members,
            guests: stats.guests,
          })}
        </dd>
        <dt>{t('Durchschnitt')}</dt>
        <dd>{stats.average}</dd>
        <dt>{t('Höchster / niedrigster Wert')}</dt>
        <dd>
          {stats.max} / {stats.min}
        </dd>
      </dl>
      {stats.per_unit.length > 0 && (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>{t('Einheit')}</th>
                <th className="num">{t('Schützen')}</th>
                <th className="num">{t('Mitglieder')}</th>
                <th className="num">{t('Beteiligung')}</th>
                <th className="num">{t('Durchschnitt')}</th>
                <th className="num">{t('Bester Wert')}</th>
              </tr>
            </thead>
            <tbody>
              {stats.per_unit.map((u) => (
                <tr key={u.unit}>
                  <td>{u.name}</td>
                  <td className="num">{u.count}</td>
                  <td className="num">{u.members}</td>
                  <td className="num">
                    {u.participation !== null
                      ? t('{participation} %', { participation: u.participation })
                      : ''}
                  </td>
                  <td className="num">{u.average}</td>
                  <td className="num">{u.best}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
