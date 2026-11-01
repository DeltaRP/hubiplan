// Ansicht als Rolle: HUBIplan so ansehen, wie eine Rolle der Einheit es sieht.
// Nur lesen und nie mehr als die eigenen Rechte (Server: access/preview.py).
import { useEffect, useState } from 'react'
import { rolePreviewApi } from '../api/orgs.ts'
import type { OrgSummary, RolePreviewRole } from '../api/orgs.ts'
import { ApiError } from '../api/client.ts'
import { alertDialog } from './dialog.ts'
import { t } from '../i18n/index.ts'

async function report(err: unknown) {
  await alertDialog({
    title: t('Ansicht als Rolle'),
    message: err instanceof ApiError ? err.message : t('Das hat nicht geklappt.'),
  })
}

/** Auswahl in der Kopfleiste; erscheint nur mit dem Recht „Ansicht als Rolle“. */
export function RolePreviewSelect({
  org,
  onChanged,
}: {
  org: OrgSummary
  onChanged: () => Promise<void> | void
}) {
  const preview = org.role_preview
  const available = !!preview?.available
  const active = preview?.active ?? null
  const [roles, setRoles] = useState<RolePreviewRole[]>(active ? [active] : [])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!available) return
    let alive = true
    rolePreviewApi
      .get(org.id)
      .then((s) => alive && setRoles(s.roles))
      .catch(() => alive && setRoles([]))
    return () => {
      alive = false
    }
  }, [org.id, available])

  if (!available) return null

  async function choose(value: string) {
    setBusy(true)
    try {
      if (value === '') await rolePreviewApi.stop(org.id)
      else await rolePreviewApi.start(org.id, Number(value))
      await onChanged()
    } catch (err) {
      await report(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <label className="org-switch role-preview-switch">
      <span className="sr-only">{t('Ansicht als Rolle')}</span>
      <select
        value={active ? String(active.id) : ''}
        onChange={(e) => void choose(e.target.value)}
        aria-label={t('Ansicht als Rolle')}
        disabled={busy}
      >
        <option value="">{t('Eigene Ansicht')}</option>
        {roles.map((r) => (
          <option key={r.id} value={String(r.id)}>
            {t('Ansicht als')} {r.name}
          </option>
        ))}
      </select>
    </label>
  )
}

/** Deutlicher Hinweis über dem Inhalt, solange eine Rolle gewählt ist. */
export function RolePreviewBanner({
  org,
  onChanged,
}: {
  org: OrgSummary
  onChanged: () => Promise<void> | void
}) {
  const [busy, setBusy] = useState(false)
  const active = org.role_preview?.active
  if (!active) return null

  async function end() {
    setBusy(true)
    try {
      await rolePreviewApi.stop(org.id)
      await onChanged()
    } catch (err) {
      await report(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="role-preview-banner" role="status">
      <p>
        <strong>{t('Ansicht als „{name}“', { name: active.name })}</strong>
        {t(
          ': So sieht jemand mit dieser Rolle HUBIplan, soweit du die Rechte selbst hast. Ändern ist ausgeschaltet.',
        )}
      </p>
      <button type="button" className="button" onClick={() => void end()} disabled={busy}>
        {t('Ansicht beenden')}
      </button>
    </div>
  )
}
