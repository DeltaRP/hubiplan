// Im Standmodus endgültig abschließen (Ralf 2026-11-01): erst wenn alle Eingaben des Geräts
// beim Server angekommen sind; offene Stechen meldet der Server.
import { useState } from 'react'
import type { CompetitionDetail, StandApi } from '../../api/competitions.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage } from '../../components/forms.ts'

export function StandFinish({
  api,
  comp,
  pending,
  online,
  onFinished,
}: {
  api: StandApi
  comp: CompetitionDetail
  pending: number
  online: boolean
  onFinished: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  if (!api.finish || !comp.can_manage) return null
  const ready = online && pending === 0

  async function finish() {
    const ok = await confirmDialog({
      title: 'Endgültig abschließen',
      message: `„${comp.title}“ endgültig abschließen? Danach sind keine Eingaben mehr möglich. Wieder öffnen geht unter „Einrichten“.`,
      confirmLabel: 'Abschließen',
      danger: false,
    })
    if (!ok || !api.finish) return
    setBusy(true)
    try {
      await api.finish()
      setError(null)
      onFinished()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stand-finish">
      <div className="button-row">
        <button
          type="button"
          className="button button-ghost"
          disabled={!ready || busy}
          onClick={() => void finish()}
        >
          Endgültig abschließen
        </button>
      </div>
      {!ready && (
        <p className="muted small">Erst wenn alle Eingaben abgeglichen sind (Empfang nötig).</p>
      )}
      {error && <p className="alert alert-error">{error}</p>}
    </div>
  )
}
