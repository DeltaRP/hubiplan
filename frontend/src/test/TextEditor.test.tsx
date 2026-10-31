// Editor für die Texte der Webseite (WYSIWYG, gespeichert als Markdown). Erfundene Daten.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import axe from 'axe-core'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { LinkTarget, WebsiteImage } from '../api/website.ts'
import { TextEditor } from '../components/texteditor/TextEditor.tsx'

const image = (id: number, key: string, alt: string): WebsiteImage => ({
  id,
  key,
  caption: '',
  alt_text: alt,
  width: 800,
  height: 600,
  url: `/api/x/${id}/`,
  small_url: `/api/x/${id}/?size=small`,
  markdown: `![${alt}](bild:${key})`,
  uploaded_at: '2026-10-30T10:00:00Z',
})

const targets: LinkTarget[] = [
  { href: 'seite:start', label: 'Startseite' },
  { href: 'seite:termine', label: 'Termine' },
]

function Harness({
  initial,
  onChange,
  images,
}: {
  initial: string
  onChange?: (text: string) => void
  images?: WebsiteImage[]
}) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <TextEditor
        label="Text"
        value={value}
        images={images}
        linkTargets={targets}
        onChange={(text) => {
          setValue(text)
          onChange?.(text)
        }}
      />
      <button type="button" onClick={() => setValue('## Von außen')}>
        Fassung holen
      </button>
    </>
  )
}

const editor = () => screen.getByRole('textbox', { name: 'Text' })

describe('Editor für Webseitentexte', () => {
  it('zeigt den Text formatiert statt mit Auszeichnung', () => {
    render(<Harness initial={'## Geschichte\n\nGegründet **1920**.'} />)
    expect(within(editor()).getByRole('heading', { level: 2, name: 'Geschichte' })).toBeVisible()
    expect(within(editor()).getByText('1920').tagName).toBe('STRONG')
    expect(editor()).not.toHaveTextContent('**')
  })

  it('macht per Knopf eine Überschrift und eine Liste daraus', async () => {
    const onChange = vi.fn()
    render(<Harness initial="Festfolge" onChange={onChange} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Überschrift' }))
    expect(onChange).toHaveBeenLastCalledWith('## Festfolge')
    expect(screen.getByRole('button', { name: 'Überschrift' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await user.click(screen.getByRole('button', { name: 'Überschrift' }))
    expect(onChange).toHaveBeenLastCalledWith('Festfolge')
    await user.click(screen.getByRole('button', { name: 'Aufzählung' }))
    expect(onChange).toHaveBeenLastCalledWith('- Festfolge')
    await user.click(screen.getByRole('button', { name: 'Nummerierte Liste' }))
    expect(onChange).toHaveBeenLastCalledWith('1. Festfolge')
    // Rückgängig nimmt schnell aufeinanderfolgende Schritte zusammen zurück
    await user.click(screen.getByRole('button', { name: 'Rückgängig (Strg+Z)' }))
    expect(onChange).not.toHaveBeenLastCalledWith('1. Festfolge')
    expect(within(editor()).queryByRole('list')).toBeNull()
  })

  it('verlinkt eine Seite der eigenen Webseite aus der Liste', async () => {
    const onChange = vi.fn()
    render(<Harness initial="Alle Feste." onChange={onChange} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Link (Strg+K)' }))
    const dialog = await screen.findByRole('dialog', { name: 'Link einfügen' })
    expect(within(dialog).getByRole('radio', { name: 'Seite unserer Webseite' })).toBeChecked()
    await user.selectOptions(within(dialog).getByLabelText('Seite'), 'seite:termine')
    await user.click(within(dialog).getByRole('button', { name: 'Einfügen' }))
    expect(onChange).toHaveBeenLastCalledWith('[Termine](seite:termine)Alle Feste.')
    expect(within(editor()).getByRole('link', { name: 'Termine' })).toBeVisible()
  })

  it('nimmt beim Link nur sichere Adressen', async () => {
    const onChange = vi.fn()
    render(<Harness initial="Text" onChange={onChange} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Link (Strg+K)' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('radio', { name: /andere Adresse/ }))
    await user.type(
      within(dialog).getByLabelText('Adresse (https://… oder E-Mail)'),
      'javascript:alert(1)',
    )
    await user.click(within(dialog).getByRole('button', { name: 'Einfügen' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent(/Bitte eine Adresse/)
    await user.clear(within(dialog).getByLabelText('Adresse (https://… oder E-Mail)'))
    await user.type(
      within(dialog).getByLabelText('Adresse (https://… oder E-Mail)'),
      'www.beispiel-schuetzen.de',
    )
    await user.click(within(dialog).getByRole('button', { name: 'Einfügen' }))
    // Link mit der Adresse als Text: kurze Markdown-Form
    expect(onChange).toHaveBeenLastCalledWith('<https://www.beispiel-schuetzen.de>Text')
  })

  it('fügt ein Bild aus der Bilderliste ein und zeigt es', async () => {
    const onChange = vi.fn()
    render(
      <Harness initial="Text" onChange={onChange} images={[image(1, 'fahne123', 'Die Fahne')]} />,
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Bild einfügen' }))
    const dialog = await screen.findByRole('dialog', { name: 'Bild einfügen' })
    await user.click(within(dialog).getByRole('button', { name: /Die Fahne/ }))
    expect(onChange).toHaveBeenLastCalledWith('![Die Fahne](bild:fahne123)Text')
    expect(within(editor()).getByRole('img', { name: 'Die Fahne' })).toHaveAttribute(
      'src',
      '/api/x/1/?size=small',
    )
  })

  it('schaltet auf Markdown um und zurück', async () => {
    const onChange = vi.fn()
    render(<Harness initial="**fett**" onChange={onChange} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Markdown anzeigen' }))
    const source = screen.getByRole('textbox', { name: 'Text' })
    expect(source).toHaveValue('**fett**')
    await user.type(source, ' und *kursiv*')
    expect(onChange).toHaveBeenLastCalledWith('**fett** und *kursiv*')
    await user.click(screen.getByRole('button', { name: 'Markdown anzeigen' }))
    expect(within(editor()).getByText('kursiv').tagName).toBe('EM')
  })

  it('bearbeitet Texte mit Tabellen als Markdown, ohne etwas zu verlieren', () => {
    const table = '| Jahr | König |\n| --- | --- |\n| 2026 | Erfunden |'
    render(<Harness initial={table} />)
    expect(screen.getByRole('status')).toHaveTextContent(/nicht anzeigen kann/)
    expect(screen.getByRole('textbox', { name: 'Text' })).toHaveValue(table)
    expect(screen.queryByRole('button', { name: 'Fett (Strg+B)' })).toBeNull()
  })

  it('übernimmt einen von außen geänderten Text', async () => {
    render(<Harness initial="Alt" />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Fassung holen' }))
    await waitFor(() =>
      expect(within(editor()).getByRole('heading', { name: 'Von außen' })).toBeVisible(),
    )
  })

  it('Werkzeugleiste: ein Tab-Stopp, Pfeiltasten wandern', async () => {
    render(<Harness initial="Text" />)
    const toolbar = screen.getByRole('toolbar', { name: 'Formatierung: Text' })
    const tabbable = within(toolbar)
      .getAllByRole('button')
      .filter((b) => b.tabIndex === 0)
    expect(tabbable).toHaveLength(1)
    const user = userEvent.setup()
    tabbable[0].focus()
    await user.keyboard('{ArrowRight}')
    expect(document.activeElement).toHaveAccessibleName('Kursiv (Strg+I)')
    await user.keyboard('{End}')
    expect(document.activeElement).toHaveAccessibleName('Markdown anzeigen')
  })

  it('hat laut axe keine Verstöße', async () => {
    render(<Harness initial={'## Titel\n\nText mit [Link](seite:termine).'} />)
    const result = await axe.run(document.body, {
      // Kontrast misst jsdom nicht; Landmarken liefert die App, nicht der Baustein
      rules: { 'color-contrast': { enabled: false }, region: { enabled: false } },
    })
    expect(result.violations.map((v) => v.id)).toEqual([])
  })
})
