// Kleine Strich-Icons und Icon-Knöpfe für Tabellenzeilen (Bearbeiten, Löschen …).
import type { ButtonHTMLAttributes, ReactNode } from 'react'

function Svg({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  )
}

export const EditIcon = () => (
  <Svg>
    <path d="M15 4l5 5L9 20H4v-5Z" />
    <path d="M12.5 6.5l5 5" />
  </Svg>
)

export const DeleteIcon = () => (
  <Svg>
    <path d="M4 7h16" />
    <path d="M9 7V4.5h6V7" />
    <path d="M6.5 7l1 13h9l1-13" />
    <path d="M10.5 10.5v6M13.5 10.5v6" />
  </Svg>
)

export const ViewIcon = () => (
  <Svg>
    <path d="M2.5 12C5 7.5 8.3 5.5 12 5.5s7 2 9.5 6.5c-2.5 4.5-5.8 6.5-9.5 6.5S5 16.5 2.5 12Z" />
    <circle cx="12" cy="12" r="2.5" />
  </Svg>
)

export const RestoreIcon = () => (
  <Svg>
    <path d="M5 8.2A8 8 0 1 1 4.1 13.3" />
    <path d="M4 4v4.5h4.5" />
  </Svg>
)

/** Knopf nur mit Icon; `label` ist Tooltip und Name für Screenreader. */
export function IconButton({
  label,
  icon,
  danger = false,
  className,
  ...rest
}: {
  label: string
  icon: ReactNode
  danger?: boolean
} & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'>) {
  return (
    <button
      type="button"
      className={`icon-button${danger ? ' icon-button-danger' : ''}${className ? ` ${className}` : ''}`}
      aria-label={label}
      title={label}
      {...rest}
    >
      {icon}
    </button>
  )
}
