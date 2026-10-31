// Zusatzfeld-Typ „Startjahr/Endjahr“: zwei Jahresfelder, gespeichert als „JJJJ/JJJJ“.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FieldsTab } from '../pages/members/FieldsTab.tsx'

const definition = {
  id: 6,
  label: 'Königsjahr',
  key: 'koenigsjahr',
  field_type: 'yearrange',
  choices: [],
  repeatable: false,
  subfields: [],
  federation_wide: false,
  help_text: '',
  sort_order: 0,
  is_archived: false,
  inherited: false,
  owner_name: 'Verein',
  in_use: true,
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Zusatzfeld Startjahr/Endjahr', () => {
  it('zeigt Start- und Endjahr und speichert beide zusammen', async () => {
    document.cookie = 'csrftoken=test-token'
    const puts: unknown[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body))
        puts.push(body)
        return new Response(JSON.stringify([{ definition, value: body.values['6'] }]), {
          status: 200,
        })
      }
      return new Response(JSON.stringify([{ definition, value: '2024' }]), { status: 200 })
    })
    render(<FieldsTab orgId={7} memberId={1} canEdit />)
    const start = await screen.findByLabelText('Königsjahr: Startjahr')
    const end = screen.getByLabelText('Königsjahr: Endjahr')
    expect(start).toHaveValue('2024')
    expect(end).toHaveValue('')
    fireEvent.change(end, { target: { value: '2025' } })
    await waitFor(() => expect(puts).toEqual([{ values: { '6': '2024/2025' } }]), {
      timeout: 3000,
    })
  })
})
