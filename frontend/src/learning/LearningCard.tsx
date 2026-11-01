// Mein Konto: Lernhilfen ein- und ausschalten, ausgeblendete Erklärungen zurückholen.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Checkbox } from '../components/ui.tsx'
import { errorMessage } from '../components/forms.ts'
import { useLearning } from './LearningContext.tsx'
import { t } from '../i18n/index.ts'

export function LearningCard() {
  const learning = useLearning()
  const [error, setError] = useState<string | null>(null)
  if (!learning || !learning.ready) return null
  const hiddenCount = learning.hidden.size

  async function run(action: () => Promise<void>) {
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="card card-wide">
      <h2>{t('Lernhilfen')}</h2>
      {learning.loadFailed && (
        <Alert kind="error">
          {t('Die Einstellung konnte nicht geladen werden.')}{' '}
          <button type="button" className="link-button" onClick={learning.reload}>
            {t('Erneut laden')}
          </button>
        </Alert>
      )}
      <Checkbox
        label={t('Lernhilfen zeigen')}
        checked={learning.enabled}
        onChange={(v) => void run(() => learning.setEnabled(v))}
      />
      <p className="muted small">
        {t(
          'Zeigt ein „?“ an Fachbegriffen und Grundlagen-Erklärungen „Warum?“ an Entscheidungen. Abwägungen bei echten Wahlmöglichkeiten erscheinen immer. Alle Begriffe stehen im',
        )}{' '}
        <Link to="/glossar">{t('Glossar')}</Link>.
      </p>
      {hiddenCount > 0 && (
        <div className="learning-hidden">
          <p className="small">
            {hiddenCount === 1
              ? t('1 Erklärung „Warum?“ ausgeblendet.')
              : t('{hiddenCount} Erklärungen „Warum?“ ausgeblendet.', { hiddenCount })}
          </p>
          <button
            type="button"
            className="button button-ghost"
            onClick={() => void run(() => learning.resetHidden())}
          >
            {t('Ausgeblendete Erklärungen wieder zeigen')}
          </button>
        </div>
      )}
      {error && <Alert kind="error">{error}</Alert>}
    </div>
  )
}
