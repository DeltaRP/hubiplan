// „Mein Konto“ oben rechts: klappt die Unterseiten auf (statt eines Eintrags in der Seitenleiste).
import { useEffect, useRef, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { ACCOUNT_SECTIONS, isAccountPath } from '../pages/settings/accountNav.ts'

export function AccountMenu() {
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()
  const ref = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  // Klick daneben oder Esc schließt
  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      buttonRef.current?.focus()
    }
    document.addEventListener('mousedown', onClick)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="account-menu" ref={ref}>
      <button
        type="button"
        ref={buttonRef}
        className={`button button-ghost${isAccountPath(pathname) ? ' active' : ''}`}
        aria-expanded={open}
        aria-controls="konto-menue"
        onClick={() => setOpen((o) => !o)}
      >
        Mein Konto <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <nav id="konto-menue" className="account-menu-list" aria-label="Mein Konto">
          <ul>
            {ACCOUNT_SECTIONS.map((s) => (
              <li key={s.to}>
                <NavLink to={s.to} end onClick={() => setOpen(false)}>
                  {s.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </div>
  )
}
