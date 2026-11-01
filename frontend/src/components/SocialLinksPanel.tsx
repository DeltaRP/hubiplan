import { useState } from 'react'
import type { FormEvent } from 'react'
import { orgApi, SOCIAL_KINDS } from '../api/orgs.ts'
import type { SocialKind, SocialLink } from '../api/orgs.ts'
import { confirmDialog } from './dialog.ts'
import { errorMessage, useLoad } from './forms.ts'
import { Alert, Field, SelectField } from './ui.tsx'
import { t } from '../i18n/index.ts'

/** Social-Media-Kanäle einer Einheit (Stammdaten, z. B. für Briefvorlage und Webseite). */
export function SocialLinksPanel({ orgId, editable }: { orgId: number; editable: boolean }) {
  const { data, error, reload } = useLoad(() => orgApi.socialLinks(orgId), [orgId])
  const [kind, setKind] = useState<SocialKind>('instagram')
  const [url, setUrl] = useState('')
  const [label, setLabel] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const links = data ?? []

  async function run(action: () => Promise<unknown>) {
    setMessage(null)
    setBusy(true)
    try {
      await action()
      reload()
      return true
    } catch (err) {
      setMessage(errorMessage(err))
      return false
    } finally {
      setBusy(false)
    }
  }

  async function add(e: FormEvent) {
    e.preventDefault()
    if (!url.trim()) return
    const ok = await run(() => orgApi.createSocialLink(orgId, { kind, url: url.trim(), label }))
    if (ok) {
      setUrl('')
      setLabel('')
    }
  }

  async function remove(link: SocialLink) {
    const title = t('{kind_label} „{display}“ entfernen?', {
      kind_label: link.kind_label,
      display: link.display,
    })
    if (!(await confirmDialog({ title, confirmLabel: t('Entfernen') }))) return
    await run(() => orgApi.deleteSocialLink(orgId, link.id))
  }

  async function move(link: SocialLink, step: number) {
    const index = links.findIndex((l) => l.id === link.id)
    const other = links[index + step]
    if (!other) return
    await run(async () => {
      await orgApi.updateSocialLink(orgId, link.id, { position: other.position })
      await orgApi.updateSocialLink(orgId, other.id, { position: link.position })
    })
  }

  return (
    <div className="card card-wide">
      <h2>{t('Social Media')}</h2>
      <p className="muted small">
        {t(
          'Kanäle dieser Einheit. Sie können in der Fußzeile der Briefvorlage erscheinen, wenn das unter Einstellungen › Briefbogen eingeschaltet ist.',
        )}
      </p>
      {error && <Alert kind="error">{error}</Alert>}
      {message && <Alert kind="error">{message}</Alert>}
      {links.length === 0 && data && <p className="muted">{t('Noch keine Kanäle eingetragen.')}</p>}
      {links.length > 0 && (
        <ul className="plain-list">
          {links.map((link, i) => (
            <li key={link.id} className="role-row">
              <strong>{link.kind_label}</strong>{' '}
              <a href={link.url} target="_blank" rel="noreferrer noopener">
                {link.display}
              </a>
              {editable && (
                <span className="push-right">
                  <button
                    type="button"
                    className="link-button"
                    disabled={busy || i === 0}
                    aria-label={t('{kind_label} nach oben', { kind_label: link.kind_label })}
                    onClick={() => void move(link, -1)}
                  >
                    ↑
                  </button>{' '}
                  <button
                    type="button"
                    className="link-button"
                    disabled={busy || i === links.length - 1}
                    aria-label={t('{kind_label} nach unten', { kind_label: link.kind_label })}
                    onClick={() => void move(link, 1)}
                  >
                    ↓
                  </button>{' '}
                  <button
                    type="button"
                    className="link-button"
                    disabled={busy}
                    aria-label={t('{kind_label} entfernen', { kind_label: link.kind_label })}
                    onClick={() => void remove(link)}
                  >
                    {t('Entfernen')}
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {editable && (
        <form className="grid-3" onSubmit={add}>
          <SelectField
            label={t('Kanal')}
            value={kind}
            onChange={(e) => setKind(e.target.value as SocialKind)}
          >
            {SOCIAL_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </SelectField>
          <Field
            label={t('Adresse')}
            type="url"
            placeholder="https://"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <Field
            label={t('Anzeigename (optional)')}
            placeholder={t('z. B. @name')}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <div className="button-row">
            <button type="submit" className="button" disabled={busy || !url.trim()}>
              {t('Kanal hinzufügen')}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
