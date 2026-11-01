// Mitgliedsakte › Wettbewerbe: alle Starts mit Platz und Wert, Titel und Auszeichnungen.
import { Link } from 'react-router-dom'
import { historyApi } from '../../api/competitionHistory.ts'
import { useLoad } from '../../components/forms.ts'
import { LoadError } from '../../components/ui.tsx'
import { locale, t } from '../../i18n/index.ts'

export function CompetitionsTab({ org, membership }: { org: number; membership: number }) {
  const { data, error, reload } = useLoad(
    () => historyApi.member(org, membership),
    [org, membership],
  )
  if (error) return <LoadError message={error} onRetry={reload} />
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  return (
    <div className="card card-wide">
      <h2>{t('Titel und Auszeichnungen')}</h2>
      {data.grants.length === 0 ? (
        <p className="muted">{t('Noch keine Titel.')}</p>
      ) : (
        <ul className="plain-list">
          {data.grants.map((g) => (
            <li key={g.id}>
              <strong>{g.full_title || g.trophy_name}</strong>
              {g.place ? t(' · {x}', { x: t('Platz {n}', { n: g.place }) }) : ''}
              {g.competition_title
                ? t(' · {competition_title}', { competition_title: g.competition_title })
                : ''}
              {g.dignity_state === 'vorschlag' &&
                t(' · {x}', {
                  x: t('Vorschlag: {dignity} {year}', { dignity: g.dignity_name, year: g.year }),
                })}
            </li>
          ))}
        </ul>
      )}
      <h2>{t('Starts')}</h2>
      {data.starts.length === 0 ? (
        <p className="muted">{t('Noch keine Starts.')}</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>{t('Datum')}</th>
              <th>{t('Wettbewerb')}</th>
              <th>{t('Ergebnis')}</th>
            </tr>
          </thead>
          <tbody>
            {data.starts.map((s) => (
              <tr key={s.competition}>
                <td>{new Date(s.date).toLocaleDateString(locale())}</td>
                <td>
                  {data.can_open ? (
                    <Link to={`/wettbewerbe/${s.competition}/auswertung`}>{s.title}</Link>
                  ) : (
                    s.title
                  )}
                  {s.unit_name ? <span className="muted"> · {s.unit_name}</span> : null}
                  {s.status !== 'endgueltig' && <span className="muted"> · {s.status_label}</span>}
                </td>
                <td>
                  {s.results.length === 0
                    ? '–'
                    : s.results
                        .map((r) =>
                          [
                            r.scoring,
                            r.place
                              ? r.field
                                ? t('Platz {place} von {n}', { place: r.place, n: r.field })
                                : t('Platz {n}', { n: r.place })
                              : '',
                            r.value_text,
                          ]
                            .filter(Boolean)
                            .join(' · '),
                        )
                        .join('; ')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
