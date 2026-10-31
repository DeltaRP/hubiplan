// Startseiten-Kachel „Offene Aufgaben“: Vorgänge, die eine Entscheidung brauchen.
import { Link } from 'react-router-dom'
import { orgApi } from '../api/orgs.ts'
import type { OrgSummary } from '../api/orgs.ts'
import { LoadError } from './ui.tsx'
import { useLoad } from './forms.ts'

export function OpenTasksTile({ org }: { org: OrgSummary }) {
  const { data, error, reload } = useLoad(() => orgApi.openTasks(org.id), [org.id])
  const items = data?.items ?? []
  return (
    <div className="card tile">
      <h2>
        Offene Aufgaben
        {items.length > 0 && <span className="badge"> {items.length}</span>}
      </h2>
      {error && (
        <LoadError message="Die offenen Aufgaben konnten nicht geladen werden." onRetry={reload} />
      )}
      {data && items.length === 0 && <p className="muted">Zurzeit ist nichts zu entscheiden.</p>}
      {items.length > 0 && (
        <ul className="plain-list task-list">
          {items.map((t, i) => (
            <li key={`${t.kind}-${i}`}>
              <span className="muted small">{t.kind_label}</span>
              <div>
                <Link to={t.link}>{t.title}</Link>
                <span className="muted small"> · {t.detail}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
