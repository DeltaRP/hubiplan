import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { SubNavContext, buildNavTree } from './subnav.ts'
import type { NavNode, SubNavItem } from './subnav.ts'
import { formatTitle, useTitleOverride } from './pageTitle.ts'
import { confirmLeave } from './leaveGuard.ts'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext.tsx'
import { modules } from '../modules.tsx'
import { displayName } from '../api/orgs.ts'
import { leaveTo, ssoApi } from '../api/peering.ts'
import type { SsoAccount } from '../api/peering.ts'
import { useOrg } from '../org/OrgContext.tsx'
import { AppFooter } from './ImprintFooter.tsx'
import { Logo } from './Logo.tsx'
import { UndoControls } from './UndoControls.tsx'
import { useUndo } from './undo.ts'
import { alertDialog } from './dialog.ts'
import { preloadPagesGently } from '../lazyPages.ts'
import { PageErrorBoundary } from './PageErrorBoundary.tsx'
import { LearningProvider } from '../learning/LearningContext.tsx'
import { ACCOUNT_PATH, accountSectionLabel } from '../pages/settings/accountNav.ts'
import { AccountMenu } from './AccountMenu.tsx'
import { RolePreviewBanner, RolePreviewSelect } from './RolePreview.tsx'
import { rolePreviewApi } from '../api/orgs.ts'
import { locale } from '../i18n/index.ts'
import { t } from '../i18n/index.ts'

// Seiten außerhalb der Bereiche in der Seitenleiste
const OTHER_PAGES: Record<string, string> = {
  '/mein-konto': t('Mein Konto'),
  '/glossar': t('Glossar'),
  '/briefvorlage': t('Briefvorlage'),
}

export function Layout() {
  const { user, logout } = useAuth()
  const {
    orgs,
    departments,
    portal,
    active,
    activeKey,
    activeDept,
    activePortal,
    select,
    loading,
    refresh,
  } = useOrg()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [navOpen, setNavOpen] = useState(false)
  // Unterpunkte der aktuellen Seite (früher Reiter), siehe subnav.ts
  const [subNav, setSubNav] = useState<Record<string, SubNavItem[]>>({})
  const setSub = useCallback((id: string, items: SubNavItem[] | null) => {
    setSubNav((old) => {
      if (items === null) {
        if (!(id in old)) return old
        const rest = { ...old }
        delete rest[id]
        return rest
      }
      if (JSON.stringify(old[id]) === JSON.stringify(items)) return old
      return { ...old, [id]: items }
    })
  }, [])
  const subNavApi = useMemo(() => ({ set: setSub }), [setSub])
  const toggleRef = useRef<HTMLButtonElement>(null)
  const navRef = useRef<HTMLElement>(null)

  // Übrige Bereiche nach der Anmeldung im Hintergrund nachladen, damit spätere
  // Seitenwechsel ohne Wartezeit gehen
  useEffect(() => {
    let stop = () => undefined as void
    const timer = setTimeout(() => {
      stop = preloadPagesGently()
    }, 2000)
    return () => {
      clearTimeout(timer)
      stop()
    }
  }, [])

  // Ausgeklappte Navigation (Handy): Fokus hinein, Esc schließt, Fokus zurück zum Knopf.
  // Der Fokus wandert erst nach dem Rendern, wenn Kopf und Inhalt nicht mehr „inert“
  // sind; nach der Wahl eines Bereichs auf den neuen Inhalt (UI-Audit NUI-01).
  const focusAfterClose = useRef<'toggle' | 'main' | null>(null)
  useEffect(() => {
    if (navOpen) {
      navRef.current?.querySelector<HTMLElement>('a, button')?.focus()
      const onKey = (e: KeyboardEvent) => {
        if (e.key !== 'Escape') return
        focusAfterClose.current = 'toggle'
        setNavOpen(false)
      }
      window.addEventListener('keydown', onKey)
      return () => window.removeEventListener('keydown', onKey)
    }
    const target = focusAfterClose.current
    focusAfterClose.current = null
    if (target === 'toggle') toggleRef.current?.focus()
    else if (target === 'main') document.getElementById('inhalt')?.focus()
  }, [navOpen])

  // Seitenwechsel (anderer Pfad): Fokus auf die Überschrift der neuen Seite, damit
  // Screenreader den Wechsel ansagen und Tastaturnutzer oben im Inhalt weitermachen
  // (WCAG 2.4.3). Ein Eingabefeld, das die Seite selbst fokussiert, bleibt fokussiert.
  const firstPath = useRef(true)
  useEffect(() => {
    if (firstPath.current) {
      firstPath.current = false
      return
    }
    let tries = 0
    const timer = setInterval(() => {
      const main = document.getElementById('inhalt')
      const heading = main?.querySelector<HTMLElement>('h1')
      if (!heading && ++tries < 20) return
      clearInterval(timer)
      if (!main) return
      const current = document.activeElement
      if (
        current instanceof HTMLElement &&
        main.contains(current) &&
        current.matches('input, select, textarea')
      )
        return
      const target = heading ?? main
      if (target !== main && !target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1')
      target.focus({ preventScroll: true })
    }, 50)
    return () => clearInterval(timer)
  }, [pathname])

  // Verknüpfte Zugänge auf anderen Instanzen (Verbund): stehen mit in der Einheitenauswahl
  const [remoteAccounts, setRemoteAccounts] = useState<SsoAccount['accounts']>([])
  useEffect(() => {
    let alive = true
    ssoApi
      .account()
      .then((d) => alive && setRemoteAccounts(d.accounts))
      .catch(() => alive && setRemoteAccounts([]))
    return () => {
      alive = false
    }
  }, [])

  // Breiter als der Handy-Umbruch: Navigation steht fest, also zuklappen
  useEffect(() => {
    const wide = window.matchMedia?.('(min-width: 801px)')
    if (!wide) return
    const onChange = () => wide.matches && setNavOpen(false)
    wide.addEventListener?.('change', onChange)
    return () => wide.removeEventListener?.('change', onChange)
  }, [])

  function closeNav() {
    focusAfterClose.current = 'toggle'
    setNavOpen(false)
  }
  function choseInNav() {
    if (navOpen) focusAfterClose.current = 'main'
    setNavOpen(false)
  }
  // Nach Rückgängig/Wiederherstellen lädt die Seite ihre Daten neu
  const undoBase = active
    ? `/api/orgs/${active.id}`
    : activeDept
      ? `/api/depts/${activeDept.id}`
      : null
  const { version } = useUndo(undoBase)

  // Ansicht als Rolle: nach dem Wechsel Rechte neu laden und die Seite neu aufbauen
  const [previewVersion, setPreviewVersion] = useState(0)
  const previewOrg = orgs.find((o) => o.role_preview?.active) ?? null
  const previewChanged = useCallback(async () => {
    await refresh()
    setPreviewVersion((v) => v + 1)
  }, [refresh])

  async function handleLogout() {
    try {
      await logout()
    } catch {
      await alertDialog({
        title: t('Abmelden hat nicht geklappt'),
        message: t(
          'Der Server hat die Abmeldung nicht bestätigt. Sie sind noch angemeldet. Bitte erneut versuchen.',
        ),
      })
      return
    }
    navigate('/anmelden')
  }

  async function switchOrg(key: string) {
    // Erst Offenes speichern; scheitert das und bleibt man, ändert sich nichts (NMF-01)
    if (!(await confirmLeave())) return
    const remote = remoteAccounts.find((a) => `r:${a.id}` === key)
    if (remote) {
      // Einheit auf einer anderen Instanz: dort gleich über diese Instanz angemeldet
      leaveTo.go(remote.url)
      return
    }
    // Die Ansicht als Rolle gilt nur in ihrer Einheit: beim Wechsel endet sie
    if (previewOrg && key !== String(previewOrg.id)) {
      try {
        await rolePreviewApi.stop(previewOrg.id)
        await refresh()
      } catch {
        // Ohne Antwort bleibt die Ansicht bestehen; der Hinweis zeigt sie weiter
      }
    }
    select(key)
    setNavOpen(false)
    navigate('/')
  }

  const visible = modules.filter((m) =>
    m.visible(active, { dept: activeDept, portal: activePortal }),
  )
  const contextCount = orgs.length + departments.length + portal.length + remoteAccounts.length
  // Im Kopf steht immer der volle Name, der Kurzname nur in der Auswahl.
  const brandName = active?.name ?? activeDept?.name ?? activePortal?.club_name ?? 'HUBIplan'
  const brandLogo =
    active?.theme.logo_url ?? activeDept?.theme.logo_url ?? activePortal?.theme.logo_url ?? null

  // Seitentitel im Browser-Tab: Bereich · Arbeitsbereich · HUBIplan (WCAG 2.4.2)
  const pageLabel = (() => {
    const matches = (path: string) => pathname === path || pathname.startsWith(`${path}/`)
    const mod = visible
      .filter((m) => matches(m.path))
      .sort((a, b) => b.path.length - a.path.length)[0]
    if (!mod) {
      const section = accountSectionLabel(pathname)
      if (section && pathname !== ACCOUNT_PATH) return t('{section} · Mein Konto', { section })
      return OTHER_PAGES[pathname] ?? null
    }
    const sub = mod
      .children?.(active)
      .filter((c) => c.to !== mod.path && matches(c.to))
      .sort((a, b) => b.to.length - a.to.length)[0]
    const modLabel =
      mod.id === 'abteilung' && activeDept
        ? activeDept.label
        : (mod.labelFor?.(active) ?? mod.label)
    return sub ? t('{label} · {modLabel}', { label: sub.label, modLabel }) : modLabel
  })()
  const titleOverride = useTitleOverride()
  useEffect(() => {
    document.title = formatTitle(
      titleOverride ?? pageLabel,
      brandName !== 'HUBIplan' ? brandName : null,
    )
  }, [titleOverride, pageLabel, brandName])

  // Lernhilfen nur in der Oberfläche der Bearbeitenden, nie im Mitgliederbereich
  // Unterpunkte als verschachtelte Liste; tiefere Ebenen nur unter dem aktiven Punkt
  const renderNav = (nodes: NavNode[], level = 1): ReactNode =>
    nodes.length > 0 && (
      <ul className={`sidebar-sub${level > 1 ? ' sidebar-sub-deep' : ''}`}>
        {nodes.map((c) => (
          <li key={c.to}>
            <NavLink to={c.to} end={c.end} className="sidebar-sublink" onClick={choseInNav}>
              {c.label}
            </NavLink>
            {c.children.length > 0 &&
              (pathname === c.to || pathname.startsWith(`${c.to}/`) || level > 1) &&
              renderNav(c.children, level + 1)}
          </li>
        ))}
      </ul>
    )

  return (
    <SubNavContext.Provider value={subNavApi}>
      <LearningProvider off={!active && !activeDept}>
        <div className={`app-shell${navOpen ? ' nav-open' : ''}`}>
          <a href="#inhalt" className="skip-link">
            {t('Zum Inhalt springen')}
          </a>
          <header className="topbar" inert={navOpen || undefined}>
            <button
              type="button"
              className="nav-toggle"
              ref={toggleRef}
              aria-label={navOpen ? t('Navigation schließen') : t('Navigation öffnen')}
              aria-expanded={navOpen}
              aria-controls="hauptnavigation"
              onClick={() => setNavOpen((o) => !o)}
            >
              <span />
              <span />
              <span />
            </button>
            <NavLink to="/" className="topbar-brand">
              <Logo name={brandName} logoUrl={brandLogo} />
            </NavLink>
            <div className="topbar-user">
              {undoBase && !previewOrg && <UndoControls base={undoBase} />}
              {active && <RolePreviewSelect org={active} onChanged={previewChanged} />}
              {contextCount > 1 && (
                <label className="org-switch">
                  <span className="sr-only">{t('Organisation wechseln')}</span>
                  <select
                    value={activeKey ?? ''}
                    onChange={(e) => void switchOrg(e.target.value)}
                    aria-label={t('Organisation wechseln')}
                  >
                    {orgs.map((o) => (
                      <option key={o.id} value={String(o.id)}>
                        {displayName(o)} ({o.type_label})
                      </option>
                    ))}
                    {departments.map((d) => (
                      <option key={`d${d.id}`} value={`d:${d.id}`}>
                        {d.path?.includes('›') ? d.path : displayName(d)} (
                        {d.club_display_name || d.club_name})
                      </option>
                    ))}
                    {portal.map((p) => (
                      <option key={`p${p.id}`} value={`p:${p.id}`}>
                        {t('Meine Daten: {first_name} (', { first_name: p.first_name })}
                        {p.club_display_name || p.club_name})
                      </option>
                    ))}
                    {remoteAccounts.length > 0 && (
                      <optgroup label={t('Auf anderen Instanzen')}>
                        {remoteAccounts.map((a) => (
                          <option key={`r${a.id}`} value={`r:${a.id}`}>
                            {a.base_url.replace(/^https:\/\//, '')} {t('öffnen')}
                          </option>
                        ))}
                      </optgroup>
                    )}
                  </select>
                </label>
              )}
              <span className="topbar-email">{user?.email}</span>
              <AccountMenu />
              <button type="button" className="button button-ghost" onClick={handleLogout}>
                {t('Abmelden')}
              </button>
            </div>
          </header>

          <nav className="sidebar" id="hauptnavigation" aria-label={t('Module')} ref={navRef}>
            <button type="button" className="sidebar-close" onClick={closeNav}>
              <span aria-hidden="true">×</span> {t('Navigation schließen')}
            </button>
            <ul>
              {visible.map((m) => (
                <li key={m.id}>
                  <NavLink
                    to={m.path}
                    end={m.path === '/'}
                    className="sidebar-link"
                    onClick={choseInNav}
                  >
                    {m.icon}
                    <span>
                      {m.id === 'abteilung' && activeDept
                        ? activeDept.label
                        : (m.labelFor?.(active) ?? m.label)}
                    </span>
                  </NavLink>
                  {(pathname === m.path || pathname.startsWith(`${m.path}/`)) &&
                    renderNav(
                      buildNavTree(m.path, m.children?.(active) ?? [], Object.values(subNav)),
                    )}
                </li>
              ))}
            </ul>
            {/* Immer am selben Ort erreichbar, unabhängig vom Modul (UI-Audit H-NUI-C) */}
            <div className="sidebar-help">
              <NavLink to="/glossar" className="sidebar-link" onClick={choseInNav}>
                <svg
                  viewBox="0 0 24 24"
                  width="20"
                  height="20"
                  aria-hidden="true"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <circle cx="12" cy="12" r="9" />
                  <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17.5h.01" />
                </svg>
                <span>{t('Hilfe & Glossar')}</span>
              </NavLink>
            </div>
          </nav>
          <div className="sidebar-backdrop" aria-hidden="true" onClick={closeNav} />

          <main className="content" id="inhalt" tabIndex={-1} inert={navOpen || undefined}>
            {previewOrg && <RolePreviewBanner org={previewOrg} onChanged={previewChanged} />}
            {user?.mfa_required_by && (
              <MfaNotice by={user.mfa_required_by} overdue={!!user.mfa_overdue} />
            )}
            {loading ? (
              <p className="muted" role="status">
                {t('Lädt …')}
              </p>
            ) : (
              <PageErrorBoundary resetKey={pathname}>
                <Suspense
                  fallback={
                    <p className="muted" role="status">
                      {t('Lädt …')}
                    </p>
                  }
                >
                  <Outlet key={`${version}-${previewVersion}`} />
                </Suspense>
              </PageErrorBoundary>
            )}
            <AppFooter />
          </main>
        </div>
      </LearningProvider>
    </SubNavContext.Provider>
  )
}

/** Pflicht-2FA für heikle Rechte (Gesamtaudit 31.10.b, Frage 1). */
function MfaNotice({ by, overdue }: { by: string; overdue: boolean }) {
  const date = new Date(by).toLocaleDateString(locale())
  return (
    <div className={overdue ? 'alert alert-error' : 'alert alert-info'} role="status">
      {overdue
        ? t(
            'Rollenverwaltung, vollständige Exporte und das Buchen in der Kasse ruhen, bis du die Zwei-Faktor-Anmeldung einrichtest. ',
          )
        : t(
            'Für deine Rechte (Rollen, Exporte oder Kasse) brauchst du ab dem {date} die Zwei-Faktor-Anmeldung. ',
            { date },
          )}
      <NavLink to="/mein-konto/anmeldung">{t('Jetzt einrichten')}</NavLink>
    </div>
  )
}
