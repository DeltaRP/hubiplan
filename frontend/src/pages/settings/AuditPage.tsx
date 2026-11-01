import { useState } from 'react'
import { orgApi } from '../../api/orgs.ts'
import type { AuditChainCheck, AuditEntry } from '../../api/orgs.ts'
import type { ListQuery } from '../../api/client.ts'
import { AuditUndo } from '../../components/AuditUndo.tsx'
import { ListSearch, Pager } from '../../components/ListControls.tsx'
import { firstOfSet } from '../../components/undo.ts'
import { Alert } from '../../components/ui.tsx'
import { errorMessage, formatDateTime, useLoad } from '../../components/forms.ts'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { Term } from '../../learning/Aids.tsx'
import { t } from '../../i18n/index.ts'

export function AuditPage() {
  const org = useActiveOrg()
  const [query, setQuery] = useState<ListQuery>({})
  const onlyDeleted = query.aktion === 'delete'
  const { data, error } = useLoad(
    () => orgApi.audit(org.id, query),
    [org.id, JSON.stringify(query)],
  )
  const entries = data?.results ?? []
  const first = firstOfSet(entries)
  const searching = !!(query.q || query.von || query.bis)
  return (
    <div className="card card-wide">
      <h2>{t('Änderungsprotokoll')}</h2>
      <p className="muted small">
        {t(
          'Wer hat wann was geändert. Änderungen der letzten 30 Tage lassen sich rückgängig machen, Gelöschtes lässt sich wiederherstellen. Ältere Einträge findest du über die Suche oder durch Blättern.',
        )}
      </p>
      <nav className="tabs" aria-label={t('Ansicht')}>
        <button
          type="button"
          className={`tab${onlyDeleted ? '' : ' active'}`}
          aria-current={onlyDeleted ? undefined : 'page'}
          onClick={() => setQuery({ ...query, aktion: undefined, seite: 1 })}
        >
          {t('Alle Änderungen')}
        </button>
        <button
          type="button"
          className={`tab${onlyDeleted ? ' active' : ''}`}
          aria-current={onlyDeleted ? 'page' : undefined}
          onClick={() => setQuery({ ...query, aktion: 'delete', seite: 1 })}
        >
          {t('Papierkorb')}
        </button>
      </nav>
      <AuditChain orgId={org.id} />
      <ListSearch query={query} onChange={setQuery} placeholder={t('Objekt, Person oder Art')} />
      {error && <Alert kind="error">{error}</Alert>}
      {!data && !error && <p className="muted">{t('Lädt …')}</p>}
      {data &&
        (entries.length === 0 ? (
          <p className="muted">
            {searching
              ? t('Keine passenden Einträge.')
              : onlyDeleted
                ? t('Nichts gelöscht.')
                : t('Noch keine Einträge.')}
          </p>
        ) : (
          <>
            <ul className="audit-list">
              {entries.map((entry) => (
                <AuditItem
                  key={entry.id}
                  entry={entry}
                  orgId={org.id}
                  showAction={first.has(entry.id)}
                />
              ))}
            </ul>
            <Pager
              data={data}
              noun={t('Einträge')}
              onPage={(seite) => setQuery({ ...query, seite })}
            />
          </>
        ))}
    </div>
  )
}

/** Kettenprüfung: Jeder Eintrag enthält die Prüfsumme seines Vorgängers. */
function AuditChain({ orgId }: { orgId: number }) {
  const { data, reload } = useLoad(() => orgApi.auditChain(orgId), [orgId])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AuditChainCheck | null>(null)
  const check = result ?? data?.check ?? null

  async function run() {
    setBusy(true)
    setError(null)
    try {
      setResult((await orgApi.checkAuditChain(orgId)).check)
      await reload()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="subcard">
      <p className="small">
        {check ? (
          <>
            {check.ok ? (
              <strong>{t('Protokoll unverändert')}</strong>
            ) : (
              <strong>{t('Protokoll wurde verändert')}</strong>
            )}
            {t(' · {entries} Einträge, geprüft am {x}', {
              entries: check.entries,
              x: formatDateTime(check.checked_at),
            })}
            {check.cleared > 0 &&
              t(' · {cleared} aus Datenschutzgründen geleert', { cleared: check.cleared })}
          </>
        ) : (
          t('Das Protokoll wurde noch nicht geprüft.')
        )}{' '}
        <button type="button" className="link-button" disabled={busy} onClick={() => void run()}>
          {t('Jetzt prüfen')}
        </button>
      </p>
      {check && !check.ok && (
        <Alert kind="error">
          {check.problems.map((p) => (
            <span key={p}>
              {p}
              <br />
            </span>
          ))}
        </Alert>
      )}
      <p className="muted small">
        {t('Das Protokoll ist')} <Term k="chained_log">verkettet</Term>
        {t(
          ': Jeder Eintrag enthält eine Prüfsumme seines Vorgängers. Wird ein Eintrag direkt in der Datenbank geändert oder gelöscht, fällt das hier auf. Die Prüfung läuft täglich; bei einem Fehler geht eine Warnung an die Betreiber.',
        )}
      </p>
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return '–'
  if (typeof value === 'boolean') return value ? 'ja' : 'nein'
  if (Array.isArray(value)) return value.join(', ') || '–'
  return String(value)
}

function AuditItem({
  entry,
  orgId,
  showAction,
}: {
  entry: AuditEntry
  orgId: number
  showAction: boolean
}) {
  const changes = Object.entries(entry.changes)
  return (
    <li>
      <div>
        <strong>{entry.object_type}</strong> „{entry.object_repr}“ {entry.action_label}
      </div>
      <div className="muted small">
        {formatDateTime(entry.timestamp)} · {entry.user_email || t('System')}
        {entry.via ? t(' · über {via}', { via: entry.via }) : ''}
      </div>
      {entry.action === 'update' && changes.length > 0 && (
        <ul className="changes small">
          {changes.map(([field, [before, after]]) => (
            <li key={field}>
              {field}: {show(before)} → {show(after)}
            </li>
          ))}
        </ul>
      )}
      <AuditUndo entry={entry} orgId={orgId} showAction={showAction} />
    </li>
  )
}
