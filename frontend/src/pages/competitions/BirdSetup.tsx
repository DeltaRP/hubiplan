// Vogelschießen einrichten (Pfänder) und nachträglich erfassen, dazu der Standzugang für
// ein geliehenes Gerät (QR-Code).
import { useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import {
  competitionsApi,
  type BirdState,
  type CompetitionDetail,
  type StandAccessInfo,
} from '../../api/competitions.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, useLoad } from '../../components/forms.ts'
import { Alert, LoadError } from '../../components/ui.tsx'
import { HowTo, Term, Why } from '../../learning/Aids.tsx'
import { locale } from '../../i18n/index.ts'

function numOrNull(text: string): number | null {
  const n = parseInt(text, 10)
  return Number.isFinite(n) && n > 0 ? n : null
}

/** Pfänder: Namen, Preis, Reihenfolge (Wettbewerbe verwalten). */
export function PrizesCard({
  org,
  comp,
  onChanged,
}: {
  org: number
  comp: CompetitionDetail
  onChanged: () => void
}) {
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const closed = comp.status === 'endgueltig'
  const prizes = [...comp.prizes].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)

  async function run(action: () => Promise<unknown>) {
    try {
      await action()
      setError(null)
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function move(i: number, dir: -1 | 1) {
    const other = prizes[i + dir]
    if (!other) return
    const a = prizes[i]
    await run(async () => {
      await competitionsApi.updatePrize(org, comp.id, a.id, { sort_order: i + dir + 1 })
      await competitionsApi.updatePrize(org, comp.id, other.id, { sort_order: i + 1 })
    })
  }

  return (
    <div className="card card-wide">
      <h2>Pfänder</h2>
      <p className="muted">
        In der Reihenfolge, in der sie meist fallen. Namen und Anzahl sind frei (z. B. „Zepter“,
        „Apfel“, „Krone“ beim Königsvogel).
      </p>
      <ul className="prize-setup">
        {prizes.map((p, i) => (
          <li key={p.id}>
            <input
              aria-label="Pfand"
              defaultValue={p.name}
              disabled={closed}
              onBlur={(e) => {
                const v = e.target.value.trim()
                if (v && v !== p.name)
                  void run(() => competitionsApi.updatePrize(org, comp.id, p.id, { name: v }))
              }}
            />
            <input
              aria-label={`Preis für ${p.name}`}
              placeholder="Preis (optional)"
              defaultValue={p.award}
              disabled={closed}
              onBlur={(e) => {
                if (e.target.value.trim() !== p.award)
                  void run(() =>
                    competitionsApi.updatePrize(org, comp.id, p.id, {
                      award: e.target.value.trim(),
                    }),
                  )
              }}
            />
            {!closed && (
              <span className="button-row">
                <button
                  type="button"
                  className="button button-ghost"
                  aria-label={`${p.name} nach oben`}
                  disabled={i === 0}
                  onClick={() => void move(i, -1)}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="button button-ghost"
                  aria-label={`${p.name} nach unten`}
                  disabled={i === prizes.length - 1}
                  onClick={() => void move(i, 1)}
                >
                  ↓
                </button>
                <button
                  type="button"
                  className="button button-ghost"
                  onClick={async () => {
                    const ok = await confirmDialog({
                      title: 'Pfand entfernen',
                      message: `„${p.name}“ entfernen?`,
                      confirmLabel: 'Entfernen',
                    })
                    if (ok) await run(() => competitionsApi.removePrize(org, comp.id, p.id))
                  }}
                >
                  Entfernen
                </button>
              </span>
            )}
          </li>
        ))}
      </ul>
      {!closed && (
        <form
          className="button-row"
          onSubmit={(e) => {
            e.preventDefault()
            if (!name.trim()) return
            void run(() => competitionsApi.addPrize(org, comp.id, name.trim())).then(() =>
              setName(''),
            )
          }}
        >
          <input
            aria-label="Neues Pfand"
            placeholder="Neues Pfand"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button type="submit" className="button button-ghost">
            Pfand hinzufügen
          </button>
        </form>
      )}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}

/** Nachträglich erfassen: je Pfand wer, mit dem wievielten Schuss, Schüsse für das Pfand. */
export function ManualPrizes({ org, comp }: { org: number; comp: CompetitionDetail }) {
  const bird = useLoad(() => competitionsApi.bird(org, comp.id), [org, comp.id])
  const starters = useLoad(() => competitionsApi.starters(org, comp.id), [org, comp.id])
  const [error, setError] = useState<string | null>(null)
  const closed = comp.status === 'endgueltig'
  if (bird.error) return <LoadError message={bird.error} onRetry={bird.reload} />
  if (!bird.data || !starters.data) return null
  const state: BirdState = bird.data

  async function save(prize: number, data: Parameters<typeof competitionsApi.updatePrize>[3]) {
    try {
      bird.setData(await competitionsApi.updatePrize(org, comp.id, prize, data))
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <details className="card card-wide">
      <summary>
        <strong>Nachträglich erfassen</strong>{' '}
        <span className="muted">(wenn am Stand auf Papier gezählt wurde)</span>
      </summary>
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>
                <Term k="comp_prize">Pfand</Term>
              </th>
              <th>Schütze</th>
              <th className="num">Schuss Nr. gesamt</th>
              <th className="num">
                <Term k="comp_shots_for">Schüsse für das Pfand</Term>
              </th>
            </tr>
          </thead>
          <tbody>
            {state.prizes.map((p) => (
              <tr key={`${p.id}-${p.winner}-${p.shot_number}-${p.shots_for}`}>
                <td>{p.name}</td>
                <td>
                  <select
                    aria-label={`Schütze für ${p.name}`}
                    disabled={closed}
                    value={p.winner ?? ''}
                    onChange={(e) =>
                      void save(p.id, { winner: e.target.value ? Number(e.target.value) : null })
                    }
                  >
                    <option value="">– hängt noch –</option>
                    {starters.data
                      ?.slice()
                      .sort((a, b) => a.name.localeCompare(b.name))
                      .map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                          {s.number ? ` (${s.number})` : ''}
                        </option>
                      ))}
                  </select>
                </td>
                <td className="num">
                  <input
                    aria-label={`Schuss Nr. für ${p.name}`}
                    inputMode="numeric"
                    className="input-narrow"
                    disabled={closed || !p.fallen}
                    defaultValue={p.shot_number ?? ''}
                    onBlur={(e) => {
                      const v = numOrNull(e.target.value)
                      if (v !== p.shot_number) void save(p.id, { shot_number: v })
                    }}
                  />
                </td>
                <td className="num">
                  <input
                    aria-label={`Schüsse für ${p.name}`}
                    inputMode="numeric"
                    className="input-narrow"
                    disabled={closed || !p.fallen}
                    defaultValue={p.shots_for ?? ''}
                    onBlur={(e) => {
                      const v = numOrNull(e.target.value)
                      if (v !== p.shots_for) void save(p.id, { shots_for: v })
                    }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Die Gesamtzahl der Schüsse steht unter „Einrichten“. Starter kommen über „Schützen und
        Losnummern“ oben dazu.
      </p>
      <HowTo k="how_comp_shots_for" />
      {error && <Alert kind="error">{error}</Alert>}
    </details>
  )
}

/** Standzugang: Link und QR-Code, der nur diesen Wettbewerb im Standmodus öffnet. */
export function StandAccessCard({ org, comp }: { org: number; comp: CompetitionDetail }) {
  const list = useLoad(() => competitionsApi.standAccesses(org, comp.id), [org, comp.id])
  const [label, setLabel] = useState('')
  const [created, setCreated] = useState<StandAccessInfo | null>(null)
  const [error, setError] = useState<string | null>(null)
  const link = created?.token ? `${window.location.origin}/stand/zugang/${created.token}` : ''

  async function create() {
    try {
      const res = await competitionsApi.createStandAccess(org, comp.id, label.trim())
      setCreated(res)
      setLabel('')
      setError(null)
      void list.reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function revoke(a: StandAccessInfo) {
    const ok = await confirmDialog({
      title: 'Standzugang beenden',
      message: `Den Standzugang ${a.label ? `„${a.label}“ ` : ''}beenden? Das Gerät kann danach nichts mehr eintragen.`,
      confirmLabel: 'Beenden',
    })
    if (!ok) return
    try {
      await competitionsApi.revokeStandAccess(org, comp.id, a.id)
      if (created?.id === a.id) setCreated(null)
      void list.reload()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const active = (list.data ?? []).filter((a) => a.active)
  return (
    <div className="card card-wide">
      <h2>
        <Term k="comp_stand_access_term">Standzugang</Term> für ein geliehenes Gerät
      </h2>
      <p className="muted">
        Öffnet nur diesen Wettbewerb im <Term k="comp_stand_mode">Standmodus</Term>, ohne Anmeldung.
        Das Gerät kann nur erfassen und sieht von Mitgliedern nur Name und Untereinheit. Der Zugang
        endet am Ende des Wettbewerbstags oder wenn du ihn beendest.
      </p>
      {comp.status !== 'endgueltig' && (
        <div className="button-row">
          <input
            aria-label="Bezeichnung des Geräts"
            placeholder="z. B. Tablet Stand 1"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <button type="button" className="button" onClick={() => void create()}>
            Standzugang erzeugen
          </button>
        </div>
      )}
      {created && link && (
        <div className="stand-access-new">
          <QRCodeSVG value={link} size={200} marginSize={2} title="QR-Code für den Standzugang" />
          <p>
            Mit dem Gerät den QR-Code scannen oder diesen Link öffnen. Er erscheint nur jetzt:
            <br />
            <code className="break-all">{link}</code>
          </p>
          <div className="button-row">
            <button
              type="button"
              className="button button-ghost"
              onClick={() => void navigator.clipboard?.writeText(link)}
            >
              Link kopieren
            </button>
          </div>
        </div>
      )}
      {active.length > 0 && (
        <ul className="stand-list">
          {active.map((a) => (
            <li key={a.id}>
              {a.label || 'Standzugang'}{' '}
              <span className="muted">
                bis{' '}
                {new Date(a.expires_at).toLocaleString(locale(), {
                  dateStyle: 'short',
                  timeStyle: 'short',
                })}
              </span>
              <button
                type="button"
                className="button button-ghost push-right"
                onClick={() => void revoke(a)}
              >
                Beenden
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <Alert kind="error">{error}</Alert>}
      <Why k="comp_stand_access" />
      <HowTo k="how_comp_tablets" />
    </div>
  )
}
