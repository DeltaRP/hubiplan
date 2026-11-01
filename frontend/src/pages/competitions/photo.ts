// Hilfen zur Fotoerkennung (Schießscheiben Schritt 4), getrennt von der Oberfläche.
import { ApiError } from '../../api/client.ts'
import type { PhotoResult } from '../../api/competitions.ts'
import type { PadHit } from './TargetPad.tsx'
import { t } from '../../i18n/index.ts'

const MAX_SIDE = 1600

/** Foto vor dem Hochladen verkleinern (spart Datenvolumen am Stand). */
export async function shrinkPhoto(file: Blob): Promise<Blob> {
  if (typeof createImageBitmap !== 'function') return file
  try {
    const bitmap = await createImageBitmap(file)
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height))
    if (scale === 1 && file.size < 3_000_000) return file
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bitmap.width * scale)
    canvas.height = Math.round(bitmap.height * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) return file
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    bitmap.close?.()
    const blob = await new Promise<Blob | null>((ok) => canvas.toBlob(ok, 'image/jpeg', 0.9))
    return blob ?? file
  } catch {
    return file
  }
}

export interface PhotoSuggestion {
  hits: PadHit[]
  needsReview: boolean
  note: string
  /** Schlüssel der bereitgelegten Spiegelausschnitte (nur mit Einwilligung des Vereins) */
  samples: string[]
}

export function toSuggestion(r: PhotoResult): PhotoSuggestion {
  return {
    hits: r.hits.map((h) => ({
      x: Number(h.x),
      y: Number(h.y),
      spot: h.spot ?? null,
      source: 'foto' as const,
    })),
    needsReview: r.needs_review,
    note: r.note,
    samples: (r.samples ?? []).map((s) => s.key),
  }
}

export function errorText(err: unknown): string {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    return t('Ohne Verbindung geht die Fotoerkennung nicht. Bitte die Treffer antippen.')
  }
  const msg = err instanceof ApiError ? err.fieldErrors.photo || err.message : ''
  return msg || t('Das Foto ließ sich nicht auswerten. Bitte die Treffer antippen.')
}
