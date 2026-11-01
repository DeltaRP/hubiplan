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
  if (!data) return <p className="muted">Wird geladen …</p>
  const exp = (q: string) => competitionsApi.exportUrl(org, comp.id, q)

  return (
    <>
      <div className="button-row">
        <a className="button button-ghost" href={exp('als=pdf')} target="_blank" rel="noreferrer">
          Ergebnisliste (PDF)
        </a>
        <a className="button button-ghost" href={exp('als=xlsx')}>
          Excel
        </a>
        <button type="button" className="button button-ghost" onClick={reload}>
          Aktualisieren
        </button>
      </div>
      {data.bird && <BirdResults bird={data.bird} />}
      {data.open_shootoffs > 0 && (
        <Alert kind="info">
          <Term k="comp_tie">Gleichstand</Term> auf <Term k="comp_prize_place">Preisplätzen</Term>:
          Stechen nötig. Erst danach lässt sich der Wettbewerb endgültig abschließen.
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
                Ohne Ergebnis: {block.without_value.map((w) => w.name).join(', ')}
              </p>
            )}
          </div>
        )
      })}
      {'count' in data.stats && <StatsCard stats={data.stats as Stats} />}
      <p className="muted small">
        Zustand ändern und abschließen unter „Einrichten“.{' '}
        <button type="button" className="link-button" onClick={onChanged}>
          Neu laden
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
        <h2>Pfänderliste</h2>
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>
                  <Term k="comp_prize">Pfand</Term>
                </th>
                <th>Schütze</th>
                <th>Einheit / Verein</th>
                <th className="num">Schuss Nr.</th>
                <th className="num">Schüsse</th>
                <th>Preis</th>
              </tr>
            </thead>
            <tbody>
              {bird.prizes.map((p) => (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td>{p.winner_name || <span className="muted">hängt noch</span>}</td>
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
        <h2>Kennzahlen</h2>
        <dl className="stats-list">
          <dt>Schüsse insgesamt</dt>
          <dd>{st.shots}</dd>
          <dt>Schützen</dt>
          <dd>
            {st.starters} ({st.members} Mitglieder, {st.guests} Gäste)
          </dd>
          {st.rounds ? (
            <>
              <dt>
                <Term k="comp_round">Runden</Term>
              </dt>
              <dd>{st.rounds}</dd>
            </>
          ) : null}
          {st.duration_minutes !== null ? (
            <>
              <dt>Dauer</dt>
              <dd>{st.duration_minutes} Minuten</dd>
            </>
          ) : null}
          {st.per_unit.map((u) => (
            <Fragment key={u.name}>
              <dt>Pfänder {u.name}</dt>
              <dd>{u.count}</dd>
            </Fragment>
          ))}
        </dl>
        {(bird.draw.missing.length > 0 || bird.draw.gaps.length > 0) && (
          <p className="muted small">
            {bird.draw.missing.length ? (
              <>
                Ohne <Term k="comp_lot">Losnummer</Term>: {bird.draw.missing.join(', ')}.{' '}
              </>
            ) : null}
            {bird.draw.gaps.length ? `Nicht vergebene Nummern: ${bird.draw.gaps.join(', ')}.` : ''}
          </p>
        )}
      </div>
    </>
  )
}

function ForeignTable({ block }: { block: StandingBlock }) {
  const team = block.kind === 'mannschaft'
  if (!block.rows.length)
    return <p className="muted">{team ? 'Noch keine Mannschaften.' : 'Noch keine Schützen.'}</p>
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th className="num">Platz</th>
            <th>{team ? 'Mannschaft' : 'Name'}</th>
            <th>{team ? 'Schützen' : 'Einheit'}</th>
            <th className="num">Wert</th>
            <th>Bemerkung</th>
          </tr>
        </thead>
        <tbody>
          {block.rows.map((r) => (
            <tr key={r.key} className={r.prize ? 'row-prize' : undefined}>
              <td className="num">
                {r.place ? `${r.place}.` : '–'}
                {r.place && block.field_size ? ` von ${block.field_size}` : ''}
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
  if (!block.rows.length) return <p className="muted">Noch keine Ergebnisse.</p>
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th className="num">Platz</th>
            <th>{unit ? 'Einheit' : 'Name'}</th>
            <th>{unit ? 'Schützen' : 'Einheit / Verein'}</th>
            {unit && <th>Bester Schütze</th>}
            <th className="num">Wert</th>
            {hasShootoff && (
              <th className="num">
                <Term k="comp_shootoff">Stechen</Term>
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
                    (<Term k="comp_ooc">außer Konkurrenz</Term>)
                  </>
                ) : null}
                {r.guest ? (
                  <span className="muted">
                    {' '}
                    · <Term k="comp_guest">Gast</Term>
                  </span>
                ) : null}
              </td>
              <td>{unit ? r.count : r.unit_name || r.club}</td>
              {unit && <td>{r.best}</td>}
              <td className="num">{r.value_text || <span className="muted">{r.reason}</span>}</td>
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
      <h2>Kennzahlen</h2>
      <dl className="stats-list">
        <dt>Schützen</dt>
        <dd>
          {stats.count} ({stats.members} Mitglieder, {stats.guests} Gäste)
        </dd>
        <dt>Durchschnitt</dt>
        <dd>{stats.average}</dd>
        <dt>Höchster / niedrigster Wert</dt>
        <dd>
          {stats.max} / {stats.min}
        </dd>
      </dl>
      {stats.per_unit.length > 0 && (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Einheit</th>
                <th className="num">Schützen</th>
                <th className="num">Mitglieder</th>
                <th className="num">Beteiligung</th>
                <th className="num">Durchschnitt</th>
                <th className="num">Bester Wert</th>
              </tr>
            </thead>
            <tbody>
              {stats.per_unit.map((u) => (
                <tr key={u.unit}>
                  <td>{u.name}</td>
                  <td className="num">{u.count}</td>
                  <td className="num">{u.members}</td>
                  <td className="num">{u.participation !== null ? `${u.participation} %` : ''}</td>
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
