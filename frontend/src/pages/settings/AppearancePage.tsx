import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { ChangeEvent } from 'react'
import { api } from '../../api/client.ts'
import { orgApi, PERM } from '../../api/orgs.ts'
import type { ExtraColor, ThemeSettings } from '../../api/orgs.ts'
import { Alert, Checkbox, Field, SaveStatus, LoadError } from '../../components/ui.tsx'
import { errorMessage, useAutoSave, useForm, useLoad } from '../../components/forms.ts'
import { useActiveOrg, useOrg } from '../../org/OrgContext.tsx'
import { contrastRatio, readableOn } from '../../theme/contrast.ts'
import { linkColor, PAGE_BG } from '../../theme/theme.ts'
import { useImageCrop } from '../../components/ImageCrop.tsx'
import { RightsHint } from '../../components/RightsHint.tsx'

export function AppearancePage() {
  const org = useActiveOrg()
  const { data, error, setData, reload } = useLoad(() => orgApi.theme(org.id), [org.id])
  if (error) return <LoadError message={error} onRetry={() => void reload()} />
  if (!data) return <p className="muted">Lädt …</p>
  return <ThemeForm key={org.id} orgId={org.id} theme={data} onSaved={setData} reload={reload} />
}

function ThemeForm({
  orgId,
  theme,
  onSaved,
  reload,
}: {
  orgId: number
  theme: ThemeSettings
  onSaved: (t: ThemeSettings) => void
  reload: () => Promise<void>
}) {
  const { can, refresh } = useOrg()
  const editable = can(PERM.themeEdit)
  const form = useForm({
    primary_color: theme.primary_color,
    accent_color: theme.accent_color,
    primary_color_name: theme.primary_color_name ?? '',
    accent_color_name: theme.accent_color_name ?? '',
    extra_colors: theme.extra_colors ?? [],
  })
  const eff = theme.effective
  const primary = form.values.primary_color || eff.primary
  const accent = form.values.accent_color || eff.accent

  const auto = useAutoSave(form, (changes) => orgApi.updateTheme(orgId, changes), {
    enabled: editable,
    onSaved: (saved) => {
      onSaved(saved as ThemeSettings)
      void refresh()
    },
  })

  return (
    <div className="stack">
      <form className="card card-wide" onSubmit={(e) => e.preventDefault()}>
        <h2>Farben</h2>
        {editable && <SaveStatus auto={auto} />}
        <p className="muted small">
          Ohne eigene Farbe übernimmt die Organisation das Erscheinungsbild der übergeordneten Ebene
          {eff.inherited_from.colors && !theme.primary_color
            ? ` (derzeit von „${eff.inherited_from.colors}“)`
            : ''}
          .
        </p>
        <fieldset disabled={!editable}>
          <ColorInput
            label="Hauptfarbe (Primärfarbe)"
            hint="Kopfzeile, Schaltflächen, Links"
            value={form.values.primary_color}
            inherited={eff.primary}
            error={form.errors.primary_color}
            onChange={(v) => form.set('primary_color', v)}
          />
          <ColorName
            label="Name der Hauptfarbe"
            value={form.values.primary_color_name}
            onChange={(v) => form.set('primary_color_name', v)}
          />
          <ColorInput
            label="Zweitfarbe (Akzentfarbe)"
            hint="Hervorhebungen"
            value={form.values.accent_color}
            inherited={eff.accent}
            error={form.errors.accent_color}
            onChange={(v) => form.set('accent_color', v)}
          />
          <ColorName
            label="Name der Zweitfarbe"
            value={form.values.accent_color_name}
            onChange={(v) => form.set('accent_color_name', v)}
          />
          <ExtraColors
            colors={form.values.extra_colors}
            error={form.errors.extra_colors}
            ownPrimary={Boolean(form.values.primary_color)}
            onChange={(v) => form.set('extra_colors', v)}
          />
        </fieldset>

        <h3>Vorschau</h3>
        <div className="theme-preview">
          <span
            className="preview-chip"
            style={{ background: primary, color: readableOn(primary) }}
          >
            Schaltfläche
          </span>
          <span className="preview-chip" style={{ background: accent, color: readableOn(accent) }}>
            Hinweis
          </span>
          {/* Dieselbe abgeleitete Linkfarbe wie in der App (UI-Audit NUI-04) */}
          <span style={{ color: linkColor(primary) }} className="preview-link">
            Link auf weißem Grund
          </span>
          <span
            style={{ color: linkColor(primary), background: PAGE_BG }}
            className="preview-link preview-on-page"
          >
            Link auf dem Seitenhintergrund
          </span>
        </div>
        <ContrastHints primary={primary} accent={accent} />
        <p className="muted small">
          Welches Design die Webseite hat und wo es welche Farbe einsetzt, stellst du unter{' '}
          <Link to="/webseite/gestaltung">Webseite › Gestaltung</Link> ein.
        </p>
      </form>

      <div className="card card-wide">
        <h2>Logo / Wappen</h2>
        {editable ? (
          <LogoUpload
            uploadUrl={orgApi.logoUrl(orgId)}
            logoUrl={theme.logo_url}
            onChange={async () => {
              await reload()
              await refresh()
            }}
          />
        ) : theme.logo_url ? (
          <img src={theme.logo_url} alt="Logo" className="logo-preview" />
        ) : (
          <p className="muted">Kein eigenes Logo.</p>
        )}
        {!theme.logo_url && eff.logo_url && (
          <p className="muted small">Angezeigt wird das Logo von „{eff.inherited_from.logo}“.</p>
        )}
      </div>
    </div>
  )
}

function ColorInput({
  label,
  hint,
  value,
  inherited,
  error,
  onChange,
}: {
  label: string
  hint: string
  value: string
  inherited: string
  error?: string
  onChange: (v: string) => void
}) {
  return (
    <div className={`field color-field${error ? ' field-invalid' : ''}`}>
      <span>{label}</span>
      <div className="color-row">
        <input
          type="color"
          aria-label={`${label} wählen`}
          value={value || inherited}
          onChange={(e) => onChange(e.target.value)}
        />
        <input
          aria-label={`${label} als Hex-Wert`}
          value={value}
          placeholder={`${inherited} (geerbt)`}
          onChange={(e) => onChange(e.target.value.trim())}
        />
        {value && (
          <button type="button" className="button button-ghost" onClick={() => onChange('')}>
            Erben
          </button>
        )}
      </div>
      <small className={error ? 'field-error' : 'muted'}>{error ?? hint}</small>
    </div>
  )
}

function ColorName({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (v: string) => void
}) {
  return (
    <Field
      label={label}
      value={value}
      maxLength={30}
      placeholder="z. B. Grün"
      hint="Erscheint bei der Auswahl der Farben für die Webseite."
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

const MAX_EXTRA = 4

/** Weitere Farben der Einheit (zusammen bis sechs); genutzt von den Webseiten-Designs */
function ExtraColors({
  colors,
  error,
  ownPrimary,
  onChange,
}: {
  colors: ExtraColor[]
  error?: string
  ownPrimary: boolean
  onChange: (v: ExtraColor[]) => void
}) {
  const update = (i: number, patch: Partial<ExtraColor>) =>
    onChange(colors.map((c, j) => (j === i ? { ...c, ...patch } : c)))
  const move = (i: number, d: number) => {
    const next = [...colors]
    ;[next[i], next[i + d]] = [next[i + d], next[i]]
    onChange(next)
  }
  return (
    <div className={`field${error ? ' field-invalid' : ''}`}>
      <span>Weitere Farben</span>
      <small className="muted">
        Für Einheiten mit drei oder mehr Vereinsfarben. Die Webseiten-Designs nutzen sie für
        Zierlinien, Farbbänder und Datumsfelder.
        {!ownPrimary && ' Weitere Farben gelten nur zusammen mit einer eigenen Hauptfarbe.'}
      </small>
      {colors.map((c, i) => {
        const valid = /^#[0-9a-f]{6}$/i.test(c.color)
        const ratio = valid ? contrastRatio(c.color, readableOn(c.color)) : 0
        return (
          <div className="color-row" key={i}>
            <input
              type="color"
              aria-label={`${i + 3}. Farbe wählen`}
              value={valid ? c.color : '#000000'}
              onChange={(e) => update(i, { color: e.target.value })}
            />
            <input
              aria-label={`${i + 3}. Farbe als Hex-Wert`}
              value={c.color}
              onChange={(e) => update(i, { color: e.target.value.trim() })}
            />
            <input
              aria-label={`Name der ${i + 3}. Farbe`}
              value={c.name}
              maxLength={30}
              placeholder="Name, z. B. Weinrot"
              onChange={(e) => update(i, { name: e.target.value })}
            />
            {valid && (
              <span className={`small ${ratio >= 4.5 ? 'ok' : 'bad'}`}>
                {ratio >= 4.5 ? '✓' : '✗'} Text darauf {ratio.toFixed(1)} : 1
              </span>
            )}
            <button
              type="button"
              className="button button-ghost"
              aria-label={`${i + 3}. Farbe nach oben`}
              disabled={i === 0}
              onClick={() => move(i, -1)}
            >
              ↑
            </button>
            <button
              type="button"
              className="button button-ghost"
              aria-label={`${i + 3}. Farbe nach unten`}
              disabled={i === colors.length - 1}
              onClick={() => move(i, 1)}
            >
              ↓
            </button>
            <button
              type="button"
              className="button button-ghost"
              onClick={() => onChange(colors.filter((_, j) => j !== i))}
            >
              Entfernen
            </button>
          </div>
        )
      })}
      {colors.length < MAX_EXTRA && (
        <div>
          <button
            type="button"
            className="button button-ghost"
            onClick={() => onChange([...colors, { color: '#8b1e2d', name: '' }])}
          >
            Farbe hinzufügen
          </button>
        </div>
      )}
      {error && <small className="field-error">{error}</small>}
    </div>
  )
}

function ContrastHints({ primary, accent }: { primary: string; accent: string }) {
  if (!/^#[0-9a-f]{6}$/i.test(primary) || !/^#[0-9a-f]{6}$/i.test(accent)) return null
  const checks = [
    { label: 'Text auf Primärfarbe', ratio: contrastRatio(primary, readableOn(primary)), min: 4.5 },
    {
      label: 'Primärfarbe auf Weiß (Rahmen, Symbole)',
      ratio: contrastRatio(primary, '#ffffff'),
      min: 3,
    },
    { label: 'Text auf Akzentfarbe', ratio: contrastRatio(accent, readableOn(accent)), min: 4.5 },
  ]
  const link = linkColor(primary)
  return (
    <ul className="contrast-list">
      {checks.map((c) => (
        <li key={c.label} className={c.ratio >= c.min ? 'ok' : 'bad'}>
          {c.ratio >= c.min ? '✓' : '✗'} {c.label}: {c.ratio.toFixed(1)} : 1 (mind. {c.min} : 1)
        </li>
      ))}
      <li className="ok">
        ✓ Links auf Weiß und auf dem Seitenhintergrund:{' '}
        {Math.min(contrastRatio(link, '#ffffff'), contrastRatio(link, PAGE_BG)).toFixed(1)} : 1
        (mind. 4.5 : 1)
        {link.toLowerCase() !== primary.toLowerCase() && (
          <>
            {' '}
            – dafür wird automatisch ein dunklerer Ton verwendet{' '}
            <span className="color-swatch" style={{ background: link }} aria-hidden="true" /> {link}
          </>
        )}
      </li>
    </ul>
  )
}

export function LogoUpload({
  uploadUrl,
  logoUrl,
  onChange,
}: {
  uploadUrl: string
  logoUrl: string | null
  onChange: () => void | Promise<void>
}) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Wappen kommen oft mit weißem Hintergrund; der wird standardmäßig entfernt
  const [removeBackground, setRemoveBackground] = useState(true)
  const crop = useImageCrop({ title: 'Ausschnitt für Logo/Wappen', maxSide: 1024 })

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const chosen = e.target.files?.[0]
    e.target.value = ''
    if (!chosen) return
    const file = await crop.pick(chosen)
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      await orgApi.uploadLogo(uploadUrl, file, removeBackground)
      await onChange()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    try {
      await api.del(uploadUrl)
      await onChange()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="logo-upload-box">
      {logoUrl && <img src={logoUrl} alt="Logo" className="logo-preview logo-preview-checker" />}
      <div className="button-row">
        <label className="button button-ghost">
          {logoUrl ? 'Anderes Bild wählen' : 'Bild hochladen'}
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="file-input"
            disabled={busy}
            onChange={upload}
          />
        </label>
        {crop.dialog}
        <RightsHint />
        {logoUrl && (
          <button type="button" className="button button-ghost" onClick={remove} disabled={busy}>
            Entfernen
          </button>
        )}
      </div>
      <Checkbox
        label="Weißen Hintergrund entfernen"
        hint="Weiß am Rand wird durchsichtig, Weiß im Wappen bleibt"
        checked={removeBackground}
        onChange={setRemoveBackground}
        disabled={busy}
      />
      <p className="muted small">PNG, JPG oder WebP, höchstens 2 MB.</p>
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}
