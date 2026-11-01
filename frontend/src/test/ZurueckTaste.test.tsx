// Gesamtaudit 01.11., GA-F02: Browser-Zurück verwirft ungespeicherte Eingaben nicht still.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { LeaveGuard, useChangesGuard } from '../components/leaveGuard.ts'

function Formular() {
  const [name, setName] = useState('')
  useChangesGuard({ name })
  return <input aria-label="Name" value={name} onChange={(e) => setName(e.target.value)} />
}

function App() {
  return (
    <BrowserRouter>
      <LeaveGuard />
      <Routes>
        <Route path="/" element={<Link to="/neu">Neuaufnahme</Link>} />
        <Route path="/neu" element={<Formular />} />
      </Routes>
    </BrowserRouter>
  )
}

describe('Browser-Zurück mit ungespeicherten Eingaben', () => {
  it('fragt nach und bleibt bei „Weiter bearbeiten“', async () => {
    window.history.replaceState(null, '', '/')
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByText('Neuaufnahme'))
    await user.type(screen.getByLabelText('Name'), 'Erika')
    window.history.back()
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Weiter bearbeiten' }))
    expect(screen.getByLabelText('Name')).toHaveValue('Erika')
    await waitFor(() => expect(window.location.pathname).toBe('/neu'))

    window.history.back()
    const again = await screen.findByRole('alertdialog')
    await user.click(within(again).getByRole('button', { name: 'Verwerfen' }))
    await waitFor(() => expect(screen.getByText('Neuaufnahme')).toBeInTheDocument())
    expect(window.location.pathname).toBe('/')
  })
})
