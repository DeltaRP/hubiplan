// Mitgliederbereich: „Meine Ergebnisse“ (Wettbewerbe Schritt 5) – eigene Starts mit Platz
// und Wert, Titel und Auszeichnungen über alle Jahre.
import { historyApi } from '../../api/competitionHistory.ts'
import { formatDate, useLoad } from '../../components/forms.ts'
import { Alert } from '../../components/ui.tsx'
import { t } from '../../i18n/index.ts'

export function PortalResults({ accessId }: { accessId: number }) {
  const { data, error } = useLoad(() => historyApi.mine(accessId), [accessId])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  if (data.starts.length === 0 && data.grants.length === 0)
    return (
      <p className="muted">
        {t('Noch keine Ergebnisse. Sobald du bei einem Wettbewerb antrittst, steht es hier.')}
      </p>
    )
  return (
    <>
      {data.grants.length > 0 && (
        <>
          <h2>{t('Titel und Auszeichnungen')}</h2>
          <ul className="plain-list">
            {data.grants.map((g) => (
              <li key={g.id}>
                <strong>{g.full_title || g.trophy_name}</strong>
                {g.place ? ` · ${t('Platz {n}', { n: g.place })}` : ''}
                {g.competition_title ? ` · ${g.competition_title}` : ''}
              </li>
            ))}
          </ul>
        </>
      )}
      <h2>{t('Starts')}</h2>
      <ul className="plain-list">
        {data.starts.map((s) => (
          <li key={s.competition}>
            <strong>{s.title}</strong> · {formatDate(s.date)}
            {s.status !== 'endgueltig' && <span className="muted"> · {s.status_label}</span>}
            {s.results.map((r) => (
              <div key={r.scoring} className="muted">
                {[
                  r.scoring,
                  r.place
                    ? r.field
                      ? t('Platz {place} von {n}', { place: r.place, n: r.field })
                      : t('Platz {n}', { n: r.place })
                    : '',
                  r.value_text,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </div>
            ))}
          </li>
        ))}
      </ul>
    </>
  )
}
