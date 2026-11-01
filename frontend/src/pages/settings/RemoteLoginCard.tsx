// Mein Konto: Zugänge gekoppelter HUBIplan-Instanzen verknüpfen (Verbund Schritt 7).
import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { leaveTo, ssoApi } from '../../api/peering.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, formatDateTime, useLoad } from '../../components/forms.ts'
import { Alert } from '../../components/ui.tsx'
import { t } from '../../i18n/index.ts'

const host = (url: string) => url.replace(/^https:\/\//, '')

export function RemoteLoginCard() {
  const { data, reload } = useLoad(() => ssoApi.account(), [])
  const { state } = useLocation()
  const [choice, setChoice] = useState('')
  const [error, setError] = useState<string | null>(null)
  if (!data) return null
  if (!data.login_enabled && data.links.length === 0 && data.accounts.length === 0) return null

  const selected = choice || data.linkable[0]?.instance_id || ''

  async function link() {
    setError(null)
    try {
      leaveTo.go((await ssoApi.start(selected, 'link', '/mein-konto/app')).url)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function unlink(id: number, url: string) {
    if (!(await confirmDialog(t('Verknüpfung mit {x} lösen?', { x: host(url) })))) return
    setError(null)
    try {
      await ssoApi.unlink(id)
      await reload()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function forget(id: number, url: string) {
    if (!(await confirmDialog(t('{x} aus der Einheitenauswahl entfernen?', { x: host(url) }))))
      return
    setError(null)
    try {
      await ssoApi.forget(id)
      await reload()
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <div className="card">
      <h2>{t('Anmelden über andere Instanzen')}</h2>
      <p className="muted small">
        {t(
          'Hast du auch auf einer gekoppelten HUBIplan-Instanz einen Zugang, verknüpfe ihn hier einmal. Danach meldest du dich hier mit dem Zugang dort an. Rechte ändert das nicht. Nutzt du hier die Zwei-Faktor-Anmeldung, brauchst du sie auch dort.',
        )}
      </p>
      {(state as { linked?: boolean } | null)?.linked && (
        <Alert kind="success">{t('Verknüpft.')}</Alert>
      )}
      {data.links.length > 0 && (
        <ul className="plain-list">
          {data.links.map((l) => (
            <li key={l.id}>
              {t('Anmelden mit {x} ({email})', { x: host(l.base_url), email: l.email })}
              {l.last_used_at && (
                <span className="muted small">
                  {' '}
                  {t('· zuletzt')} {formatDateTime(l.last_used_at)}
                </span>
              )}{' '}
              <button
                type="button"
                className="button button-ghost"
                onClick={() => void unlink(l.id, l.base_url)}
              >
                {t('Lösen')}
              </button>
            </li>
          ))}
        </ul>
      )}
      {data.linkable.length > 0 && (
        <div className="button-row">
          <label className="field">
            <span>{t('Instanz')}</span>
            <select value={selected} onChange={(e) => setChoice(e.target.value)}>
              {data.linkable.map((p) => (
                <option key={p.instance_id} value={p.instance_id}>
                  {host(p.base_url)}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="button" onClick={() => void link()}>
            {t('Zugang verknüpfen')}
          </button>
        </div>
      )}
      {data.accounts.length > 0 && (
        <>
          <h3>{t('Deine Zugänge auf anderen Instanzen')}</h3>
          <p className="muted small">{t('Sie stehen auch in der Einheitenauswahl oben.')}</p>
          <ul className="plain-list">
            {data.accounts.map((a) => (
              <li key={a.id}>
                <a href={a.url}>
                  {host(a.base_url)} {t('öffnen')}
                </a>{' '}
                <button
                  type="button"
                  className="button button-ghost"
                  onClick={() => void forget(a.id, a.base_url)}
                >
                  {t('Entfernen')}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}
