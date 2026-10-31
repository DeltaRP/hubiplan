// Datenschutzhinweise der Webseite (für Besucher). Gepflegt unter Einstellungen › Datenschutz,
// zusammen mit den Datenschutzhinweisen für Mitglieder.
import { useState } from 'react'
import { websiteApi } from '../../api/website.ts'
import type { Website, WebsiteData, WebsitePrivacy } from '../../api/website.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, formatDateTime, useAutoSave, useForm } from '../../components/forms.ts'
import { PrivacyPublish } from '../../components/PrivacyPublish.tsx'
import { Alert, Field, SaveStatus, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { TextEditor } from '../../components/texteditor/TextEditor.tsx'

export function PrivacyCard({
  data,
  website,
  onChange,
}: {
  data: WebsiteData
  website: Website
  onChange: (data: WebsiteData) => void
}) {
  // Nach dem Erzeugen neu aufbauen, damit der erzeugte Text im Feld steht
  return (
    <PrivacyForm
      key={website.privacy_generated_at ?? ''}
      data={data}
      website={website}
      onChange={onChange}
    />
  )
}

function PrivacyForm({
  data,
  website,
  onChange,
}: {
  data: WebsiteData
  website: Website
  onChange: (data: WebsiteData) => void
}) {
  const org = useActiveOrg()
  const form = useForm<WebsitePrivacy>({
    privacy_mode: website.privacy_mode,
    privacy_text: website.privacy_text,
    privacy_url: website.privacy_url,
  })
  const values = form.values
  const [error, setError] = useState<string | null>(null)
  const outdated = website.checks.some((c) => c.key === 'privacy_outdated')

  // Der Entwurf speichert automatisch; öffentlich wird er erst mit „Veröffentlichen“
  const auto = useAutoSave(form, (changes) => websiteApi.save(org.id, changes), {
    enabled: data.can_manage,
    onSaved: (result) => onChange(result as WebsiteData),
  })

  async function run(action: () => Promise<WebsiteData>) {
    setError(null)
    // Erst Offenes speichern, damit nichts verloren geht oder Erzeugtes überschreibt
    if (!(await auto.flush())) return
    try {
      onChange(await action())
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function generate() {
    if (
      values.privacy_text.trim() &&
      !(await confirmDialog({
        title: 'Datenschutzhinweise neu erzeugen?',
        message: 'Der bisherige Text wird ersetzt. Eigene Ergänzungen bitte vorher sichern.',
        confirmLabel: 'Neu erzeugen',
      }))
    )
      return
    await run(() => websiteApi.generatePrivacy(org.id))
  }

  return (
    <div className="card card-wide">
      <h2>Datenschutzhinweise der Webseite</h2>
      <p className="muted small">
        Für Besucher der Webseite: Zugriffsdaten, Kontaktformular, Kalender-Abo, Personen auf der
        Seite, Links zu sozialen Netzwerken. Die Fußzeile der Webseite verlinkt diesen Text.
        HUBIplan erzeugt einen Entwurf passend zu den Bausteinen; Angaben in eckigen Klammern bitte
        ergänzen. Erzeugen und Bearbeiten ändern nur den Entwurf (er speichert automatisch),
        öffentlich wird er erst mit „Veröffentlichen“. Ein Vorschlag, keine Rechtsberatung.
      </p>
      {data.can_manage && <SaveStatus auto={auto} />}
      {outdated && (
        <Alert kind="info">
          Die Bausteine haben sich seit der Erzeugung geändert. Bitte neu erzeugen und prüfen.
        </Alert>
      )}
      {error && <Alert kind="error">{error}</Alert>}
      <fieldset disabled={!data.can_manage}>
        <SelectField
          label="Datenschutzhinweise"
          value={values.privacy_mode}
          error={form.errors.privacy_mode}
          onChange={(e) =>
            form.set('privacy_mode', e.target.value as WebsitePrivacy['privacy_mode'])
          }
        >
          <option value="text">eigener Text</option>
          <option value="link">auf eigene Seite verlinken</option>
        </SelectField>
        {values.privacy_mode === 'link' ? (
          <Field
            label="Adresse der Datenschutzhinweise"
            type="url"
            value={values.privacy_url}
            error={form.errors.privacy_url}
            onChange={(e) => form.set('privacy_url', e.target.value)}
          />
        ) : (
          <TextEditor
            label="Entwurf der Datenschutzhinweise"
            value={values.privacy_text}
            error={form.errors.privacy_text}
            rows={14}
            hint={
              website.privacy_generated_at
                ? `Zuletzt erzeugt: ${formatDateTime(website.privacy_generated_at)}`
                : undefined
            }
            onChange={(text) => form.set('privacy_text', text)}
          />
        )}
        {values.privacy_mode === 'text' && (
          <div className="button-row">
            <button type="button" className="button" onClick={() => void generate()}>
              {values.privacy_text.trim() ? 'Entwurf neu erzeugen' : 'Textentwurf erzeugen'}
            </button>
          </div>
        )}
        {values.privacy_mode === 'text' && (
          <PrivacyPublish
            draft={values.privacy_text}
            publishedText={website.privacy_published_text}
            publishedAt={website.privacy_published_at}
            disabled={!data.can_manage}
            onFill={(next) => form.set('privacy_text', next)}
            // Entwurf zuerst speichern, damit genau dieser Stand veröffentlicht wird
            onPublish={() => run(() => websiteApi.publishPrivacy(org.id))}
          />
        )}
      </fieldset>
    </div>
  )
}
