import { describe, expect, it } from 'vitest'
import { cameraError } from './cameraError.ts'

describe('cameraError', () => {
  it('nennt den Grund verständlich', () => {
    expect(cameraError(new DOMException('x', 'NotAllowedError'), true)).toContain(
      'nicht freigegeben',
    )
    expect(cameraError(new DOMException('x', 'NotFoundError'), true)).toContain('keine Kamera')
    expect(cameraError(new DOMException('x', 'NotReadableError'), true)).toContain('belegt')
    expect(cameraError(new Error('x'), true)).toContain('Foto der Scheibe')
    expect(cameraError(null, false)).toContain('https')
  })
})
