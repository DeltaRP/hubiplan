// Webseite › Social Media: Instagram-Profikonto und Facebook-Seite verbinden.
// HUBIplan holt die eigenen Beiträge serverseitig ab und speichert Text und Bilder
// selbst; Besucher der Webseite haben keinen Kontakt zu Meta. Jede Einheit nutzt
// ihre eigene Meta-App (App-ID und App-Geheimnis von developers.facebook.com).
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { leaveTo } from '../../api/peering.ts'
import { socialApi } from '../../api/website.ts'
import type { SocialFeed, SocialKind, SocialPost } from '../../api/website.ts'
import { confirmDialog } from '../../components/dialog.ts'
import { errorMessage, formatDate, formatDateTime, useLoad } from '../../components/forms.ts'
import { Alert, Checkbox, Field, LoadError, SelectField } from '../../components/ui.tsx'
import { useActiveOrg } from '../../org/OrgContext.tsx'
import { Why } from '../../learning/Aids.tsx'
import { t } from '../../i18n/index.ts'

const KIND_LABEL: Record<SocialKind, string> = {
  instagram: t('Instagram'),
  facebook: t('Facebook-Seite'),
}

export function SocialPage() {
  const org = useActiveOrg()
  const [params, setParams] = useSearchParams()
  const { data, error, reload } = useLoad(() => socialApi.list(org.id), [org.id])
  const [adding, setAdding] = useState(false)

  if (error) return <LoadError message={error} onRetry={() => void reload()} />
  if (!data) return <p className="muted">{t('Lädt …')}</p>

  const back = params.get('verbunden') ? 'ok' : params.get('fehler')
  return (
    <>
      {back && (
        <Alert kind={back === 'ok' ? 'success' : 'error'}>
          {back === 'ok'
            ? t('Verbunden, die Beiträge wurden abgerufen.')
            : t('Nicht verbunden: {back}', { back })}{' '}
          <button type="button" className="link-button" onClick={() => setParams({})}>
            {t('Ausblenden')}
          </button>
        </Alert>
      )}
      <div className="card card-wide">
        <h2>{t('Instagram und Facebook')}</h2>
        <p className="muted small">
          {t(
            'HUBIplan holt die Beiträge eurer eigenen Kanäle alle 30 Minuten ab und speichert Text und Fotos selbst. Die Webseite zeigt sie unter „Aktuelles“ und, wenn ihr wollt, auf der Startseite. Besucher haben dabei keinen Kontakt zu Instagram oder Facebook, es gibt keine Cookies und kein Tracking. Was ihr dort löscht, verschwindet auch hier.',
          )}
        </p>
        <Why k="web_social" />
        {data.feeds.length === 0 && <p className="muted">{t('Noch kein Kanal angelegt.')}</p>}
        {data.feeds.map((f) => (
          <FeedCard
            key={f.id}
            feed={f}
            canManage={data.can_manage}
            redirectUri={data.redirect_uri}
            onChanged={() => void reload()}
          />
        ))}
        {data.can_manage &&
          (adding ? (
            <NewFeed
              units={data.units}
              existing={data.feeds}
              onDone={() => {
                setAdding(false)
                void reload()
              }}
            />
          ) : (
            <div className="button-row">
              <button type="button" className="button" onClick={() => setAdding(true)}>
                {t('Kanal hinzufügen')}
              </button>
            </div>
          ))}
      </div>
      {data.can_manage && <SetupGuide redirectUri={data.redirect_uri} />}
    </>
  )
}

function NewFeed({
  units,
  existing,
  onDone,
}: {
  units: { id: number; name: string }[]
  existing: SocialFeed[]
  onDone: () => void
}) {
  const org = useActiveOrg()
  const [kind, setKind] = useState<SocialKind>('instagram')
  const [department, setDepartment] = useState<number | null>(null)
  // Beim Anlegen ausdrücklich wählen, „erst nach Freigabe“ vorausgewählt (UX-Audit 31.10. F10)
  const [mode, setMode] = useState<SocialFeed['mode']>('approval')
  const [error, setError] = useState<string | null>(null)
  const taken = existing.some((f) => f.kind === kind && f.department === department)
  async function create() {
    setError(null)
    try {
      await socialApi.create(org.id, { kind, department, mode })
      onDone()
    } catch (err) {
      setError(errorMessage(err))
    }
  }
  return (
    <div className="social-feed">
      <div className="grid-2">
        <SelectField
          label={t('Netzwerk')}
          value={kind}
          onChange={(e) => setKind(e.target.value as SocialKind)}
        >
          <option value="instagram">{t('Instagram (Profikonto)')}</option>
          <option value="facebook">{t('Facebook-Seite')}</option>
        </SelectField>
        {units.length > 0 && (
          <SelectField
            label={t('Kanal von')}
            value={department ?? ''}
            onChange={(e) => setDepartment(e.target.value ? Number(e.target.value) : null)}
            hint={t('Kanäle einer Untereinheit erscheinen auf ihrer Seite.')}
          >
            <option value="">{org.name}</option>
            {units.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </SelectField>
        )}
        <SelectField
          label={t('Abgerufene Beiträge')}
          value={mode}
          onChange={(e) => setMode(e.target.value as SocialFeed['mode'])}
          hint={t(
            '„Erst nach Freigabe“, wenn Fotos von Dritten dabei sein können. Später änderbar.',
          )}
        >
          <option value="approval">{t('erst nach Freigabe zeigen')}</option>
          <option value="auto">{t('automatisch zeigen')}</option>
        </SelectField>
      </div>
      {taken && <Alert kind="info">{t('Diesen Kanal gibt es hier schon.')}</Alert>}
      {error && <Alert kind="error">{error}</Alert>}
      <div className="button-row">
        <button type="button" className="button" disabled={taken} onClick={() => void create()}>
          {t('Anlegen')}
        </button>
        <button type="button" className="button button-ghost" onClick={onDone}>
          {t('Abbrechen')}
        </button>
      </div>
    </div>
  )
}

function statusText(f: SocialFeed): string {
  if (f.status === 'ok') {
    const until = f.token_expires_at
      ? t(', Zugang bis {x}', { x: formatDate(f.token_expires_at) })
      : ''
    const last = f.last_sync_at
      ? t(', zuletzt abgerufen {x}', { x: formatDateTime(f.last_sync_at) })
      : ''
    return t('verbunden mit {x}{until}{last}', { x: f.account_name || t('dem Konto'), until, last })
  }
  return f.status_label
}

function FeedCard({
  feed,
  canManage,
  redirectUri,
  onChanged,
}: {
  feed: SocialFeed
  canManage: boolean
  redirectUri: string
  onChanged: () => void
}) {
  const org = useActiveOrg()
  const [open, setOpen] = useState(feed.status === 'new' || feed.status === 'choose')
  const [appId, setAppId] = useState(feed.app_id)
  const [configId, setConfigId] = useState(feed.config_id)
  const [viaFacebook, setViaFacebook] = useState(feed.via_facebook)
  const [secret, setSecret] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [showPosts, setShowPosts] = useState(false)

  async function run(action: () => Promise<unknown>, done?: string) {
    setBusy(true)
    setError(null)
    setInfo(null)
    try {
      await action()
      if (done) setInfo(done)
      onChanged()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function connect() {
    setBusy(true)
    setError(null)
    try {
      if (
        appId !== feed.app_id ||
        configId !== feed.config_id ||
        viaFacebook !== feed.via_facebook ||
        secret
      ) {
        await socialApi.save(org.id, feed.id, {
          app_id: appId,
          config_id: configId,
          via_facebook: viaFacebook,
          ...(secret ? { app_secret: secret } : {}),
        })
      }
      const { url } = await socialApi.connect(org.id, feed.id)
      leaveTo.go(url)
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  const title = `${KIND_LABEL[feed.kind]}${feed.department_name ? ` (${feed.department_name})` : ''}`
  const connected = feed.status === 'ok' || feed.status === 'error'
  return (
    <section className="social-feed" aria-label={title}>
      <h3>
        <button
          type="button"
          className="link-button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {title}
        </button>
      </h3>
      <p className="small">
        {statusText(feed)}
        {feed.post_count > 0 && t(' · {post_count} Beiträge', { post_count: feed.post_count })}
        {feed.pending_count > 0 &&
          t(' · {pending_count} warten auf Freigabe', { pending_count: feed.pending_count })}
      </p>
      {feed.last_error && feed.status !== 'ok' && <Alert kind="error">{feed.last_error}</Alert>}
      {open && (
        <>
          {canManage && feed.status === 'choose' && (
            <SelectField
              label={
                feed.kind === 'instagram'
                  ? t('Welches Instagram-Konto?')
                  : t('Welche Facebook-Seite?')
              }
              value=""
              onChange={(e) =>
                e.target.value &&
                void run(() => socialApi.choosePage(org.id, feed.id, e.target.value))
              }
            >
              <option value="">
                {feed.kind === 'instagram' ? t('Konto') : t('Seite')} {t('wählen …')}
              </option>
              {feed.pages.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </SelectField>
          )}
          {canManage && !connected && feed.status !== 'choose' && (
            <>
              <div className="grid-2">
                <Field
                  label={t('App-ID')}
                  inputMode="numeric"
                  value={appId}
                  onChange={(e) => setAppId(e.target.value.trim())}
                  hint={t('Aus eurer Meta-App (siehe Anleitung unten).')}
                />
                <Field
                  label={t('App-Geheimnis')}
                  type="password"
                  autoComplete="off"
                  value={secret}
                  placeholder={feed.has_secret ? 'gespeichert' : ''}
                  onChange={(e) => setSecret(e.target.value.trim())}
                  hint={t('Wird verschlüsselt gespeichert und nie wieder angezeigt.')}
                />
                {(feed.kind === 'facebook' || viaFacebook) && (
                  <Field
                    label={t('Konfigurations-ID')}
                    inputMode="numeric"
                    value={configId}
                    onChange={(e) => setConfigId(e.target.value.trim())}
                    hint={
                      feed.kind === 'instagram'
                        ? t(
                            'Aus „Facebook Login for Business“ › Konfigurationen. Leer: über die mit Instagram verknüpfte Facebook-Seite.',
                          )
                        : t('Nur nötig, wenn eure App mit „Facebook Login for Business“ arbeitet.')
                    }
                  />
                )}
                {feed.kind === 'instagram' && (
                  <Checkbox
                    label={t('Alter Weg „Instagram-Login“')}
                    checked={!viaFacebook}
                    onChange={(v) => setViaFacebook(!v)}
                    hint={t(
                      'Nur für ältere Meta-Apps, die „API-Einrichtung mit Instagram-Login“ noch anbieten.',
                    )}
                  />
                )}
              </div>
              <p className="muted small">
                {t('Weiterleitungsadresse für die Meta-App:')} <code>{redirectUri}</code>
              </p>
              <div className="button-row">
                <button
                  type="button"
                  className="button"
                  disabled={busy || !appId || (!secret && !feed.has_secret)}
                  onClick={() => void connect()}
                >
                  {t('Mit')} {feed.kind === 'instagram' ? t('Instagram') : t('Facebook')} verbinden
                </button>
              </div>
            </>
          )}
          {canManage && (
            <div className="grid-2">
              <SelectField
                label={t('Künftig abgerufene Beiträge')}
                value={feed.mode}
                onChange={(e) =>
                  void run(() =>
                    socialApi.save(org.id, feed.id, { mode: e.target.value as SocialFeed['mode'] }),
                  )
                }
                hint={t(
                  'Gilt nur für neue Beiträge; wartende bleiben wartend. „Erst nach Freigabe“, wenn Fotos von Dritten dabei sein können.',
                )}
              >
                <option value="auto">{t('automatisch zeigen')}</option>
                <option value="approval">{t('erst nach Freigabe')}</option>
              </SelectField>
              <Field
                label={t('Beiträge halten')}
                type="number"
                min={1}
                max={50}
                defaultValue={feed.max_posts}
                onBlur={(e) =>
                  Number(e.target.value) !== feed.max_posts &&
                  void run(() =>
                    socialApi.save(org.id, feed.id, { max_posts: Number(e.target.value) }),
                  )
                }
                hint={t('Die neuesten; ältere fallen weg.')}
              />
              <Checkbox
                label={t('Link zum Beitrag zeigen')}
                checked={feed.show_link}
                onChange={(v) => void run(() => socialApi.save(org.id, feed.id, { show_link: v }))}
                hint={t('schlichter Textlink, kein Meta-Element')}
              />
              <Checkbox
                label={t('Hashtags am Ende weglassen')}
                checked={feed.strip_hashtags}
                onChange={(v) =>
                  void run(() => socialApi.save(org.id, feed.id, { strip_hashtags: v }))
                }
              />
            </div>
          )}
          <div className="button-row">
            {feed.post_count > 0 && (
              <button
                type="button"
                className="button button-ghost"
                aria-expanded={showPosts}
                onClick={() => setShowPosts(!showPosts)}
              >
                {showPosts ? t('Beiträge zuklappen') : t('Beiträge ansehen')}
              </button>
            )}
            {canManage && feed.pending_count > 0 && (
              <button
                type="button"
                className="button button-ghost"
                disabled={busy}
                onClick={async () => {
                  const n = feed.pending_count
                  const text =
                    n === 1 ? t('den wartenden Beitrag') : t('alle {n} wartenden Beiträge', { n })
                  if (
                    await confirmDialog(
                      t(
                        '{x}{x2} auf der Webseite zeigen? Prüfe vorher, ob alle Fotos gezeigt werden dürfen.',
                        { x: text[0].toUpperCase(), x2: text.slice(1) },
                      ),
                    )
                  )
                    void run(async () => {
                      const r = await socialApi.publishPending(org.id, feed.id)
                      setInfo(
                        r.published === 1
                          ? t('1 Beitrag freigegeben.')
                          : t('{published} Beiträge freigegeben.', { published: r.published }),
                      )
                    })
                }}
              >
                {feed.pending_count === 1
                  ? t('1 wartenden Beitrag veröffentlichen')
                  : t('{pending_count} wartende Beiträge veröffentlichen', {
                      pending_count: feed.pending_count,
                    })}
              </button>
            )}
            {canManage && connected && (
              <>
                <button
                  type="button"
                  className="button button-ghost"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      const r = await socialApi.sync(org.id, feed.id)
                      setInfo(
                        r.created
                          ? t('{created} neue Beiträge abgerufen.', { created: r.created })
                          : t('Nichts Neues.'),
                      )
                    })
                  }
                >
                  {t('Jetzt abrufen')}
                </button>
                <button
                  type="button"
                  className="button button-ghost"
                  disabled={busy}
                  onClick={() => void connect()}
                >
                  {t('Neu verbinden')}
                </button>
                <button
                  type="button"
                  className="button button-ghost"
                  disabled={busy}
                  onClick={async () => {
                    if (
                      await confirmDialog(
                        t(
                          'Verbindung trennen? Der Zugang und alle abgerufenen Beiträge mit Bildern werden gelöscht.',
                        ),
                      )
                    )
                      void run(() => socialApi.disconnect(org.id, feed.id), t('Getrennt.'))
                  }}
                >
                  {t('Trennen')}
                </button>
              </>
            )}
            {canManage && (
              <button
                type="button"
                className="button button-ghost"
                disabled={busy}
                onClick={async () => {
                  if (await confirmDialog(t('{title} mit allen Beiträgen löschen?', { title })))
                    void run(() => socialApi.remove(org.id, feed.id))
                }}
              >
                {t('Kanal löschen')}
              </button>
            )}
          </div>
          {info && <Alert kind="success">{info}</Alert>}
          {error && <Alert kind="error">{error}</Alert>}
          {showPosts && <PostList feed={feed.id} onChanged={onChanged} />}
        </>
      )}
    </section>
  )
}

function PostList({ feed, onChanged }: { feed: number; onChanged: () => void }) {
  const org = useActiveOrg()
  const { data, error, reload } = useLoad(() => socialApi.posts(org.id, feed), [org.id, feed])
  const [saveError, setSaveError] = useState<string | null>(null)
  if (error) return <LoadError message={error} onRetry={() => void reload()} />
  if (!data) return <p className="muted">{t('Lädt …')}</p>
  async function setState(post: SocialPost, state: SocialPost['state']) {
    setSaveError(null)
    try {
      await socialApi.setPost(org.id, post.id, { state })
      void reload()
      onChanged()
    } catch (err) {
      setSaveError(errorMessage(err))
    }
  }
  return (
    <>
      {saveError && <Alert kind="error">{saveError}</Alert>}
      <ul className="plain-list social-posts">
        {data.map((p) => (
          <li key={p.id} className={p.state === 'hidden' ? 'muted' : undefined}>
            <PostImages post={p} onSaved={() => void reload()} />
            <div>
              <p className="small">
                {formatDateTime(p.published_at)} · {p.state_label}
                {p.media_type === 'video' && t(' · Video (nur Vorschaubild)')}
              </p>
              <p className="pre-line">{p.text || <em>{t('ohne Text')}</em>}</p>
              <div className="button-row">
                {p.state !== 'visible' && (
                  <button
                    type="button"
                    className="button"
                    onClick={() => void setState(p, 'visible')}
                  >
                    {p.state === 'pending' ? t('Freigeben') : t('Wieder zeigen')}
                  </button>
                )}
                {p.state !== 'hidden' && (
                  <button
                    type="button"
                    className="button button-ghost"
                    onClick={() => void setState(p, 'hidden')}
                  >
                    {t('Ausblenden')}
                  </button>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </>
  )
}

/**
 * Alle Bilder eines Beitrags mit Anzahl, Vergrößerung und Alternativtext (UX-Audit 31.10. N08):
 * vor der Freigabe muss jedes Foto prüfbar sein, nicht nur die ersten vier.
 */
function PostImages({ post, onSaved }: { post: SocialPost; onSaved: () => void }) {
  const org = useActiveOrg()
  const [large, setLarge] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  if (post.images.length === 0) return <div className="social-post-images" />
  const shown = post.images.find((i) => i.id === large)
  async function saveAlt(id: number, text: string) {
    setError(null)
    setSaved(false)
    try {
      await socialApi.setPost(org.id, post.id, { alt_texts: { [String(id)]: text } })
      setSaved(true)
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    }
  }
  return (
    <div className="social-post-images">
      <p className="small">
        {post.images.length === 1 ? t('1 Bild') : t('{n} Bilder', { n: post.images.length })}
        {post.images.some((i) => i.is_video) && ' (Video: nur Vorschaubild)'}
      </p>
      <div className="social-post-thumbs">
        {post.images.map((i, n) => (
          <button
            key={i.id}
            type="button"
            className="link-button"
            aria-pressed={large === i.id}
            aria-label={
              large === i.id
                ? t('Bild {x} von {n} verkleinern', { x: n + 1, n: post.images.length })
                : t('Bild {x} von {n} vergrößern', { x: n + 1, n: post.images.length })
            }
            onClick={() => setLarge(large === i.id ? null : i.id)}
          >
            <img src={i.small_url} alt={i.alt_text} width={80} height={60} />
          </button>
        ))}
      </div>
      {shown && (
        <figure className="social-post-large">
          <img src={shown.url} alt={shown.alt_text} />
          <figcaption>
            <Field
              key={shown.id}
              label={t('Alternativtext Bild {x}', { x: post.images.indexOf(shown) + 1 })}
              defaultValue={shown.alt_text}
              maxLength={300}
              hint={t(
                'Kurz beschreiben, was zu sehen ist; wird beim Verlassen des Felds gespeichert.',
              )}
              onBlur={(e) =>
                e.target.value !== shown.alt_text && void saveAlt(shown.id, e.target.value)
              }
            />
            {saved && (
              <p className="small" role="status">
                {t('Gespeichert.')}
              </p>
            )}
            {error && <Alert kind="error">{error}</Alert>}
          </figcaption>
        </figure>
      )}
    </div>
  )
}

function SetupGuide({ redirectUri }: { redirectUri: string }) {
  return (
    <details className="card card-wide">
      <summary>
        <strong>{t('Anleitung: eigene Meta-App anlegen (einmalig, etwa 20 Minuten)')}</strong>
      </summary>
      <p className="muted small">
        {t(
          'Meta gibt Beiträge nur an eine registrierte „App“ heraus. Das ist keine Handy-App, sondern ein Eintrag bei Meta, der erlaubt, die Beiträge eurer eigenen Kanäle zu lesen. Weil ihr die App selbst anlegt, bleiben Zugang und Daten bei euch, und Meta muss nichts prüfen.',
        )}
      </p>
      <ol>
        <li>
          {t('Instagram: Konto auf')} <strong>{t('Profikonto')}</strong>{' '}
          {t(
            'umstellen (in der Instagram-App unter Einstellungen › Kontoart, „Business“ oder „Creator“). Private Konten gehen nicht. Facebook: Es geht nur eine',
          )}{' '}
          <strong>{t('Seite')}</strong>
          {t(', kein privates Profil.')}
        </li>
        <li>
          {t('Auf')} <strong>developers.facebook.com</strong>{' '}
          {t(
            'mit einem Facebook-Konto des Vorstands anmelden und ein Entwicklerkonto anlegen. Am besten die App im Business-Portfolio des Vereins anlegen und zwei Personen als Admins eintragen, damit sie bei einem Vorstandswechsel nicht verloren geht.',
          )}
        </li>
        <li>
          {t('„App erstellen“, Anwendungsfall')} <strong>{t('„Instagram API“')}</strong>{' '}
          {t('(Instagram) bzw.')} <strong>{t('„Alles auf deiner Seite verwalten“')}</strong>{' '}
          {t(
            '(Facebook). Die App bleibt im Entwicklungsmodus; Veröffentlichung, App-Prüfung und Unternehmensverifizierung sind nicht nötig.',
          )}
        </li>
        <li>
          {t('Instagram: Unter „API-Einrichtung mit Facebook-Login“ bzw. „Unified Login“ eine')}{' '}
          <strong>{t('Konfiguration')}</strong> {t('anlegen: Zugriffstoken')}{' '}
          <strong>„Nutzerzugriffstoken“</strong>
          {t(
            '(Ablauf „läuft nie ab“, falls angeboten; „Systemnutzer“ funktioniert im Entwicklungsmodus nicht), Assets nur',
          )}{' '}
          <strong>{t('Instagram-Konten')}</strong>{' '}
          {t('(keine Werbekonten), Berechtigungen nur die Pflicht-Berechtigungen (')}
          <code>instagram_basic</code> {t('und die nicht abwählbaren). Die angezeigte')}{' '}
          <strong>{t('Konfigurations-ID')}</strong>{' '}
          {t(
            'oben eintragen. Wer sich anmeldet, muss Admin der App sein und das Instagram-Konto im Business-Portfolio verwalten. Alternativ ohne Konfiguration: Konfigurations-ID leer lassen, Anwendungsfall „Alles auf deiner Seite verwalten“ hinzufügen; HUBIplan findet das Instagram-Konto dann über die damit verknüpfte Facebook-Seite.',
          )}
        </li>
        <li>{t('Facebook: Wer die Seite verwaltet, muss Admin der App sein.')}</li>
        <li>
          {t('Als')} <strong>{t('Weiterleitungs-URI')}</strong> {t('(OAuth) eintragen:')}{' '}
          <code>{redirectUri}</code>
        </li>
        <li>{t('Als Datenschutz-URL die Datenschutzhinweise eurer Webseite eintragen.')}</li>
        <li>
          <strong>{t('App-ID')}</strong> und <strong>{t('App-Geheimcode')}</strong>{' '}
          {t(
            'aus App-Einstellungen › Allgemein oben eintragen und auf „verbinden“ klicken. Nur beim alten Weg „Instagram-Login“ gelten stattdessen „Instagram-App-ID“ und „Instagram-App-Geheimcode“.',
          )}
        </li>
      </ol>
      <p className="muted small">
        {t(
          'Rechte: Zeigt nur Fotos, die ihr auch auf der Webseite zeigen dürft. Hat ein Fotograf ein Bild nur für Instagram freigegeben oder sind Personen zu sehen, die nur „Social Media“ zugestimmt haben, wählt „erst nach Freigabe“ oder blendet den Beitrag aus. Videos zeigt die Webseite nur als Vorschaubild mit Link, weil Musik aus Instagram nur dort lizenziert ist. HUBIplan speichert Texte und Bilder der Beiträge und zeigt sie auf eurer Webseite; die Bilder werden dabei neu gespeichert, eingebettete Angaben wie der Name des Fotografen gehen verloren. Muss ein Fotograf genannt werden, gehört sein Name in den Beitragstext. Die Verbindung zu Instagram oder Facebook gibt euch keine Rechte an fremden Bildern.',
        )}
      </p>
    </details>
  )
}
