// Prüfliste vor einer folgenreichen Aktion. Blockiert nie: nur echte Fehler,
// die der Server meldet, halten eine Aktion auf.
import { Link } from 'react-router-dom'
import { Why } from './Aids.tsx'
import type { CheckItem } from './checks.ts'
import { useLearning } from './LearningContext.tsx'

export function Checklist({ title, items }: { title: string; items: CheckItem[] }) {
  const learning = useLearning()
  if (!learning || items.length === 0) return null
  const counted = items.filter((i) => !i.info)
  const done = counted.filter((i) => i.ok).length
  return (
    <section className="checklist" aria-label={title}>
      <h3 className="checklist-title">{title}</h3>
      {counted.length > 0 && (
        <p className="checklist-count muted small">
          {done} von {counted.length} Punkten erledigt
        </p>
      )}
      <ul className="checklist-items">
        {items.map((item) => (
          <li
            key={item.key}
            className={`checklist-item ${item.info ? 'is-info' : item.ok ? 'is-ok' : 'is-open'}`}
          >
            <span className="checklist-mark" aria-hidden="true">
              {item.info ? 'i' : item.ok ? '✓' : '!'}
            </span>
            <span className="checklist-text">
              <span className="sr-only">
                {item.info ? 'Hinweis: ' : item.ok ? 'Erledigt: ' : 'Offen: '}
              </span>
              {item.text}
              {!item.ok && item.fix && <span className="checklist-fix">{item.fix}</span>}
              {!item.ok && item.to && (
                <Link className="checklist-link" to={item.to}>
                  Zur Stelle
                </Link>
              )}
              {(!item.ok || item.info) && item.why && <Why k={item.why} />}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
