// Zuschnitt im Browser: Bild drehen, spiegeln und den gewählten Ausschnitt als JPEG ausgeben.
// Der Server prüft und verarbeitet das Ergebnis noch einmal (Metadaten weg, feste Größen).

export interface PixelArea {
  x: number
  y: number
  width: number
  height: number
}

const MAX_OUTPUT = 1200
/** Größere Bilder lehnen wir ab, bevor der Browser sie vollständig dekodiert. */
export const MAX_PIXELS = 50_000_000
/** Längste Seite für die Bearbeitung; größere Bilder werden einmal verkleinert. */
export const EDIT_MAX_SIDE = 3000

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('Bild konnte nicht geladen werden.'))
    img.src = src
  })
}

function rotatedSize(width: number, height: number, degrees: number) {
  const rad = (degrees * Math.PI) / 180
  return {
    width: Math.abs(Math.cos(rad) * width) + Math.abs(Math.sin(rad) * height),
    height: Math.abs(Math.sin(rad) * width) + Math.abs(Math.cos(rad) * height),
  }
}

export interface CropOptions {
  /** Längste Seite des Ergebnisses in Pixeln (Standard 1200). */
  maxSide?: number
  /** Transparenz erhalten: Ergebnis als PNG, wenn das Bild durchsichtige Stellen hat. */
  keepTransparency?: boolean
}

/** true, wenn mindestens ein Pixel nicht voll deckend ist. */
export function hasTransparency(data: Uint8ClampedArray): boolean {
  for (let i = 3; i < data.length; i += 4) if (data[i] < 255) return true
  return false
}

export async function cropImage(
  src: string,
  area: PixelArea,
  rotation: number,
  flip: boolean,
  options: CropOptions = {},
): Promise<Blob> {
  const maxOutput = options.maxSide ?? MAX_OUTPUT
  const image = await loadImage(src)
  const bbox = rotatedSize(image.width, image.height, rotation)

  // 1. Ganzes Bild gedreht/gespiegelt auf eine Zwischenfläche zeichnen
  const stage = document.createElement('canvas')
  stage.width = Math.round(bbox.width)
  stage.height = Math.round(bbox.height)
  const ctx = stage.getContext('2d')
  if (!ctx) throw new Error('Canvas wird nicht unterstützt.')
  ctx.translate(stage.width / 2, stage.height / 2)
  ctx.rotate((rotation * Math.PI) / 180)
  ctx.scale(flip ? -1 : 1, 1)
  ctx.translate(-image.width / 2, -image.height / 2)
  ctx.drawImage(image, 0, 0)

  // 2. Ausschnitt in passender Größe übernehmen
  const scale = Math.min(1, maxOutput / Math.max(area.width, area.height))
  const out = document.createElement('canvas')
  out.width = Math.round(area.width * scale)
  out.height = Math.round(area.height * scale)
  const octx = out.getContext('2d')
  if (!octx) throw new Error('Canvas wird nicht unterstützt.')
  let type = 'image/jpeg'
  if (options.keepTransparency) {
    octx.drawImage(stage, area.x, area.y, area.width, area.height, 0, 0, out.width, out.height)
    if (hasTransparency(octx.getImageData(0, 0, out.width, out.height).data)) {
      type = 'image/png'
    } else {
      // Ohne durchsichtige Stellen reicht JPEG (deutlich kleiner)
      octx.globalCompositeOperation = 'destination-over'
      octx.fillStyle = '#ffffff'
      octx.fillRect(0, 0, out.width, out.height)
    }
  } else {
    octx.fillStyle = '#ffffff'
    octx.fillRect(0, 0, out.width, out.height)
    octx.drawImage(stage, area.x, area.y, area.width, area.height, 0, 0, out.width, out.height)
  }

  return new Promise((resolve, reject) =>
    out.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('Export fehlgeschlagen.'))),
      type,
      0.9,
    ),
  )
}

/** Wie stark ein Bild vor der Bearbeitung verkleinert wird (1 = gar nicht). */
export function editScale(width: number, height: number): number {
  if (width * height > MAX_PIXELS) {
    throw new Error('Das Bild hat zu viele Pixel (höchstens 50 Megapixel).')
  }
  return Math.min(1, EDIT_MAX_SIDE / Math.max(width, height))
}

/**
 * Bild für den Editor vorbereiten: Pixelzahl prüfen und große Bilder einmal auf
 * höchstens 3000 px verkleinern, damit Drehen und Zuschneiden nicht mit dem
 * vollen Original arbeiten. Gibt eine Objekt-URL zurück. Mit ``keepTransparency``
 * bleibt ein verkleinertes Bild PNG (z. B. Wappen mit durchsichtigem Hintergrund).
 */
export async function prepareImage(file: Blob, keepTransparency = false): Promise<string> {
  const url = URL.createObjectURL(file)
  try {
    const image = await loadImage(url)
    const scale = editScale(image.naturalWidth, image.naturalHeight)
    if (scale >= 1) return url
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(image.naturalWidth * scale)
    canvas.height = Math.round(image.naturalHeight * scale)
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('Canvas wird nicht unterstützt.')
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height)
    const small = await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (blob) =>
          blob ? resolve(blob) : reject(new Error('Bild konnte nicht verkleinert werden.')),
        keepTransparency ? 'image/png' : 'image/jpeg',
        0.92,
      ),
    )
    URL.revokeObjectURL(url)
    return URL.createObjectURL(small)
  } catch (err) {
    URL.revokeObjectURL(url)
    throw err
  }
}

/** Dateiname mit passender Endung zum Ergebnis */
export function croppedName(name: string, type: string): string {
  const base = name.replace(/\.[^./\\]*$/, '') || 'bild'
  return `${base}.${type === 'image/png' ? 'png' : 'jpg'}`
}
