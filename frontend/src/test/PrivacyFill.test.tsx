import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { PrivacyPublish } from '../components/PrivacyPublish.tsx'

function Harness({ initial }: { initial: string }) {
  const [draft, setDraft] = useState(initial)
  return (
    <>
      <PrivacyPublish
        draft={draft}
        publishedText=""
        publishedAt={null}
        onPublish={async () => {}}
        onFill={setDraft}
      />
      <pre data-testid="entwurf">{draft}</pre>
    </>
  )
}

describe('Offene Angaben der Datenschutzhinweise', () => {
  it('lassen sich direkt ausfüllen und werden überall ersetzt (Ralf 2026-10-30)', async () => {
    const user = userEvent.setup()
    render(
      <Harness initial="Server bei [Hosting-Anbieter]. Logs nach [Anzahl] Tagen. Noch einmal [Anzahl]." />,
    )
    await user.type(screen.getByLabelText('Anzahl'), '14')
    await user.click(screen.getByRole('button', { name: 'Anzahl einsetzen' }))
    expect(screen.getByTestId('entwurf')).toHaveTextContent(
      'Server bei [Hosting-Anbieter]. Logs nach 14 Tagen. Noch einmal 14.',
    )
    expect(screen.queryByLabelText('Anzahl')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Hosting-Anbieter'), 'Beispiel GmbH{Enter}')
    expect(screen.getByTestId('entwurf')).toHaveTextContent('Server bei Beispiel GmbH.')
    expect(screen.queryByText(/noch offen/)).not.toBeInTheDocument()
  })
})
