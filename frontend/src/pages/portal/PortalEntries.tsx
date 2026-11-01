// Mitgliederbereich: wofür das Mitglied gemeldet ist (Meldungen Schritt 2).
import { entriesApi, type MyEntry } from '../../api/entries.ts'
import { formatDate, useLoad } from '../../components/forms.ts'
import { Alert } from '../../components/ui.tsx'
import { t } from '../../i18n/index.ts'

function today(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function PortalEntries({ accessId }: { accessId: number }) {
  const { data, error } = useLoad(() => entriesApi.mine(accessId), [accessId])
  if (error) return <Alert kind="error">{error}</Alert>
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  if (data.length === 0)
    return (
      <p className="muted">
        {t(
          'Zurzeit bist du für nichts gemeldet. Sobald der Verein dich zu einem Wettbewerb oder Anlass meldet, steht das hier.',
        )}
      </p>
    )
  const now = today()
  const coming = data.filter((r) => !r.date || r.date >= now)
  const past = data.filter((r) => r.date && r.date < now)
  return (
    <>
      {coming.length > 0 && <EntryList title={t('Demnächst')} rows={coming} />}
      {past.length > 0 && <EntryList title={t('Vergangen')} rows={past} />}
    </>
  )
}

function EntryList({ title, rows }: { title: string; rows: MyEntry[] }) {
  return (
    <div className="card card-wide">
      <h2>{title}</h2>
      <ul className="plain-list">
        {rows.map((r) => (
          <li key={r.id}>
            <strong>{r.title}</strong>
            <br />
            <span className="muted small">
              {[
                r.date ? formatDate(r.date) : '',
                r.location,
                t('Veranstalter: {organizer}', { organizer: r.organizer }),
              ]
                .filter(Boolean)
                .join(' · ')}
            </span>
            <br />
            {t('Gemeldet in')} {r.group}
            {r.position ? t(' als {position}', { position: r.position }) : ''}
            {r.substitute ? ' (Ersatz)' : ''}
            {r.confirmed ? t(', vom Veranstalter bestätigt') : ''}
          </li>
        ))}
      </ul>
    </div>
  )
}
