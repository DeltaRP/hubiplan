// Listen zum Sortieren per Ziehen; die Logik steckt in useSortable.tsx.
import type { ReactNode } from 'react'
import { useSortable } from './useSortable.tsx'
import type { SortableOptions } from './useSortable.tsx'
import { t } from '../i18n/index.ts'

export function GripIcon() {
  return (
    <svg viewBox="0 0 10 16" width="10" height="16" aria-hidden="true" focusable="false">
      {[3, 8, 13].map((y) => (
        <g key={y}>
          <circle cx="2.5" cy={y} r="1.5" />
          <circle cx="7.5" cy={y} r="1.5" />
        </g>
      ))}
    </svg>
  )
}

/** Einfache Liste zum Sortieren (Name und optional ein Zusatz je Zeile). */
export function SortableList<T>({
  render,
  ariaLabel,
  ...options
}: SortableOptions<T> & { render?: (item: T) => ReactNode; ariaLabel: string }) {
  const s = useSortable(options)
  return (
    <>
      <ul className="sortable-list" aria-label={ariaLabel}>
        {s.ordered.map((item) => {
          const { ref, className } = s.rowProps(item)
          return (
            <li key={options.id(item)} ref={ref} className={className}>
              {s.handle(item)}
              <div className="sortable-label">{render ? render(item) : options.label(item)}</div>
            </li>
          )
        })}
      </ul>
      {s.status}
    </>
  )
}

/** Hinweis über einer sortierbaren Liste */
export function SortHint({ website = false }: { website?: boolean }) {
  return (
    <p className="muted small sort-hint">
      {t('Reihenfolge ändern: am Griff')} <GripIcon />{' '}
      {t('ziehen oder den Griff anklicken und die Pfeiltasten nutzen.')}
      {website && t(' Sie gilt auch für die Webseite.')}
    </p>
  )
}
