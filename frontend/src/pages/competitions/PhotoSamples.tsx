// Bestätigte Spiegelausschnitte sammeln (Schießscheiben Schritt 6). Nur mit Einwilligung des
// Vereins (Ralf 01.11.2026): standardmäßig aus, jederzeit abschaltbar und löschbar.
// Steht unter Einstellungen › Datenschutz, nicht auf der Wettbewerbsliste (Ralf 01.11.).
import { useState } from 'react'
import { competitionsApi } from '../../api/competitions.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, useLoad } from '../../components/forms.ts'
import { Alert, Checkbox } from '../../components/ui.tsx'
import { Why } from '../../learning/Aids.tsx'

export function PhotoSamplesCard({ org }: { org: number }) {
  const { data, setData } = useLoad(() => competitionsApi.photoSamples(org), [org])
  const [error, setError] = useState<string | null>(null)
  if (!data) return null

  async function toggle(on: boolean) {
    setError(null)
    try {
      setData(await competitionsApi.setPhotoSamples(org, on))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function remove() {
    const ok = await confirmDialog({
      title: 'Ausschnitte löschen',
      message: `Alle ${data?.count} gesammelten Spiegelausschnitte endgültig löschen?`,
      confirmLabel: 'Löschen',
    })
    if (!ok) return
    setError(null)
    try {
      setData(await competitionsApi.deletePhotoSamples(org))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <section className="card card-wide">
      <h2>
        Fotoerkennung verbessern{' '}
        <span className="muted small">({data.enabled ? 'Sammeln an' : 'Sammeln aus'})</span>
      </h2>
      <p className="muted small">
        Wenn ihr Treffer aus einem Foto bestätigt, kann HUBIplan den Ausschnitt des Spiegels mit den
        bestätigten Treffern aufbewahren. Damit lässt sich die Erkennung später an echten Scheiben
        prüfen und verbessern. Gespeichert wird nur das entzerrte Schwarzweißbild eines Spiegels und
        die Trefferlage, ohne Namen, ohne Wettbewerb und ohne Uhrzeit. Das ganze Foto wird nie
        gespeichert.
      </p>
      <Checkbox
        label="Bestätigte Spiegelausschnitte sammeln"
        checked={data.enabled}
        disabled={!data.can_manage}
        onChange={(on) => void toggle(on)}
      />
      <p className="small">
        Gesammelt: {data.count} {data.count === 1 ? 'Ausschnitt' : 'Ausschnitte'}.
        {data.enabled ? '' : ' Ausschalten löscht nichts.'}
      </p>
      {data.can_manage && data.count > 0 && (
        <div className="button-row">
          <button type="button" className="button button-ghost" onClick={() => void remove()}>
            Alle Ausschnitte löschen
          </button>
        </div>
      )}
      {error && <Alert kind="error">{error}</Alert>}
      <Why k="comp_photo_samples" />
    </section>
  )
}
