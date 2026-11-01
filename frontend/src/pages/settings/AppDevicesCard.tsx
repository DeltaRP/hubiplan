import { QRCodeSVG } from 'qrcode.react'
import { useCallback, useEffect, useState } from 'react'
import { devicesApi } from '../../api/devices.ts'
import { HowTo } from '../../learning/Aids.tsx'
import { confirmDialog } from '../../components/dialog.ts'
import type { AppDevice, PairingCode } from '../../api/devices.ts'
import { locale } from '../../i18n/index.ts'
import { t } from '../../i18n/index.ts'

function formatDate(value: string): string {
  return new Date(value).toLocaleString(locale(), { dateStyle: 'medium', timeStyle: 'short' })
}

// Mein Konto: HUBIplan-App mit dem Konto verbinden und Geräte abmelden.
export function AppDevicesCard() {
  const [visible, setVisible] = useState(false)
  const [devices, setDevices] = useState<AppDevice[]>([])
  const [pairing, setPairing] = useState<PairingCode | null>(null)
  // Nach dem Scannen: welches Gerät hat sich verbunden? (ein fremdes fällt so sofort auf)
  const [connected, setConnected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setDevices(await devicesApi.list())
  }, [])

  useEffect(() => {
    let active = true
    devicesApi
      .hasPortal()
      .then(async (has) => {
        if (!active || !has) return
        setVisible(true)
        await load()
      })
      .catch(() => {
        // Ohne Mitgliederbereich bleibt die Karte einfach weg
      })
    return () => {
      active = false
    }
  }, [load])

  useEffect(() => {
    if (!pairing) return
    let active = true
    // Höchstens ein Abruf gleichzeitig; nach Ablauf des Codes nicht weiter fragen
    // (Gesamtaudit 30.10., WEB-P02)
    let busy = false
    const expires = Date.parse(pairing.expires_at)
    const timer = window.setInterval(() => {
      if (busy) return
      if (Number.isFinite(expires) && Date.now() > expires) {
        window.clearInterval(timer)
        setPairing(null)
        setError(t('Der QR-Code ist abgelaufen. Bitte bei Bedarf einen neuen erzeugen.'))
        return
      }
      busy = true
      devicesApi
        .pairingStatus(pairing.id)
        .then(async (status) => {
          if (!active || !status.used) return
          setConnected(status.device ?? t('unbekanntes Gerät'))
          setPairing(null)
          await load()
        })
        .catch(() => {
          // Nächster Versuch beim nächsten Takt
        })
        .finally(() => {
          busy = false
        })
    }, 3000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [pairing, load])

  if (!visible) return null

  async function createCode() {
    setError(null)
    setConnected(null)
    try {
      setPairing(await devicesApi.pairingCode())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function remove(device: AppDevice) {
    if (
      !(await confirmDialog(
        t('„{name}“ abmelden? Die App dort muss neu verbunden werden.', { name: device.name }),
      ))
    )
      return
    setError(null)
    try {
      await devicesApi.remove(device.id)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function lockAdmin(device: AppDevice) {
    setError(null)
    try {
      await devicesApi.lockAdmin(device.id)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="card">
      <h2>{t('App auf dem Telefon')}</h2>
      <p className="muted small">
        {t(
          'Mit der HUBIplan-App für Android siehst du Termine im Kalender deines Telefons, sagst mit einem Fingertipp zu oder ab und bekommst Mitteilungen deines Vereins.',
        )}
      </p>
      <HowTo k="how_app_devices" />
      {error && (
        <p className="alert alert-error" role="alert">
          {error}
        </p>
      )}
      {connected && (
        <p className="alert alert-success" role="status">
          {t('Verbunden:')} <strong>{connected}</strong>. Warst du das nicht? Dann das Gerät unten
          sofort abmelden.
        </p>
      )}
      {pairing ? (
        <div className="totp-setup">
          <QRCodeSVG value={pairing.url} size={200} marginSize={2} />
          <p className="muted">
            {t(
              'In der App auf „Mit QR-Code verbinden“ tippen und diesen Code scannen. Er gilt bis  {x} Uhr und nur einmal.',
              { x: formatDate(pairing.expires_at) },
            )}
          </p>
          <button type="button" className="button button-ghost" onClick={() => setPairing(null)}>
            {t('Schließen')}
          </button>
        </div>
      ) : (
        <button type="button" className="button button-primary" onClick={() => void createCode()}>
          {t('App verbinden')}
        </button>
      )}
      <h3>{t('Angemeldete Geräte')}</h3>
      {devices.length === 0 ? (
        <p className="muted">{t('Noch kein Gerät verbunden.')}</p>
      ) : (
        <ul className="plain-list">
          {devices.map((d) => (
            <li key={d.id}>
              <strong>{d.name}</strong>{' '}
              <span className="muted small">
                {t('zuletzt aktiv')} {formatDate(d.last_seen_at)}
              </span>{' '}
              <button type="button" className="button button-ghost" onClick={() => void remove(d)}>
                {t('Abmelden')}
              </button>
              {d.admin_until && (
                <>
                  <br />
                  <span className="small">
                    {t('Verwaltung freigeschaltet bis')} {formatDate(d.admin_until)}
                  </span>{' '}
                  <button
                    type="button"
                    className="button button-ghost"
                    onClick={() => void lockAdmin(d)}
                  >
                    {t('Verwaltung sperren')}
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
