// Wettbewerbe Schritt 3: Ergebnisse zur Meldung einer Untereinheit. Nach dem Abschluss sieht
// die Untereinheit die Plätze ihrer Starter und Mannschaften und die Wertung der
// Untereinheiten; die ganze Rangliste nur, wenn der Veranstalter sie freigibt.
import type { Scope } from '../../api/entries.ts'
import { entryResultsApi } from '../../api/entryResults.ts'
import { useLoad } from '../../components/forms.ts'
import { t } from '../../i18n/index.ts'

export function EntryResultsCard({ org, call }: { org: Scope; call: number }) {
  const res = useLoad(() => entryResultsApi.get(org, call), [org, call])
  const data = res.data
  if (!data) return null
  return (
    <div className="card card-wide">
      <h2>{t('Ergebnisse')}</h2>
      {!data.final ? (
        <p className="muted">
          {t(
            'Der Wettbewerb ist noch nicht abgeschlossen ({x}). Die Ergebnisse erscheinen hier, sobald er endgültig ist.',
            {
              x: data.status_label,
            },
          )}
        </p>
      ) : (
        <>
          {!data.share_ranking && (
            <p className="muted small">
              {t(
                'Gezeigt sind eure Starter und Mannschaften mit ihrem Platz in der Gesamtwertung sowie die Wertung der Untereinheiten.',
              )}
            </p>
          )}
          {data.prizes.length > 0 && (
            <table className="table">
              <caption>{t('Preise')}</caption>
              <tbody>
                {data.prizes.map((p, i) => (
                  <tr key={i}>
                    <td>{p.name}</td>
                    <td>
                      {p.winner ?? ''}
                      {p.unit_name ? ` (${p.unit_name})` : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {data.scorings.map((s) => (
            <table className="table" key={s.name}>
              <caption>
                {s.name}
                {s.field ? ` · ${t('{n} gewertet', { n: s.field })}` : ''}
              </caption>
              <thead>
                <tr>
                  <th scope="col">{t('Platz')}</th>
                  <th scope="col">{t('Name')}</th>
                  <th scope="col" className="num">
                    {t('Ergebnis')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {s.rows.length === 0 && (
                  <tr>
                    <td colSpan={3} className="muted">
                      {t('Keine Werte.')}
                    </td>
                  </tr>
                )}
                {s.rows.map((r, i) => (
                  <tr key={i}>
                    <td>{r.place ? `${r.place}.` : '–'}</td>
                    <td>
                      {r.own ? <strong>{r.name}</strong> : r.name}
                      {r.unit_name && s.kind === 'einzel' ? (
                        <span className="muted"> ({r.unit_name})</span>
                      ) : null}
                      {r.members && <div className="muted small">{r.members.join(', ')}</div>}
                    </td>
                    <td className="num">{r.value_text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ))}
        </>
      )}
    </div>
  )
}
