// Einstellungen › Verbund: Kopplungen mit Einheiten auf anderen HUBIplan-Instanzen.
import { useState } from 'react'
import { euro, financeApi } from '../../api/finance.ts'
import { memberApi, todayIso } from '../../api/members.ts'
import { orgApi, PERM } from '../../api/orgs.ts'
import { transferApi } from '../../api/datatransfer.ts'
import { levelsOf, peeringApi } from '../../api/peering.ts'
import type {
  Coupling,
  CouplingInvoice,
  Levels,
  RemoteTransfer,
  PacketChoice,
  PeeringPreview,
  ReceivedCompetition,
  SpinOff,
  SpinOffExitCandidate,
} from '../../api/peering.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, formatDate, formatDateTime, useLoad } from '../../components/forms.ts'
import { Alert, Checkbox, Field, LoadError, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { HowTo, Why } from '../../learning/Aids.tsx'
import { t } from '../../i18n/index.ts'

const KIND_LABELS: Record<string, string> = {
  'coupling.accept': t('Kopplung bestätigt'),
  'coupling.config': t('Freigaben geändert'),
  'coupling.end': t('Kopplung gelöst'),
  'register.numbers': t('Verbandsnummern'),
  'circular.forward': t('Rundschreiben zur Weitergabe'),
  'circular.report': t('Rückmeldung zum Rundschreiben'),
  'register.suggest': t('Korrekturvorschlag'),
  'transfer.request': t('Wechselanfrage'),
  'transfer.decision': t('Entscheidung zum Wechsel'),
  'transfer.cancel': t('Wechselanfrage zurückgezogen'),
  'invoice.issue': t('Rechnung'),
  'invoice.cancel': t('Rechnung storniert'),
  'invoice.status': t('Zahlungsstand'),
  'invoice.paid': t('als bezahlt gemeldet'),
}

function kindLabel(kind: string, coupling: Coupling): string {
  if (KIND_LABELS[kind]) return KIND_LABELS[kind]
  const key = kind.replace(/^packet\./, '')
  const packet =
    coupling.send.find((p) => p.key === key) ?? coupling.receive.find((p) => p.key === key)
  return packet ? packet.label.replace(/ \(.*\)$/, '') : kind
}

export function PeeringPage() {
  const org = useActiveOrg()
  const { data, error, reload } = useLoad(() => peeringApi.overview(org.id), [org.id])
  if (error) return <LoadError message={error} onRetry={() => void reload()} />
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  if (!data.enabled) {
    return (
      <div className="card card-wide">
        <h2>{t('Verbund')}</h2>
        <Alert kind="info">
          {t(
            'Der Verbund mit anderen HUBIplan-Instanzen ist auf dieser Instanz nicht eingeschaltet. Alles läuft wie bisher auf dieser Instanz. Einschalten kann ihn die Plattformverwaltung.',
          )}
        </Alert>
      </div>
    )
  }
  const open = data.couplings.filter((c) => c.state !== 'ended' && c.state !== 'moved')
  const closed = data.couplings.filter((c) => c.state === 'ended' || c.state === 'moved')
  return (
    <>
      <div className="card card-wide">
        <h2>{t('Verbund')}</h2>
        <p className="muted small">
          {t(
            'Einheiten auf anderen HUBIplan-Instanzen koppeln. Es fließen nur die Daten, die du unten freigibst, verschlüsselt und unterschrieben. Diese Instanz: {base_url} · Fingerabdruck',
            { base_url: data.instance?.base_url },
          )}{' '}
          <code>{data.instance?.fingerprint}</code>
        </p>
        <HowTo k="how_peering" />
      </div>
      {data.can_offer && <OfferCard />}
      {data.can_offer && org.type === 'club' && <SpinOffCard onChange={() => void reload()} />}
      {data.can_join && <JoinCard onJoined={() => void reload()} />}
      {open.map((c) => (
        <CouplingCard key={c.id} coupling={c} onChange={() => void reload()} />
      ))}
      {open.some((c) => c.state === 'active' || c.state === 'paused') && (
        <MoveCard onMoved={() => void reload()} />
      )}
      {closed.length > 0 && (
        <div className="card card-wide">
          <h3>{t('Frühere Kopplungen')}</h3>
          <ul className="plain-list">
            {closed.map((c) => (
              <li key={c.id}>
                {c.remote.name} ({c.remote.base_url}) · {c.state_label}
                {c.ended_at && t(' am {x}', { x: formatDateTime(c.ended_at) })}
              </li>
            ))}
          </ul>
        </div>
      )}
      {!data.can_offer && !data.can_join && open.length === 0 && (
        <Alert kind="info">
          {t(
            'Diese Einheit kann sich nicht mit anderen Instanzen koppeln: Nur Einheiten mit eigenem Datenbereich nehmen ferne Einheiten auf, und nur Einheiten mit eigenen Mitgliedern ohne Einheit darüber koppeln sich unter eine ferne Einheit.',
          )}
        </Alert>
      )}
    </>
  )
}

function MoveCard({ onMoved }: { onMoved: () => void }) {
  const org = useActiveOrg()
  const [url, setUrl] = useState('')
  const [target, setTarget] = useState<{ base_url: string; fingerprint: string } | null>(null)
  const [fingerprint, setFingerprint] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [result, setResult] = useState<{ done: number; failed: string[] } | null>(null)
  const [busy, setBusy] = useState(false)
  async function inspect() {
    setErr(null)
    setTarget(null)
    setBusy(true)
    try {
      setTarget(await peeringApi.moveInspect(org.id, url.trim()))
    } catch (e) {
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  async function announce() {
    if (!target) return
    const ok = await confirmDialog({
      title: t('Umzug melden?'),
      message:
        t('Alle Gegenstellen koppeln sich danach mit der neuen Instanz. Diese Instanz nimmt für ') +
        t('die Kopplungen dieser Einheit nichts mehr an. Das lässt sich nicht rückgängig machen.'),
      confirmLabel: t('Umzug melden'),
      danger: true,
    })
    if (!ok) return
    setErr(null)
    setBusy(true)
    try {
      setResult(await peeringApi.move(org.id, target.base_url, fingerprint))
      onMoved()
    } catch (e) {
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <details className="card card-wide">
      <summary>
        <strong>{t('Umzug auf eine andere Instanz')}</strong>
      </summary>
      <ol className="small">
        <li>{t('Unter Datenübernahme diese Einheit exportieren. Die Kopplungen ziehen mit.')}</li>
        <li>{t('Die Datei auf der neuen Instanz einlesen lassen.')}</li>
        <li>
          {t(
            'Hier die neue Instanz eintragen, den Fingerabdruck vergleichen und den Umzug melden.',
          )}
        </li>
      </ol>
      {result ? (
        <Alert kind={result.failed.length ? 'error' : 'success'}>
          {result.done} {t('Gegenstelle(n) haben den Umzug übernommen.')}
          {result.failed.length > 0 && t(' Nicht erreicht: {x}', { x: result.failed.join('; ') })}
        </Alert>
      ) : (
        <>
          <Field
            label={t('Adresse der neuen Instanz')}
            type="url"
            value={url}
            placeholder="https://"
            onChange={(e) => {
              setUrl(e.target.value)
              setTarget(null)
            }}
          />
          {target && (
            <>
              <p className="small">
                {t('Fingerabdruck von {base_url}:', { base_url: target.base_url })}{' '}
                <code>{target.fingerprint}</code>
              </p>
              <Field
                label={t('Fingerabdruck zur Bestätigung')}
                hint={t('Von der Plattformverwaltung der neuen Instanz auf anderem Weg erfragen.')}
                value={fingerprint}
                onChange={(e) => setFingerprint(e.target.value)}
              />
            </>
          )}
          {err && <Alert kind="error">{err}</Alert>}
          <div className="button-row">
            {!target ? (
              <button
                type="button"
                className="button"
                disabled={busy || !url.trim()}
                onClick={() => void inspect()}
              >
                {t('Neue Instanz prüfen')}
              </button>
            ) : (
              <button
                type="button"
                className="button button-danger"
                disabled={busy || !fingerprint.trim()}
                onClick={() => void announce()}
              >
                {t('Umzug melden')}
              </button>
            )}
          </div>
        </>
      )}
    </details>
  )
}

function SpinOffCard({ onChange }: { onChange: () => void }) {
  const org = useActiveOrg()
  const canExport = org.permissions.includes(PERM.dataExport)
  const { data, reload } = useLoad(() => peeringApi.spinOffs(org.id), [org.id])
  const units = useLoad(() => orgApi.departments(org.id), [org.id])
  const [unit, setUnit] = useState('')
  const [way, setWay] = useState<'keep' | 'move'>('keep')
  const [cutoff, setCutoff] = useState('')
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [withFiles, setWithFiles] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  if (!data) return null
  const candidates = (units.data ?? []).filter(
    (u) =>
      !u.is_remote &&
      u.is_active &&
      !(units.data ?? []).some((c) => c.parent_unit === u.id) &&
      !data.spin_offs.some(
        (s) => s.unit.id === u.id && (s.state === 'prepared' || s.state === 'requested'),
      ),
  )
  const items = data.checklist[way]
  const ready = unit && cutoff && items.every((i) => checked[i.key])

  async function prepare() {
    const ok = await confirmDialog({
      title: t('Ausgliederung vorbereiten?'),
      message:
        t('Es entstehen ein Export der Untereinheit mit ihren Mitgliedern und ein Kopplungscode ') +
        t(
          '(30 Tage gültig). Gib die Datei nur an die Plattformverwaltung der neuen Instanz weiter.',
        ),
      confirmLabel: t('Vorbereiten'),
    })
    if (!ok) return
    setErr(null)
    setBusy(true)
    try {
      await peeringApi.prepareSpinOff(org.id, {
        unit: Number(unit),
        way,
        cutoff,
        checklist: checked,
        with_files: withFiles,
      })
      setUnit('')
      setChecked({})
      await reload()
      onChange()
    } catch (e) {
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  async function cancel(id: number) {
    setErr(null)
    try {
      await peeringApi.cancelSpinOff(org.id, id)
      await reload()
    } catch (e) {
      setErr(errorMessage(e))
    }
  }

  return (
    <div className="card card-wide">
      <h3>{t('Untereinheit auf eigene Instanz ausgliedern')}</h3>
      <p className="muted small">
        {t(
          'Für eine Untereinheit, die künftig eine eigene HUBIplan-Instanz betreibt. Sie bekommt einen Export ihrer Daten mit einem Kopplungscode. Die neue Instanz liest ihn ein und koppelt sich damit unter den Verein. Nach deiner Bestätigung ist die Untereinheit hier nur noch zu sehen.',
        )}
      </p>
      {data.spin_offs.length > 0 && (
        <ul className="plain-list">
          {data.spin_offs.map((s) => (
            <li key={s.id}>
              <strong>{s.unit.name}</strong>
              {t(': {way_label}, Stichtag {x} ·', {
                way_label: s.way_label,
                x: formatDate(s.cutoff),
              })}{' '}
              {s.state_label}
              {s.state === 'prepared' && s.export_job?.has_file && canExport && (
                <>
                  {' · '}
                  <a href={transferApi.downloadUrl({ org: org.id }, s.export_job.id)}>
                    {t('Export herunterladen')}
                  </a>
                </>
              )}
              {s.state === 'prepared' && s.export_job && !s.export_job.has_file && (
                <> {t('· Export läuft noch')}</>
              )}
              {s.state === 'prepared' && (
                <>
                  {' '}
                  <button
                    type="button"
                    className="button button-ghost"
                    onClick={() => void cancel(s.id)}
                  >
                    {t('Abbrechen')}
                  </button>
                </>
              )}
              {s.state === 'requested' && (
                <>
                  {' '}
                  {t(
                    '· Die Anfrage steht unten bei den Kopplungen und wartet auf deine Bestätigung.',
                  )}
                </>
              )}
              {s.exited_at && (
                <>
                  {' '}
                  {t('· Sammelaustritt: {exited_count} Mitglieder zum', {
                    exited_count: s.exited_count,
                  })}{' '}
                  {formatDate(s.cutoff)}
                </>
              )}
              {s.state === 'done' && s.way === 'move' && !s.exited_at && (
                <CollectiveExit spin={s} onDone={() => void reload()} />
              )}
            </li>
          ))}
        </ul>
      )}
      {!canExport ? (
        <Alert kind="info">
          {t('Ausgliedern darf nur, wer den vollständigen Export erstellen darf.')}
        </Alert>
      ) : (
        <>
          <SelectField
            label={t('Untereinheit')}
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            hint={t('Nur Untereinheiten ohne eigene Untereinheiten.')}
          >
            <option value="">{t('bitte wählen')}</option>
            {candidates.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </SelectField>
          <fieldset>
            <legend className="small">{t('Was wird aus den Mitgliedern?')}</legend>
            <label className="checkbox">
              <input
                type="radio"
                name="spin-way"
                checked={way === 'keep'}
                onChange={() => {
                  setWay('keep')
                  setChecked({})
                }}
              />
              <span>
                {t(
                  'Sie bleiben Mitglieder des Vereins (empfohlen). Die Untereinheit pflegt sie auf ihrer Instanz, der Verein sieht sie weiter.',
                )}
              </span>
            </label>
            <label className="checkbox">
              <input
                type="radio"
                name="spin-way"
                checked={way === 'move'}
                onChange={() => {
                  setWay('move')
                  setChecked({})
                }}
              />
              <span>
                {t(
                  'Sie werden Mitglieder der Untereinheit. Beim Verein treten sie zum Stichtag mit Grund „Wechsel“ aus.',
                )}
              </span>
            </label>
          </fieldset>
          <Field
            label={t('Stichtag')}
            type="date"
            value={cutoff}
            onChange={(e) => setCutoff(e.target.value)}
          />
          <fieldset>
            <legend className="small">{t('Vorher erledigt')}</legend>
            {items.map((i) => (
              <Checkbox
                key={i.key}
                label={i.label}
                checked={!!checked[i.key]}
                onChange={(on) => setChecked({ ...checked, [i.key]: on })}
              />
            ))}
          </fieldset>
          <Checkbox
            label={t('Mit Dateien (Fotos, Belege, Satzung)')}
            checked={withFiles}
            onChange={setWithFiles}
          />
          {err && <Alert kind="error">{err}</Alert>}
          <div className="button-row">
            <button
              type="button"
              className="button"
              disabled={!ready || busy}
              onClick={() => void prepare()}
            >
              {t('Ausgliederung vorbereiten')}
            </button>
          </div>
        </>
      )}
    </div>
  )
}

/** Weg B: Mitglieder der ausgegliederten Untereinheit treten zum Stichtag aus (Wechsel). */
function CollectiveExit({ spin, onDone }: { spin: SpinOff; onDone: () => void }) {
  const org = useActiveOrg()
  const [members, setMembers] = useState<SpinOffExitCandidate[] | null>(null)
  const [keep, setKeep] = useState<Record<number, boolean>>({})
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  if (!org.permissions.includes(PERM.membersEdit)) return null

  async function load() {
    setErr(null)
    try {
      const data = await peeringApi.spinOffExitPreview(org.id, spin.id)
      setMembers(data.members)
      // Wer zugleich in einer anderen Untereinheit ist, bleibt vorerst Mitglied
      setKeep(Object.fromEntries(data.members.map((m) => [m.id, m.also_in.length > 0])))
    } catch (e) {
      setErr(errorMessage(e))
    }
  }

  async function run() {
    if (!members) return
    const leaving = members.filter((m) => !keep[m.id]).length
    const ok = await confirmDialog({
      title: t('Sammelaustritt ausführen?'),
      message:
        t('{leaving} Mitglieder treten zum {x} mit Grund „Wechsel“ aus. ', {
          leaving,
          x: formatDate(spin.cutoff),
        }) + t('Die Zeiträume bleiben, danach gilt die Löschfrist wie bei jedem Austritt.'),
      confirmLabel: t('Austritt erfassen'),
    })
    if (!ok) return
    setBusy(true)
    setErr(null)
    try {
      await peeringApi.spinOffExit(
        org.id,
        spin.id,
        members.filter((m) => keep[m.id]).map((m) => m.id),
      )
      onDone()
    } catch (e) {
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="subcard">
      {!members ? (
        <button type="button" className="button" onClick={() => void load()}>
          {t('Sammelaustritt vorbereiten')}
        </button>
      ) : (
        <>
          <p className="small">
            {t('Austritt zum {x} mit Grund „Wechsel“. Häkchen heißt: bleibt Vereinsmitglied.', {
              x: formatDate(spin.cutoff),
            })}
          </p>
          {members.length === 0 && <p className="muted small">{t('Niemand mehr zugeordnet.')}</p>}
          {members.map((m) => (
            <Checkbox
              key={m.id}
              label={t('{name} bleibt{x}', {
                name: m.name,
                x: m.also_in.length ? ` (auch in ${m.also_in.join(', ')})` : '',
              })}
              checked={!!keep[m.id]}
              onChange={(on) => setKeep({ ...keep, [m.id]: on })}
            />
          ))}
          <div className="button-row">
            <button
              type="button"
              className="button button-primary"
              disabled={busy}
              onClick={() => void run()}
            >
              {t('Sammelaustritt ausführen')}
            </button>
          </div>
        </>
      )}
      {err && <Alert kind="error">{err}</Alert>}
    </div>
  )
}

function OfferCard() {
  const org = useActiveOrg()
  const [code, setCode] = useState<{ code: string; expires_at: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  async function create() {
    setErr(null)
    try {
      setCode(await peeringApi.createCode(org.id))
    } catch (e) {
      setErr(errorMessage(e))
    }
  }
  return (
    <div className="card card-wide">
      <h3>{t('Ferne Einheit aufnehmen')}</h3>
      {org.type === 'club' && (
        <p className="muted small">
          {t(
            'Für eine Untereinheit, die eine eigene HUBIplan-Instanz betreibt: Sie erscheint hier unter den Untereinheiten und teilt Stammdaten, Termine, Vorstand und Satzung.',
          )}
        </p>
      )}
      <p className="muted small">
        {t(
          'Erzeuge einen Kopplungscode und gib ihn auf anderem Weg (Telefon, Mail, Papier) an den Vorstand der anderen Einheit. Der Code gilt 48 Stunden und nur einmal. Danach bestätigst du die Anfrage hier.',
        )}
      </p>
      {code && (
        <>
          <label className="field">
            <span>{t('Kopplungscode')}</span>
            <textarea readOnly rows={4} value={code.code} onFocus={(e) => e.target.select()} />
          </label>
          <p className="muted small">
            {t('Gültig bis {x}.', { x: formatDateTime(code.expires_at) })}
          </p>
        </>
      )}
      {err && <Alert kind="error">{err}</Alert>}
      <div className="button-row">
        <button type="button" className="button" onClick={() => void create()}>
          {code ? t('Neuen Code erzeugen') : t('Kopplungscode erzeugen')}
        </button>
        {code && (
          <button
            type="button"
            className="button"
            onClick={() => void navigator.clipboard?.writeText(code.code)}
          >
            {t('Kopieren')}
          </button>
        )}
      </div>
    </div>
  )
}

function JoinCard({ onJoined }: { onJoined: () => void }) {
  const org = useActiveOrg()
  const [code, setCode] = useState('')
  const [preview, setPreview] = useState<PeeringPreview | null>(null)
  const [levels, setLevels] = useState<Levels>({})
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function check() {
    setErr(null)
    setBusy(true)
    try {
      const p = await peeringApi.inspect(org.id, code)
      setPreview(p)
      setLevels(levelsOf(p.send))
    } catch (e) {
      setErr(errorMessage(e))
      setPreview(null)
    } finally {
      setBusy(false)
    }
  }

  async function join() {
    if (!preview) return
    const ok = await confirmDialog({
      message: t(
        '{name} unter „{name2}“ ({base_url}) koppeln? Die andere Seite muss noch bestätigen.',
        { name: org.name, name2: preview.remote.name, base_url: preview.remote.base_url },
      ),
      confirmLabel: t('Koppeln'),
      danger: false,
    })
    if (!ok) return
    setBusy(true)
    try {
      await peeringApi.join(org.id, code, levels)
      setCode('')
      setPreview(null)
      onJoined()
    } catch (e) {
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card card-wide">
      <h3>{t('Unter eine ferne Einheit koppeln')}</h3>
      <p className="muted small">
        {t(
          'Den Kopplungscode bekommst du vom Vorstand der Einheit darüber. Vor dem Koppeln siehst du, wer die andere Seite ist und welche Daten fließen.',
        )}
      </p>
      <label className="field">
        <span>{t('Kopplungscode')}</span>
        <textarea rows={3} value={code} onChange={(e) => setCode(e.target.value)} />
      </label>
      {err && <Alert kind="error">{err}</Alert>}
      {preview && (
        <>
          <p>
            <strong>{preview.remote.name}</strong> auf {preview.remote.base_url}
            {preview.remote.country && ` (Server in ${preview.remote.country})`}
            <br />
            <span className="muted small">
              {t('Fingerabdruck')} <code>{preview.remote.fingerprint}</code>. Vergleiche ihn am
              besten am Telefon mit der anderen Seite.
            </span>
          </p>
          {preview.remote.kind === 'club' && (
            <Alert kind="info">
              {t(
                'Die andere Seite ist ein Verein. {name} erscheint dort als Untereinheit auf einer eigenen Instanz.',
                { name: org.name },
              )}
            </Alert>
          )}
          <PacketToggles choices={preview.send} levels={levels} onChange={setLevels} />
          <p className="muted small">
            {t('Von dort kann kommen:')}{' '}
            {preview.receive.map((r) => r.label).join(', ') || 'nichts'}.
          </p>
        </>
      )}
      <div className="button-row">
        <button
          type="button"
          className="button"
          disabled={busy || !code}
          onClick={() => void check()}
        >
          {t('Prüfen')}
        </button>
        {preview && (
          <button
            type="button"
            className="button button-primary"
            disabled={busy}
            onClick={() => void join()}
          >
            {t('Koppeln')}
          </button>
        )}
      </div>
    </div>
  )
}

function PacketToggles({
  choices,
  levels,
  onChange,
  disabled,
}: {
  choices: PacketChoice[]
  levels: Levels
  onChange: (l: Levels) => void
  disabled?: boolean
}) {
  return (
    <fieldset className="fieldset">
      <legend>{t('Diese Einheit gibt frei')}</legend>
      {choices.map((c) => (
        <label key={c.key} className="field">
          <span>
            {c.label}
            {c.personal && (
              <span className="muted small">
                {' '}
                {t('· Personenbezug:')} {c.personal}
              </span>
            )}
          </span>
          <select
            value={levels[c.key] ?? ''}
            disabled={disabled}
            onChange={(e) => {
              const value = e.target.value
              void (async () => {
                if (c.key === 'members' && value === 'b' && !(await confirmNamed())) return
                const next = { ...levels }
                if (value) next[c.key] = value
                else delete next[c.key]
                onChange(next)
              })()
            }}
          >
            <option value="">aus</option>
            {c.levels.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
      ))}
      {choices.some((c) => c.key === 'members') && <Why k="peering_named" />}
    </fieldset>
  )
}

/** Prüfliste vor der namentlichen Meldung (Konzept 6.1). */
function confirmNamed(): Promise<boolean> {
  return confirmDialog({
    message:
      t('Namentliche Meldung: Name, Vorname, Geburtsdatum, Verbandsnummer, Mitgliedsart und ') +
      t('Zeiträume gehen an die Einheit darüber (nie Anschrift, Kontakt, Bankdaten, Fotos). ') +
      t('Bitte vorher prüfen: Steht die Meldepflicht in der Satzung? Nennen die ') +
      t('Datenschutzhinweise die Einheit darüber als Empfänger?'),
    confirmLabel: t('Geprüft, namentlich melden'),
  })
}

function CouplingCard({ coupling, onChange }: { coupling: Coupling; onChange: () => void }) {
  const org = useActiveOrg()
  const [levels, setLevels] = useState<Levels>(levelsOf(coupling.send))
  const [details, setDetails] = useState<Coupling | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const above = coupling.direction === 'parent'

  async function run(fn: () => Promise<unknown>) {
    setErr(null)
    setBusy(true)
    try {
      await fn()
      onChange()
    } catch (e) {
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  async function end() {
    const ok = await confirmDialog({
      message: t(
        'Kopplung mit „{name}“ lösen? Übermittelte Kopien werden auf beiden Seiten entfernt; Rechnungen bleiben.',
        { name: coupling.remote.name },
      ),
      confirmLabel: t('Lösen'),
    })
    if (ok) await run(() => peeringApi.end(org.id, coupling.id))
  }

  const changed = JSON.stringify(levels) !== JSON.stringify(levelsOf(coupling.send))
  return (
    <div className="card card-wide">
      <h3>
        {coupling.remote.name}{' '}
        <span className="muted small">
          ({above ? t('Einheit darüber') : t('Einheit darunter')} · {coupling.state_label})
        </span>
      </h3>
      <p className="muted small">
        {coupling.remote.base_url}
        {coupling.remote.country &&
          t(' · Server in {country}', { country: coupling.remote.country })}{' '}
        {t('· Fingerabdruck')} <code>{coupling.remote.fingerprint}</code>
        <br />
        {coupling.last_contact_at
          ? t('Zuletzt Kontakt {x}', { x: formatDateTime(coupling.last_contact_at) })
          : t('Noch kein Kontakt')}
        {coupling.last_sync_at &&
          t(' · abgeglichen {x}', { x: formatDateTime(coupling.last_sync_at) })}
        {coupling.queued > 0 && t(' · {queued} Paket(e) warten', { queued: coupling.queued })}
      </p>
      {coupling.error_since && (
        <Alert kind="error">
          {t(
            'Seit {x} nicht zustellbar: {last_error}. Die Pakete werden automatisch nachgeschickt.',
            { x: formatDateTime(coupling.error_since), last_error: coupling.last_error },
          )}
        </Alert>
      )}
      {coupling.state === 'pending' && (
        <Alert kind="info">
          {coupling.remote.name}{' '}
          {t(
            'möchte sich unter {name} koppeln. Prüfe Adresse und Fingerabdruck mit der anderen Seite.',
            { name: org.name },
          )}
        </Alert>
      )}
      {coupling.state === 'requested' && (
        <Alert kind="info">
          {t('Angefragt. Die andere Seite muss die Kopplung noch bestätigen.')}
        </Alert>
      )}
      {coupling.state === 'moving' && coupling.move && (
        <MoveConfirm coupling={coupling} onChange={onChange} />
      )}
      {coupling.keys && <KeysPending coupling={coupling} />}
      {coupling.wants_more.length > 0 && <MoreWanted coupling={coupling} onChange={onChange} />}
      <PacketToggles
        choices={coupling.send}
        levels={levels}
        onChange={setLevels}
        disabled={busy || coupling.state === 'requested'}
      />
      <p className="muted small">
        {t('Die andere Seite gibt frei:')}{' '}
        {coupling.receive
          .filter((r) => r.value)
          .map((r) => r.label)
          .join(', ') || 'nichts'}
        .
      </p>
      <ReceivedInfo coupling={coupling} />
      {coupling.register && <RegisterCard coupling={coupling} onChange={onChange} />}
      <CircularsInfo coupling={coupling} onChange={onChange} />
      {above &&
        coupling.state === 'active' &&
        coupling.send.some((p) => p.key === 'members' && p.value === 'b') && (
          <TransferCard coupling={coupling} onChange={onChange} />
        )}
      {coupling.invoices?.length > 0 && <InvoiceList coupling={coupling} onChange={onChange} />}
      {(coupling.hidden?.length ?? 0) > 0 && (
        <p className="muted small">
          {t('Ausgeblendet, weil dir das Recht fehlt:')}{' '}
          {coupling
            .hidden!.map((h) =>
              h === 'names'
                ? t('Namen bei Klärfällen und Wechseln (Mitglieder ansehen)')
                : t('Eingangsrechnungen (Beiträge/Rechnungen ansehen)'),
            )
            .join('; ')}
          .
        </p>
      )}
      {err && <Alert kind="error">{err}</Alert>}
      <div className="button-row">
        {coupling.state === 'pending' && (
          <>
            <button
              type="button"
              className="button button-primary"
              disabled={busy}
              onClick={() =>
                void run(() => peeringApi.action(org.id, coupling.id, 'accept', levels))
              }
            >
              {t('Bestätigen')}
            </button>
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => void run(() => peeringApi.action(org.id, coupling.id, 'decline'))}
            >
              {t('Ablehnen')}
            </button>
          </>
        )}
        {changed && coupling.state !== 'pending' && (
          <button
            type="button"
            className="button button-primary"
            disabled={busy}
            onClick={() => void run(() => peeringApi.setPackets(org.id, coupling.id, levels))}
          >
            {t('Freigaben speichern')}
          </button>
        )}
        {coupling.state === 'active' && (
          <>
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => void run(() => peeringApi.action(org.id, coupling.id, 'sync'))}
            >
              {t('Jetzt abgleichen')}
            </button>
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => void run(() => peeringApi.action(org.id, coupling.id, 'pause'))}
            >
              {t('Pausieren')}
            </button>
          </>
        )}
        {coupling.state === 'paused' && (
          <button
            type="button"
            className="button"
            disabled={busy}
            onClick={() => void run(() => peeringApi.action(org.id, coupling.id, 'resume'))}
          >
            {t('Fortsetzen')}
          </button>
        )}
        {coupling.state !== 'pending' && coupling.state !== 'moving' && (
          <button
            type="button"
            className="button button-danger"
            disabled={busy}
            onClick={() => void end()}
          >
            {t('Lösen')}
          </button>
        )}
        <button
          type="button"
          className="button"
          onClick={() =>
            details
              ? setDetails(null)
              : void peeringApi
                  .detail(org.id, coupling.id)
                  .then(setDetails, (e) => setErr(errorMessage(e)))
          }
        >
          {details ? t('Datenfluss ausblenden') : t('Datenfluss anzeigen')}
        </button>
      </div>
      {details?.messages && (
        <table className="table">
          <thead>
            <tr>
              <th>{t('Zeit')}</th>
              <th>{t('Richtung')}</th>
              <th>{t('Inhalt')}</th>
              <th>{t('Personen')}</th>
              <th>{t('Stand')}</th>
            </tr>
          </thead>
          <tbody>
            {details.messages.map((m) => (
              <tr key={`${m.direction}-${m.seq}-${m.created_at}`}>
                <td>{formatDateTime(m.created_at)}</td>
                <td>{m.direction === 'out' ? 'gesendet' : 'empfangen'}</td>
                <td>{kindLabel(m.kind, coupling)}</td>
                <td>{m.persons || '–'}</td>
                <td>
                  {m.state_label}
                  {m.last_error && <span className="muted small"> · {m.last_error}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function MoveConfirm({ coupling, onChange }: { coupling: Coupling; onChange: () => void }) {
  const org = useActiveOrg()
  const [fingerprint, setFingerprint] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const move = coupling.move!

  async function run(fn: () => Promise<unknown>) {
    setErr(null)
    setBusy(true)
    try {
      await fn()
      onChange()
    } catch (e) {
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="move-confirm">
      <Alert kind="info">
        {coupling.remote.name} {t('meldet einen Umzug von')} <strong>{move.from}</strong> nach{' '}
        <strong>{move.base_url}</strong>
        {move.country && ` (Server in ${move.country})`}. Bis zur Bestätigung ruht die Kopplung, es
        gehen keine Daten hinaus.
      </Alert>
      <p>
        {t('Fingerabdruck der neuen Instanz:')} <code>{move.fingerprint}</code>. Lass ihn dir von
        der anderen Seite auf anderem Weg (Telefon, Mail) nennen und gib ihn hier ein. Wenn ihr
        nichts von einem Umzug wisst: ablehnen.
      </p>
      <label className="field">
        <span>{t('Fingerabdruck von der anderen Seite')}</span>
        <input
          value={fingerprint}
          onChange={(e) => setFingerprint(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
      </label>
      {err && <Alert kind="error">{err}</Alert>}
      <div className="button-row">
        <button
          type="button"
          className="button button-primary"
          disabled={busy || !fingerprint.trim()}
          onClick={() => void run(() => peeringApi.confirmMove(org.id, coupling.id, fingerprint))}
        >
          {t('Umzug bestätigen')}
        </button>
        <button
          type="button"
          className="button button-danger"
          disabled={busy}
          onClick={() => void run(() => peeringApi.action(org.id, coupling.id, 'move-decline'))}
        >
          {t('Ablehnen und Kopplung lösen')}
        </button>
      </div>
    </div>
  )
}

/** Gegenseite möchte mehr senden, als hier beim Koppeln angenommen wurde (Härtung H4). */
function MoreWanted({ coupling, onChange }: { coupling: Coupling; onChange: () => void }) {
  const org = useActiveOrg()
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function decide(key: string, accept: boolean) {
    setErr(null)
    setBusy(true)
    try {
      await peeringApi.decideMore(org.id, coupling.id, key, accept)
      onChange()
    } catch (e) {
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="move-confirm">
      <Alert kind="info">
        {coupling.remote.name}{' '}
        {t(
          'möchte mehr senden, als ihr beim Koppeln angenommen habt. Bis ihr zustimmt, nimmt HUBIplan nur die bisherige Stufe an.',
        )}
      </Alert>
      <ul className="plain-list">
        {coupling.wants_more.map((w) => (
          <li key={w.key}>
            <strong>{w.label}</strong>: {w.level_label} (bisher {w.accepted_label})
            {w.personal && <span className="muted small"> · {w.personal}</span>}
            <div className="button-row">
              <button
                type="button"
                className="button button-primary"
                disabled={busy}
                onClick={() => void decide(w.key, true)}
              >
                {t('Annehmen')}
              </button>
              <button
                type="button"
                className="button"
                disabled={busy}
                onClick={() => void decide(w.key, false)}
              >
                {t('Ablehnen')}
              </button>
            </div>
          </li>
        ))}
      </ul>
      <p className="muted small">
        {t('Nach dem Annehmen kommen die Daten spätestens beim täglichen Abgleich.')}
      </p>
      {err && <Alert kind="error">{err}</Alert>}
    </div>
  )
}

/** Notfallwechsel der Schlüssel einer Gegenstelle: bestätigt die Plattformverwaltung (FQ-11). */
function KeysPending({ coupling }: { coupling: Coupling }) {
  const keys = coupling.keys!
  return (
    <div className="move-confirm">
      <Alert kind="error">
        {coupling.remote.base_url}{' '}
        {t(
          'meldet einen Notfallwechsel der Schlüssel: Die alten wurden dort vermutlich gestohlen. Bis zur Bestätigung ruht der Austausch mit dieser Instanz.',
        )}
      </Alert>
      <p>
        {t('Neuer Fingerabdruck:')} <code>{keys.fingerprint}</code>. Den Wechsel prüft und bestätigt
        die Plattformverwaltung dieser HUBIplan-Instanz, weil er für alle Kopplungen mit dieser
        Instanz gilt. Ihr bekommt danach eine Mitteilung. Wisst ihr von keinem Notfall bei der
        anderen Seite, sagt bitte der Plattformverwaltung Bescheid.
      </p>
    </div>
  )
}

function ReceivedInfo({ coupling }: { coupling: Coupling }) {
  const r = coupling.received
  if (!r) return null
  const roles = r.board?.roles ?? []
  return (
    <div className="muted small">
      {r.members && (
        <p>
          {t('Gemeldete Mitglieder am {x}: {total} (', {
            x: formatDate(r.members.on),
            total: r.members.total,
          })}
          {r.members.counts.filter((c) => c.kind === 'active').reduce((a, c) => a + c.n, 0)} aktiv,{' '}
          {r.members.counts.filter((c) => c.kind === 'passive').reduce((a, c) => a + c.n, 0)}{' '}
          {t('passiv). Die Beitragsrechnung an diese Einheit nutzt diese Zahlen.')}
        </p>
      )}
      {typeof r.events === 'number' && r.events > 0 && (
        <p>
          {r.events} {t('übermittelte Termine stehen im Kalender.')}
        </p>
      )}
      {r.statute && (
        <p>
          {t('Satzung vom')} {formatDate(r.statute.valid_from)}
          {r.statute.download_url && (
            <>
              {' · '}
              <a href={r.statute.download_url} target="_blank" rel="noreferrer">
                {t('öffnen')}
              </a>
            </>
          )}
        </p>
      )}
      {roles.length > 0 && (
        <ul className="plain-list">
          {roles.map((role) => (
            <li key={role.role}>
              {role.role}: {role.holders.map((h) => h.name).join(', ') || '–'}
              {role.email && t(' · {email}', { email: role.email })}
            </li>
          ))}
        </ul>
      )}
      {r.results && <ReceivedResults competitions={r.results.competitions} />}
    </div>
  )
}

function ReceivedResults({ competitions }: { competitions: ReceivedCompetition[] }) {
  if (competitions.length === 0) {
    return <p>{t('Noch keine endgültigen Wettbewerbsergebnisse übermittelt.')}</p>
  }
  return (
    <details>
      <summary>{t('Wettbewerbsergebnisse von oben: {n}', { n: competitions.length })}</summary>
      {competitions.map((c) => (
        <div key={c.uid}>
          <p>
            <strong>{c.title}</strong> · {formatDate(c.date)}
            {c.location && ` · ${c.location}`}
          </p>
          <ul className="plain-list">
            {c.scorings.map((s) => (
              <li key={s.name}>
                {s.name}:{' '}
                {s.rows.map((row, i) => (
                  <span key={i}>
                    {i > 0 && ', '}
                    {row.own ? <strong>{resultRow(row)}</strong> : resultRow(row)}
                  </span>
                ))}
                {s.field ? ` ${t('(von {n})', { n: s.field })}` : ''}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </details>
  )
}

function resultRow(row: { place: number | null; name: string; value: string }): string {
  const place = row.place ? `${row.place}. ` : ''
  return `${place}${row.name}${row.value ? ` (${row.value})` : ''}`
}

function InvoiceList({ coupling, onChange }: { coupling: Coupling; onChange: () => void }) {
  const [open, setOpen] = useState<number | null>(null)
  const incoming = coupling.direction === 'parent'
  return (
    <div>
      <h4>{incoming ? t('Eingangsrechnungen') : t('Rechnungen an diese Einheit')}</h4>
      <table className="table">
        <thead>
          <tr>
            <th>{t('Nummer')}</th>
            <th>{t('Betreff')}</th>
            <th>{t('fällig')}</th>
            <th className="num">{t('Betrag')}</th>
            <th>{t('Stand')}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {coupling.invoices.map((inv) => (
            <tr key={inv.id}>
              <td>{inv.number}</td>
              <td>{inv.subject}</td>
              <td>{inv.due_date ? formatDate(inv.due_date) : '–'}</td>
              <td className="num">{euro(inv.total)}</td>
              <td>
                <InvoiceState inv={inv} />
              </td>
              <td>
                {inv.download_url && (
                  <a href={inv.download_url} target="_blank" rel="noreferrer">
                    PDF
                  </a>
                )}
                {incoming && inv.status === 'open' && !inv.paid_reported_on && (
                  <>
                    {inv.download_url && ' · '}
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => setOpen(open === inv.id ? null : inv.id)}
                    >
                      {t('bezahlt melden')}
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {open !== null && (
        <ReportPaid
          coupling={coupling}
          inv={coupling.invoices.find((i) => i.id === open)!}
          onDone={() => {
            setOpen(null)
            onChange()
          }}
        />
      )}
    </div>
  )
}

function InvoiceState({ inv }: { inv: CouplingInvoice }) {
  if (inv.status === 'cancelled') return <>storniert</>
  const parts: string[] = []
  if (inv.settled) parts.push('ausgeglichen')
  else if (inv.paid && Number(inv.paid) > 0) parts.push(t('{x} eingegangen', { x: euro(inv.paid) }))
  else parts.push('offen')
  if (inv.paid_reported_on)
    parts.push(t('als bezahlt gemeldet am {x}', { x: formatDate(inv.paid_reported_on) }))
  return <>{parts.join(' · ')}</>
}

function ReportPaid({
  coupling,
  inv,
  onDone,
}: {
  coupling: Coupling
  inv: CouplingInvoice
  onDone: () => void
}) {
  const org = useActiveOrg()
  const canBook = org.permissions.includes(PERM.financeEdit)
  const [date, setDate] = useState(todayIso)
  const [book, setBook] = useState(canBook)
  const [account, setAccount] = useState('')
  const [category, setCategory] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { data: accounts } = useLoad(
    () => (canBook ? financeApi.accounts(org.id) : Promise.resolve([])),
    [org.id, canBook],
  )
  const { data: categories } = useLoad(
    () => (canBook ? financeApi.categories(org.id) : Promise.resolve([])),
    [org.id, canBook],
  )

  async function submit() {
    setErr(null)
    setBusy(true)
    try {
      await peeringApi.reportPaid(org.id, coupling.id, inv.id, {
        date,
        ...(book && account ? { account: Number(account), category: Number(category) } : {}),
      })
      onDone()
    } catch (e) {
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h4>
        {t('Rechnung {number} über {x} als bezahlt melden', {
          number: inv.number,
          x: euro(inv.total),
        })}
      </h4>
      {inv.bank.iban && (
        <p className="muted small">
          {t('Zahlung an {holder}, IBAN', { holder: inv.bank.holder })} {inv.bank.iban}
          {inv.bank.bank_name && ` (${inv.bank.bank_name})`}
          {t(', Verwendungszweck {number}.', { number: inv.number })}
        </p>
      )}
      <label className="field">
        <span>{t('bezahlt am')}</span>
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </label>
      {canBook && (
        <>
          <label className="checkbox">
            <input type="checkbox" checked={book} onChange={(e) => setBook(e.target.checked)} />{' '}
            {t('Ausgabe in der eigenen Kasse buchen (mit der Rechnung als Beleg)')}
          </label>
          {book && (
            <>
              <label className="field">
                <span>{t('Konto')}</span>
                <select value={account} onChange={(e) => setAccount(e.target.value)}>
                  <option value="">{t('bitte wählen')}</option>
                  {(accounts ?? [])
                    .filter((a) => a.is_active)
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                </select>
              </label>
              <label className="field">
                <span>{t('Kategorie')}</span>
                <select value={category} onChange={(e) => setCategory(e.target.value)}>
                  <option value="">{t('bitte wählen')}</option>
                  {(categories ?? [])
                    .filter((c) => c.is_active && c.kind !== 'income')
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                </select>
              </label>
            </>
          )}
        </>
      )}
      <p className="muted small">
        {t(
          'Die Meldung geht an {name}. Als ausgeglichen gilt die Rechnung erst, wenn das Geld dort eingegangen ist.',
          { name: coupling.remote.name },
        )}
      </p>
      {err && <Alert kind="error">{err}</Alert>}
      <div className="button-row">
        <button
          type="button"
          className="button button-primary"
          disabled={busy || (book && canBook && (!account || !category))}
          onClick={() => void submit()}
        >
          {t('Melden')}
        </button>
      </div>
    </div>
  )
}

function RegisterCard({ coupling, onChange }: { coupling: Coupling; onChange: () => void }) {
  const org = useActiveOrg()
  const reg = coupling.register!
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function resolve(member: number, person: number | null) {
    setErr(null)
    setBusy(true)
    try {
      await peeringApi.resolve(org.id, coupling.id, member, person)
      onChange()
    } catch (e) {
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  async function decide(member: number, apply: boolean) {
    setErr(null)
    setBusy(true)
    try {
      await peeringApi.decideCorrection(org.id, coupling.id, member, apply)
      onChange()
    } catch (e) {
      setErr(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const fieldLabel = {
    last_name: t('Nachname'),
    first_name: t('Vorname'),
    birth_date: t('Geburtsdatum'),
  }
  const shown = (field: string, value?: string) =>
    !value ? '–' : field === 'birth_date' ? formatDate(value) : value

  return (
    <div>
      <h4>{t('Namentliche Meldung')}</h4>
      <p className="muted small">
        {reg.counts.active} gemeldet
        {reg.counts.withdrawn > 0 &&
          t(' · {withdrawn} nicht mehr gemeldet (nur Minimum)', {
            withdrawn: reg.counts.withdrawn,
          })}
        {reg.counts.unclear > 0 && t(' · {unclear} Klärfälle', { unclear: reg.counts.unclear })}.
        Die Personen stehen in der Mitgliederliste des Dachverbands unter {coupling.remote.name}.
      </p>
      {reg.unclear.map((u) => (
        <div key={u.id} className="card">
          <p>
            <strong>
              {u.first_name} {u.last_name}
            </strong>
            {u.birth_date && t(', geboren {x}', { x: formatDate(u.birth_date) })}
            {t(': Ist das dieselbe Person?')}
          </p>
          <ul className="plain-list">
            {u.candidates.map((p) => (
              <li key={p.id}>
                {p.name}
                {t(', geboren')} {formatDate(p.birth_date)}
                {p.member_number &&
                  t(' · Verbandsnr. {member_number}', { member_number: p.member_number })}
                {p.units.length > 0 && t(' · {x}', { x: p.units.join(', ') })}{' '}
                <button
                  type="button"
                  className="link-button"
                  disabled={busy}
                  onClick={() => void resolve(u.id, p.id)}
                >
                  {t('dieselbe Person')}
                </button>
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="button"
            disabled={busy}
            onClick={() => void resolve(u.id, null)}
          >
            {t('Andere Person, neu anlegen')}
          </button>
        </div>
      ))}
      {(reg.corrections ?? []).map((c) => (
        <div key={`b${c.id}`} className="card">
          <p>
            <strong>{c.name}</strong>{' '}
            {t('ist auch in einem anderen Verein Mitglied. Der Verein meldet eine Änderung:')}
          </p>
          <ul className="plain-list">
            {(Object.keys(c.proposed) as (keyof typeof fieldLabel)[]).map((f) => (
              <li key={f}>
                {fieldLabel[f]}: {shown(f, c.current[f])} → {shown(f, c.proposed[f])}
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="button"
            disabled={busy}
            onClick={() => void decide(c.id, true)}
          >
            {t('Änderung übernehmen')}
          </button>{' '}
          <button
            type="button"
            className="link-button"
            disabled={busy}
            onClick={() => void decide(c.id, false)}
          >
            {t('Verwerfen')}
          </button>
        </div>
      ))}
      {reg.conflicts.length > 0 && (
        <Alert kind="info">
          {t('Doppelt aktiv gemeldet:')}{' '}
          {reg.conflicts
            .map((c) =>
              t('{name} (auch aktiv in {active_elsewhere})', {
                name: c.name,
                active_elsewhere: c.active_elsewhere,
              }),
            )
            .join(', ')}
          . Bitte mit den Vereinen klären.
        </Alert>
      )}
      {err && <Alert kind="error">{err}</Alert>}
    </div>
  )
}

function TransferCard({ coupling, onChange }: { coupling: Coupling; onChange: () => void }) {
  const org = useActiveOrg()
  const canEdit = org.permissions.includes(PERM.membersEdit)
  const { data: types } = useLoad(() => memberApi.types(org.id), [org.id])
  const [form, setForm] = useState({
    last_name: '',
    first_name: '',
    birth_date: '',
    member_type: '',
    entry_date: todayIso(),
    message: '',
  })
  const [showForm, setShowForm] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run(fn: () => Promise<unknown>) {
    setErr(null)
    setBusy(true)
    try {
      await fn()
      onChange()
      return true
    } catch (e) {
      setErr(errorMessage(e))
      return false
    } finally {
      setBusy(false)
    }
  }

  const active = (types ?? []).filter((tm) => tm.active && !tm.is_archived)
  const passive = (types ?? []).filter((tm) => !tm.active && !tm.is_archived)
  return (
    <div>
      <h4>
        {t('Wechselanfragen über')} {coupling.remote.name}
      </h4>
      <p className="muted small">
        {t(
          'Ist jemand in einer anderen Einheit {name} aktiv, läuft die Aufnahme als aktives Mitglied über eine Wechselanfrage. Die andere Einheit bestätigt Austritt oder eine nicht aktive Art.',
          { name: coupling.remote.name },
        )}
      </p>
      {coupling.transfers.length > 0 && (
        <ul className="plain-list">
          {coupling.transfers.map((tm) => (
            <TransferRow
              key={tm.id}
              t={tm}
              passive={passive}
              disabled={busy || !canEdit}
              onDecide={(data) =>
                void run(() => peeringApi.decideTransfer(org.id, coupling.id, tm.id, data))
              }
            />
          ))}
        </ul>
      )}
      {canEdit && !showForm && (
        <button type="button" className="button" onClick={() => setShowForm(true)}>
          {t('Wechselanfrage stellen')}
        </button>
      )}
      {showForm && (
        <div className="card">
          <div className="grid-2">
            <Field
              label={t('Name')}
              value={form.last_name}
              onChange={(e) => setForm({ ...form, last_name: e.target.value })}
            />
            <Field
              label={t('Vorname')}
              value={form.first_name}
              onChange={(e) => setForm({ ...form, first_name: e.target.value })}
            />
            <Field
              label={t('Geburtsdatum')}
              type="date"
              value={form.birth_date}
              onChange={(e) => setForm({ ...form, birth_date: e.target.value })}
            />
            <Field
              label={t('Eintritt')}
              type="date"
              value={form.entry_date}
              onChange={(e) => setForm({ ...form, entry_date: e.target.value })}
            />
          </div>
          <label className="field">
            <span>{t('Mitgliedsart')}</span>
            <select
              value={form.member_type}
              onChange={(e) => setForm({ ...form, member_type: e.target.value })}
            >
              <option value="">{t('bitte wählen')}</option>
              {active.map((tm) => (
                <option key={tm.id} value={tm.id}>
                  {tm.name}
                </option>
              ))}
            </select>
          </label>
          <Field
            label={t('Nachricht')}
            value={form.message}
            onChange={(e) => setForm({ ...form, message: e.target.value })}
          />
          <div className="button-row">
            <button
              type="button"
              className="button button-primary"
              disabled={busy || !form.last_name || !form.birth_date || !form.member_type}
              onClick={() =>
                void run(() =>
                  peeringApi.requestTransfer(org.id, coupling.id, {
                    ...form,
                    member_type: Number(form.member_type),
                  }),
                ).then((ok) => ok && setShowForm(false))
              }
            >
              {t('Anfrage senden')}
            </button>
            <button type="button" className="link-button" onClick={() => setShowForm(false)}>
              {t('Abbrechen')}
            </button>
          </div>
        </div>
      )}
      {err && <Alert kind="error">{err}</Alert>}
    </div>
  )
}

function TransferRow({
  t: tm,
  passive,
  disabled,
  onDecide,
}: {
  t: RemoteTransfer
  passive: { id: number; name: string }[]
  disabled: boolean
  onDecide: (data: {
    decision: 'exit' | 'change_type' | 'reject'
    member_type?: number
    response?: string
  }) => void
}) {
  const [type, setType] = useState('')
  const [response, setResponse] = useState('')
  const outgoing = tm.role === 'to'
  return (
    <li>
      <strong>{tm.name}</strong>{' '}
      {outgoing
        ? t('· Aufnahme als {x}', { x: tm.member_type_name || 'aktives Mitglied' })
        : t('· möchte zu {to_unit} wechseln ({member_type_name})', {
            to_unit: tm.to_unit,
            member_type_name: tm.member_type_name,
          })}
      {tm.entry_date && t(' ab {x}', { x: formatDate(tm.entry_date) })} · {tm.status_label}
      {tm.message && <span className="muted small"> · „{tm.message}“</span>}
      {tm.response && (
        <span className="muted small">
          {' '}
          {t('· Antwort:')} {tm.response}
        </span>
      )}
      {!outgoing && tm.status === 'pending' && (
        <div className="button-row">
          <button
            type="button"
            className="button"
            disabled={disabled}
            onClick={() => onDecide({ decision: 'exit', response })}
          >
            {t('Austritt bestätigen')}
          </button>
          <select
            aria-label={t('nicht aktive Art')}
            value={type}
            onChange={(e) => setType(e.target.value)}
            disabled={disabled}
          >
            <option value="">{t('nicht aktive Art …')}</option>
            {passive.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="button"
            disabled={disabled || !type}
            onClick={() =>
              onDecide({ decision: 'change_type', member_type: Number(type), response })
            }
          >
            {t('Art ändern')}
          </button>
          <input
            aria-label={t('Antwort')}
            placeholder={t('Antwort (optional)')}
            value={response}
            onChange={(e) => setResponse(e.target.value)}
            disabled={disabled}
          />
          <button
            type="button"
            className="link-button"
            disabled={disabled}
            onClick={() => onDecide({ decision: 'reject', response })}
          >
            ablehnen
          </button>
        </div>
      )}
    </li>
  )
}

function CircularsInfo({ coupling, onChange }: { coupling: Coupling; onChange: () => void }) {
  const org = useActiveOrg()
  const above = coupling.direction === 'parent'
  const receives = coupling.receive.some((r) => r.key === 'circulars' && r.value)
  const [err, setErr] = useState<string | null>(null)
  if (!coupling.circulars?.length && !(above && receives)) return null

  async function toggle(value: boolean) {
    setErr(null)
    try {
      await peeringApi.setOptions(org.id, coupling.id, { circulars_auto: value })
      onChange()
    } catch (e) {
      setErr(errorMessage(e))
    }
  }

  return (
    <div>
      <h4>
        {t('Rundschreiben')}{' '}
        {above ? t('von {name}', { name: coupling.remote.name }) : t('zur Weitergabe')}
      </h4>
      {above && (
        <label className="checkbox">
          <input
            type="checkbox"
            checked={!!coupling.options?.circulars_auto}
            onChange={(e) => void toggle(e.target.checked)}
          />{' '}
          {t('Automatisch an die eigenen Mitglieder weitergeben (sonst als Entwurf zum Prüfen)')}
        </label>
      )}
      {coupling.circulars.length > 0 && (
        <ul className="plain-list">
          {coupling.circulars.map((c) => (
            <li key={c.id}>
              {formatDate(c.created_at)} · {c.subject} · {c.status_label}
              {c.status === 'sent' &&
                t(' · {x} Mails versandt', { x: c.report.sent ?? 0 }) +
                  (c.report.failed
                    ? t(', {failed} fehlgeschlagen', { failed: c.report.failed })
                    : '') +
                  (c.report.letter ? t(', {letter} Briefe', { letter: c.report.letter }) : '')}
            </li>
          ))}
        </ul>
      )}
      {err && <Alert kind="error">{err}</Alert>}
    </div>
  )
}
