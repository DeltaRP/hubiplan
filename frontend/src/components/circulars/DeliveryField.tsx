import { SelectField } from '../ui.tsx'
import { t } from '../../i18n/index.ts'

// Zustellweg eines Rundschreibens: nur Mail, App statt Mail oder App und Mail
type Delivery = 'mail' | 'app' | 'both'

const HINTS: Record<Delivery, string> = {
  mail: t('Alle bekommen es per E-Mail, auch Mitglieder mit der HUBIplan-App.'),
  app: t(
    'Mitglieder mit der HUBIplan-App bekommen es nur als Mitteilung aufs Telefon, alle anderen per E-Mail.',
  ),
  both: t(
    'Mitglieder mit der HUBIplan-App bekommen es aufs Telefon und zusätzlich per E-Mail, alle anderen per E-Mail.',
  ),
}

export function DeliveryField({
  viaApp,
  alsoMail,
  onChange,
}: {
  viaApp: boolean
  alsoMail: boolean
  onChange: (change: { via_app: boolean; also_mail: boolean }) => void
}) {
  const value: Delivery = !viaApp ? 'mail' : alsoMail ? 'both' : 'app'
  return (
    <SelectField
      label={t('Zustellung')}
      value={value}
      hint={HINTS[value]}
      onChange={(e) => {
        const next = e.target.value as Delivery
        onChange({ via_app: next !== 'mail', also_mail: next === 'both' })
      }}
    >
      <option value="app">{t('per App, sonst E-Mail')}</option>
      <option value="both">{t('per App und zusätzlich E-Mail')}</option>
      <option value="mail">{t('nur per E-Mail')}</option>
    </SelectField>
  )
}
