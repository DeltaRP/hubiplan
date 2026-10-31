import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { CircularsArea } from '../components/circulars/CircularsArea.tsx'
import { renderMarkup } from '../components/circulars/markup.tsx'
import { fakeApi } from './fakeApi.ts'

const base = '/api/orgs/7/circulars/'

const draft = {
  id: 3,
  subject: 'Einladung',
  kind: 'info',
  kind_label: 'Information',
  audience: 'members',
  status: 'draft',
  status_label: 'Entwurf',
  department: null,
  created_by: 'Karla',
  created_at: '2026-10-25T10:00:00Z',
  updated_at: '2026-10-25T10:00:00Z',
  sent_at: null,
  sent_by: '',
  body: 'Hallo {Vorname},\n\n**Bitte** kommen.',
  reply_to: '',
  filters: {},
  can_edit: true,
  attachments: [],
  counts: null,
}

const options = {
  org_type: 'club',
  department: null,
  kinds: [
    { value: 'info', label: 'Information' },
    { value: 'notice', label: 'Vereinsmitteilung' },
  ],
  placeholders: [{ name: 'Vorname', label: 'Vorname des Empfängers' }],
  reply_to: 'kassenwart@example.org',
  max_attachments: 5,
  max_attachment_mb: 10,
  member_types: [{ id: 1, name: 'aktiv' }],
  departments: [{ id: 5, name: 'Jägerzug' }],
  roles: [],
}

const recipients = {
  counts: { total: 2, mail: 1, letter: 1, opted_out: 0, excluded: 0 },
  items: [
    {
      key: 'm1',
      first_name: 'Anna',
      last_name: 'Adler',
      club: 'TV',
      email: 'a@x.de',
      channel: 'mail',
    },
    { key: 'm2', first_name: 'Bernd', last_name: 'Berg', club: 'TV', email: '', channel: 'letter' },
  ],
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <CircularsArea base={{ org: 7 }} root="/r" />
    </MemoryRouter>,
  )
}

describe('Rundschreiben', () => {
  it('Auszeichnung wird ohne HTML dargestellt', () => {
    render(<div>{renderMarkup('**fett** <b>x</b>\n- eins')}</div>)
    expect(screen.getByText('fett').tagName).toBe('STRONG')
    expect(screen.getByText(/<b>x<\/b>/)).toBeInTheDocument()
    expect(screen.getByText('eins').tagName).toBe('LI')
  })

  it('zeigt Empfänger und versendet nach Rückfrage', async () => {
    const calls = fakeApi({
      [`GET ${base}3/`]: () => ({ status: 200, body: draft }),
      [`GET ${base}options/`]: () => ({ status: 200, body: options }),
      [`GET ${base}3/recipients/`]: () => ({ status: 200, body: recipients }),
      [`POST ${base}3/send/`]: () => ({
        status: 200,
        body: { ...draft, status: 'sent', can_edit: false, sent: { mail: 1, letter: 1 } },
      }),
    })
    renderAt('/3')
    expect(await screen.findByText('1 per E-Mail · 1 per Brief')).toBeInTheDocument()
    expect(screen.getByText('Brief')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Versenden …' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(within(dialog).getByText(/1 E-Mail und 1 Brief zum Drucken/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Jetzt versenden' }))
    await screen.findByText('Wird geladen …').catch(() => null)
    expect(calls.some((c) => c.key === `POST ${base}3/send/`)).toBe(true)
  })

  it('Filter ändern speichert automatisch', async () => {
    const calls = fakeApi({
      [`GET ${base}3/`]: () => ({ status: 200, body: draft }),
      [`GET ${base}options/`]: () => ({ status: 200, body: options }),
      [`GET ${base}3/recipients/`]: () => ({ status: 200, body: recipients }),
      [`PATCH ${base}3/`]: () => ({
        status: 200,
        body: { ...draft, filters: { departments: [5] } },
      }),
    })
    renderAt('/3')
    await screen.findByText('1 per E-Mail · 1 per Brief')
    const user = userEvent.setup()
    // Ohne Auswahl gilt ausdrücklich „alle“; einzelne erst nach „nur ausgewählte“
    expect(screen.queryByLabelText('Jägerzug')).not.toBeInTheDocument()
    for (const radio of screen.getAllByRole('radio', { name: 'nur ausgewählte' })) {
      await user.click(radio)
    }
    await user.click(screen.getByLabelText('Jägerzug'))
    await screen.findByText('✓ Gespeichert', {}, { timeout: 3000 })
    const patch = calls.find((c) => c.key === `PATCH ${base}3/`)
    const sent = JSON.parse(String(patch?.init?.body))
    expect(sent.filters.departments).toEqual([5])
    expect(sent.filters.selected).toContain('departments')
    // Letztes Häkchen weg: „nur ausgewählte“ bleibt und heißt niemand (UI-Audit NMF-06)
    await user.click(screen.getByLabelText('Jägerzug'))
    const box = screen.getByLabelText('Jägerzug').closest('fieldset') as HTMLElement
    expect(await within(box).findByText(/So geht die Nachricht an niemanden/)).toBeVisible()
  })
  it('Fehler beim Probemail nennt das Problem und markiert das Feld', async () => {
    fakeApi({
      [`GET ${base}3/`]: () => ({ status: 200, body: { ...draft, subject: '' } }),
      [`GET ${base}options/`]: () => ({ status: 200, body: options }),
      [`GET ${base}3/recipients/`]: () => ({ status: 200, body: recipients }),
      [`POST ${base}3/test/`]: () => ({
        status: 400,
        body: { subject: ['Bitte einen Betreff eingeben.'] },
      }),
    })
    renderAt('/3')
    await screen.findByText('1 per E-Mail · 1 per Brief')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Probemail an mich' }))
    const messages = await screen.findAllByText('Bitte einen Betreff eingeben.')
    expect(messages.length).toBe(2)
    expect(screen.queryByText(/markierten Felder/)).not.toBeInTheDocument()
  })
})
