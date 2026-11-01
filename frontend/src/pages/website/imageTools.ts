// Hilfen für die Bilder der Webseite (Übersicht, Bearbeiten, Auswahl in images.tsx).
import { useState } from 'react'
import { ApiError } from '../../api/client.ts'
import { contentApi } from '../../api/website.ts'
import type { WebsiteImage } from '../../api/website.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage } from '../../components/forms.ts'
import { useImageCrop } from '../../components/ImageCrop.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'

export function imageLabel(i: WebsiteImage): string {
  return i.caption || i.alt_text || 'ohne Beschriftung'
}

export function needsAlt(i: WebsiteImage): boolean {
  return !i.alt_text && !i.decorative
}

/** Bilder hochladen: je Datei Zuschnitt, dann mit Original und Ausschnitt speichern. */
export function useImageUpload() {
  const org = useActiveOrg()
  const crop = useImageCrop()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function upload(
    files: File[],
    extra: { department?: number | null; alt_text?: string } = {},
  ): Promise<WebsiteImage[]> {
    setError(null)
    const done: WebsiteImage[] = []
    for (const file of files) {
      const result = await crop.pickArea(file)
      if (!result) continue
      setBusy(true)
      try {
        done.push(
          await contentApi.upload(org.id, {
            file: result.file,
            original: result.crop ? file : null,
            crop: result.crop,
            department: extra.department ?? null,
            alt_text: extra.alt_text,
          }),
        )
      } catch (err) {
        setError(`${file.name}: ${errorMessage(err)}`)
      } finally {
        setBusy(false)
      }
    }
    return done
  }

  return { upload, busy, error, dialog: crop.dialog }
}

/** Löschen mit Rückfrage; wird das Bild verwendet, nennt die zweite Rückfrage die Stellen. */
export async function removeImage(orgId: number, image: WebsiteImage): Promise<boolean> {
  const ok = await confirmDialog({ title: 'Bild löschen?', confirmLabel: 'Löschen' })
  if (!ok) return false
  try {
    await contentApi.removeImage(orgId, image.id)
    return true
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 409) throw err
    const again = await confirmDialog({
      title: 'Bild trotzdem löschen?',
      message: err.message,
      confirmLabel: 'Trotzdem löschen',
    })
    if (!again) return false
    await contentApi.removeImage(orgId, image.id, true)
    return true
  }
}
