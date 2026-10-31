// Rückgängig-Knopf bzw. Stand an einem Eintrag des Änderungsprotokolls.
import { useState } from 'react'
import type { AuditEntry } from '../api/orgs.ts'
import { undoFromLog } from './undo.ts'

export function AuditUndo({
  entry,
  orgId,
  showAction,
}: {
  entry: AuditEntry
  orgId: number
  showAction: boolean
}) {
  const [busy, setBusy] = useState(false)
  const undo = entry.undo
  if (!undo) return null
  return (
    <div className="audit-actions small">
      {undo.is_undo && <span className="muted">durch Rückgängig · </span>}
      {undo.state === 'done' && <span className="muted">rückgängig gemacht</span>}
      {undo.state === 'blocked' && showAction && (
        <span className="muted">nicht rückgängig zu machen: {undo.reason}</span>
      )}
      {undo.state === 'possible' && showAction && (
        <button
          type="button"
          className="link-button"
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            await undoFromLog(`/api/orgs/${orgId}`, undo.change_set)
            setBusy(false)
          }}
        >
          {entry.action === 'delete' ? 'Wiederherstellen' : 'Rückgängig'}
        </button>
      )}
    </div>
  )
}
