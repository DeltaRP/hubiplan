// Mein Konto › Briefvorlage & Unterschrift: einmal hinterlegen, dann ist sie bei Quittungen vorbelegt.
import { useState } from 'react'
import { signatureApi } from '../../api/finance.ts'
import type { SignatureInput } from '../../api/finance.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, formatDateTime, useLoad } from '../../components/forms.ts'
import { SignatureFullscreen, SignatureImage } from '../../components/SignaturePad.tsx'
import { Alert } from '../../components/ui.tsx'

export function SignatureCard() {
  const { data, error, setData } = useLoad(() => signatureApi.get(), [])
  const [drawing, setDrawing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  async function save(value: SignatureInput) {
    setBusy(true)
    setMessage(null)
    setSaveError(null)
    try {
      setData(await signatureApi.save(value))
      setDrawing(false)
    } catch (err) {
      setSaveError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!(await confirmDialog({ title: 'Unterschrift löschen?', confirmLabel: 'Löschen' }))) return
    try {
      await signatureApi.remove()
      setData({ signature: null, updated_at: null })
    } catch (err) {
      setMessage(errorMessage(err))
    }
  }

  return (
    <div className="card">
      <h2>Unterschrift</h2>
      <p className="muted small">
        Wer Kasse führt, kann hier seine Unterschrift hinterlegen. Sie steht dann bei Quittungen
        schon im Feld des Kassierers. Verwendet wird sie nur, wenn du selbst eine Quittung
        abschließt. Gespeichert wird nur die Form der Linien.
      </p>
      {error && <Alert kind="error">{error}</Alert>}
      {message && <Alert kind="error">{message}</Alert>}
      {data?.signature && (
        <>
          <SignatureImage shape={data.signature} label="Deine hinterlegte Unterschrift" />
          {data.updated_at && (
            <p className="muted small">Hinterlegt am {formatDateTime(data.updated_at)}</p>
          )}
        </>
      )}
      {data && (
        <div className="button-row">
          <button type="button" className="button button-ghost" onClick={() => setDrawing(true)}>
            {data.signature ? 'Neu unterschreiben' : 'Unterschrift hinterlegen'}
          </button>
          {data.signature && (
            <button type="button" className="button button-ghost" onClick={remove}>
              Löschen
            </button>
          )}
        </div>
      )}
      {drawing && (
        <SignatureFullscreen
          title="Deine Unterschrift"
          text="Bitte unterschreibe so, wie du auf Papier unterschreibst."
          busy={busy}
          error={saveError}
          onCancel={() => {
            setSaveError(null)
            setDrawing(false)
          }}
          onConfirm={save}
        />
      )}
    </div>
  )
}
