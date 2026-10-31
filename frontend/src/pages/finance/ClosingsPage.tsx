// Kasse: Jahresabschluss mit Kassenbericht; danach ist das Geschäftsjahr gesperrt.
import { useState } from 'react'
import { financeApi } from '../../api/finance.ts'
import type { Retention } from '../../api/finance.ts'
import { errorMessage, formatDate, formatDateTime, useLoad } from '../../components/forms.ts'
import { Alert, LoadError } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { confirmDialog, promptDialog } from '../../components/dialog.ts'
import { Term, Why } from '../../learning/Aids.tsx'
import { Checklist } from '../../learning/Checklist.tsx'
import { closingChecks } from '../../learning/checks.ts'

function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function ClosingsPage() {
  const org = useActiveOrg()
  const { data, error, reload, setData } = useLoad(() => financeApi.closings(org.id), [org.id])
  const settings = useLoad(() => financeApi.settings(org.id), [org.id])
  const [lockDate, setLockDate] = useState('')
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  if (error) return <LoadError message={error} onRetry={() => void reload()} />
  if (!data) return <p className="muted">Lädt …</p>
  // Prüfliste für das älteste Jahr, das jetzt abgeschlossen werden kann
  const next = [...data.years]
    .sort((a, b) => a.year - b.year)
    .find((y) => !y.closed && !y.running && y.checks)

  async function close(year: number, label: string) {
    if (
      !(await confirmDialog({
        title: `Geschäftsjahr ${label} abschließen?`,
        message:
          'Danach lassen sich Buchungen dieses Jahres nicht mehr ändern, löschen oder neu nummerieren.',
        confirmLabel: 'Abschließen',
        danger: false,
      }))
    )
      return
    setBusy(true)
    setNotice(null)
    try {
      setData(await financeApi.closeYear(org.id, year))
      setNotice({ kind: 'success', text: `Geschäftsjahr ${label} ist abgeschlossen.` })
    } catch (err) {
      setNotice({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  async function reopen(year: number, label: string) {
    const reason = await promptDialog({
      title: `Abschluss ${label} aufheben?`,
      message:
        'Der bisherige Stand bleibt mit Grund gespeichert. Beim erneuten Abschluss siehst du, ' +
        'was sich gegenüber diesem Stand geändert hat.',
      label: 'Grund',
      confirmLabel: 'Aufheben',
    })
    if (reason === null) return
    setBusy(true)
    setNotice(null)
    try {
      setData(await financeApi.reopenYear(org.id, year, reason))
      setNotice({ kind: 'success', text: `Abschluss ${label} aufgehoben.` })
    } catch (err) {
      setNotice({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  async function purge(year: number, label: string, records: boolean) {
    if (
      !(await confirmDialog({
        title: `Geschäftsjahr ${label} bereinigen?`,
        message: records
          ? 'Die Aufbewahrungsfrist ist abgelaufen. Belegdateien und PDFs werden gelöscht; ' +
            'Namen, Anschriften, Buchungstexte und Bankdaten werden anonymisiert. Beträge, ' +
            'Konten und Kategorien bleiben. Das lässt sich nicht rückgängig machen.'
          : 'Die Aufbewahrungsfrist für Belege ist abgelaufen. Belegdateien, archivierte PDFs, ' +
            'Kontoauszugs- und SEPA-Dateien sowie Unterschriften werden gelöscht. Die Buchungen ' +
            'bleiben. Das lässt sich nicht rückgängig machen.',
        confirmLabel: 'Endgültig bereinigen',
        danger: true,
      }))
    )
      return
    setBusy(true)
    setNotice(null)
    try {
      const result = await financeApi.purgeYear(org.id, year)
      setNotice({ kind: 'success', text: `Geschäftsjahr ${label}: ${result.done}.` })
      await reload()
    } catch (err) {
      setNotice({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  async function lock() {
    if (!lockDate) return
    if (
      !(await confirmDialog({
        title: `Kasse bis ${formatDate(lockDate)} festschreiben?`,
        message:
          'Buchungen bis zu diesem Tag lassen sich danach nicht mehr ändern oder löschen, nur ' +
          'stornieren. Das lässt sich nicht zurücknehmen.',
        confirmLabel: 'Festschreiben',
        danger: false,
      }))
    )
      return
    setBusy(true)
    setNotice(null)
    try {
      settings.setData(await financeApi.lockUntil(org.id, lockDate))
      setLockDate('')
      setNotice({ kind: 'success', text: `Kasse bis ${formatDate(lockDate)} festgeschrieben.` })
    } catch (err) {
      setNotice({ kind: 'error', text: errorMessage(err) })
    } finally {
      setBusy(false)
    }
  }

  const fixedUntil = settings.data
    ? [settings.data.locked_until, settings.data.auto_locked_until]
        .filter((x): x is string => !!x)
        .sort()
        .pop()
    : undefined

  return (
    <div className="card card-wide">
      {settings.data && (
        <section className="subcard">
          <h3>Festschreibung</h3>
          <p className="muted small">
            Buchungen werden automatisch festgeschrieben, sobald der Folgemonat vorbei ist; danach
            lassen sie sich nur noch stornieren. Nachträglich erfasste Buchungen bleiben bis zum
            Ende des Folgemonats ihrer Erfassung änderbar. <Why k="booking_fixed" />
          </p>
          <p>
            Festgeschrieben bis <strong>{fixedUntil ? formatDate(fixedUntil) : '–'}</strong>
            {settings.data.locked_until && (
              <span className="muted small">
                {' '}
                (von Hand bis {formatDate(settings.data.locked_until)})
              </span>
            )}
          </p>
          {settings.data.can_edit && (
            <div className="button-row">
              <label>
                <span className="sr-only">Festschreiben bis</span>
                <input
                  type="date"
                  aria-label="Festschreiben bis"
                  value={lockDate}
                  max={todayIso()}
                  onChange={(e) => setLockDate(e.target.value)}
                />
              </label>
              <button
                type="button"
                className="button button-ghost"
                disabled={busy || !lockDate}
                onClick={() => void lock()}
              >
                Früher festschreiben
              </button>
            </div>
          )}
        </section>
      )}
      <h2>Jahresabschluss</h2>
      <p className="muted small">
        Der <Term k="cash_report">Kassenbericht</Term> zeigt Anfangs- und Endbestand je Konto sowie
        Einnahmen und Ausgaben nach Kategorie, mit Feldern für die Unterschriften der{' '}
        <Term k="auditors">Kassenprüfer</Term>. Nach dem Abschluss ist das Geschäftsjahr gesperrt.
        Korrekturen laufen dann als neue Buchung im laufenden Jahr. Der Datenexport (ZIP) dient der{' '}
        <Term k="data_access">Datenträgerüberlassung</Term> bei einer Prüfung. Nach Ablauf der{' '}
        <Term k="retention_period">Aufbewahrungsfrist</Term> lassen sich Belege löschen und Bücher
        anonymisieren.
      </p>
      <Why k="closing_lock" />
      {data.can_reopen && <Why k="reopen_closing" />}
      {data.years.some((y) => y.retention?.documents_due || y.retention?.records_due) && (
        <Why k="retention_end" />
      )}
      {next?.checks && data.can_close && (
        <Checklist title={`Vor dem Abschluss ${next.label}`} items={closingChecks(next.checks)} />
      )}
      {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}
      <table className="table">
        <thead>
          <tr>
            <th>
              <Term k="fiscal_year_term">Geschäftsjahr</Term>
            </th>
            <th>Stand</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {data.years.map((y) => (
            <tr key={y.year}>
              <td>
                <strong>{y.label}</strong>
                <div className="muted small">bis {formatDate(y.end_date)}</div>
              </td>
              <td>
                {y.closed
                  ? `abgeschlossen ${y.closed_at ? formatDateTime(y.closed_at) : ''}${y.closed_by ? ` von ${y.closed_by}` : ''}`
                  : y.running
                    ? 'läuft noch'
                    : 'offen'}
                {(y.reopened ?? []).map((h) => (
                  <div key={h.reopened_at} className="muted small">
                    Abschluss vom {formatDateTime(h.closed_at)} aufgehoben am{' '}
                    {formatDateTime(h.reopened_at)}
                    {h.reopened_by ? ` von ${h.reopened_by}` : ''}: {h.reason}
                  </div>
                ))}
                {y.retention && <RetentionNote r={y.retention} />}
                {y.closed && (y.changes ?? []).length > 0 && (
                  <details className="small">
                    <summary>Änderungen gegenüber dem aufgehobenen Stand</summary>
                    <ul>
                      {(y.changes ?? []).map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                  </details>
                )}
              </td>
              <td className="actions">
                <a
                  className="link-button"
                  href={financeApi.reportUrl(org.id, y.year)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Kassenbericht
                </a>{' '}
                <a
                  className="link-button"
                  href={financeApi.exportUrl(org.id, y.year)}
                  title="Alle Finanzdaten des Jahres mit Belegen, Rechnungen, Kontoauszügen und Protokoll als ZIP, z. B. für das Finanzamt"
                >
                  Datenexport (ZIP)
                </a>{' '}
                {settings.data?.datev_enabled && (
                  <>
                    <a
                      className="link-button"
                      href={financeApi.datevUrl(org.id, y.year)}
                      title="Buchungsstapel im DATEV-Format für die Steuerberatung"
                    >
                      DATEV
                    </a>{' '}
                  </>
                )}
                {data.can_close && !y.closed && !y.running && (
                  <button
                    type="button"
                    className="link-button"
                    disabled={busy}
                    onClick={() => void close(y.year, y.label)}
                  >
                    Abschließen
                  </button>
                )}
                {data.can_reopen &&
                  y.closed &&
                  !y.retention?.documents_purged_at &&
                  !y.retention?.records_purged_at && (
                    <button
                      type="button"
                      className="link-button"
                      disabled={busy}
                      onClick={() => void reopen(y.year, y.label)}
                    >
                      Abschluss aufheben
                    </button>
                  )}
                {data.can_reopen && (y.retention?.documents_due || y.retention?.records_due) && (
                  <>
                    {' '}
                    <button
                      type="button"
                      className="link-button"
                      disabled={busy}
                      onClick={() => void purge(y.year, y.label, !!y.retention?.records_due)}
                    >
                      {y.retention?.records_due ? 'Daten bereinigen' : 'Belege löschen'}
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Aufbewahrungsfrist: Belege 8 Jahre, Bücher 10 Jahre nach Ende des Kalenderjahres. */
function RetentionNote({ r }: { r: Retention }) {
  return (
    <div className="muted small">
      {r.records_purged_at
        ? `Bücher anonymisiert am ${formatDateTime(r.records_purged_at)}${r.purged_by ? ` von ${r.purged_by}` : ''}`
        : r.documents_purged_at
          ? `Belege gelöscht am ${formatDateTime(r.documents_purged_at)}${r.purged_by ? ` von ${r.purged_by}` : ''}; Bücher ab ${formatDate(r.records_from)} zu anonymisieren`
          : r.documents_due || r.records_due
            ? 'Aufbewahrungsfrist abgelaufen: Daten können bereinigt werden.'
            : `Aufbewahrungsfrist: Belege löschbar ab ${formatDate(r.documents_from)}, Bücher ab ${formatDate(r.records_from)}`}
    </div>
  )
}
