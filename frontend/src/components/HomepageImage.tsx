import { useState } from 'react'
import type { ChangeEvent } from 'react'
import { api } from '../api/client.ts'
import { orgApi } from '../api/orgs.ts'
import { errorMessage } from './forms.ts'
import { useImageCrop } from './ImageCrop.tsx'
import { RightsHint } from './RightsHint.tsx'
import { Alert } from './ui.tsx'
import { t } from '../i18n/index.ts'

/**
 * Vorschaubild der Homepage einer Untereinheit (Ralf 31.10.): HUBIplan holt es einmal
 * von der Homepage (og:image). Liefert sie keins oder passt es nicht, lädt man ein
 * eigenes hoch; Entfernen holt wieder das Bild der Homepage.
 */
export function HomepageImage({
  orgId,
  depId,
  imageUrl,
  custom,
  onChange,
}: {
  orgId: number
  depId: number
  imageUrl: string | null
  custom: boolean
  onChange: () => void | Promise<void>
}) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Antwort von „Neu von der Homepage holen“: warum kein Bild kam
  const [note, setNote] = useState<string | null>(null)
  const crop = useImageCrop({ title: t('Ausschnitt für das Bild der Homepage'), maxSide: 1200 })
  const url = orgApi.departmentHomepageImageUrl(orgId, depId)

  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    setNote(null)
    try {
      await action()
      await onChange()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const chosen = e.target.files?.[0]
    e.target.value = ''
    if (!chosen) return
    const file = await crop.pick(chosen)
    if (!file) return
    await run(() => orgApi.uploadHomepageImage(url, file))
  }

  return (
    <div className="logo-upload-box" data-testid="homepage-image">
      <p className="muted small">
        {t('Bild für die Karte „Homepage“ auf der Webseite.')}{' '}
        {custom
          ? t('Eigenes Bild.')
          : imageUrl
            ? t('Von der Homepage übernommen.')
            : t('Noch kein Bild. Hol es von der Homepage oder lade ein eigenes hoch.')}
      </p>
      {imageUrl && <img src={imageUrl} alt={t('Bild der Homepage')} className="homepage-preview" />}
      <div className="button-row">
        <label className="button button-ghost">
          {custom ? t('Anderes Bild wählen') : t('Eigenes Bild hochladen')}
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="file-input"
            disabled={busy}
            onChange={upload}
          />
        </label>
        {crop.dialog}
        <RightsHint />
        <button
          type="button"
          className="button button-ghost"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              const res = (await api.del(url)) as { message?: string } | null
              if (res?.message) setNote(res.message)
            })
          }
        >
          {busy
            ? t('Wird geholt …')
            : custom
              ? t('Eigenes Bild entfernen')
              : t('Neu von der Homepage holen')}
        </button>
      </div>
      {note && (
        <Alert kind="info">
          {note} {t('Du kannst ein eigenes Bild hochladen.')}
        </Alert>
      )}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}
