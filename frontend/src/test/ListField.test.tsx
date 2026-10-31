import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { ListInput } from '../components/ListField.tsx'
import { parseNumberList, parseTextList } from '../components/lists.ts'

function Harness({ initial, onValue }: { initial: number[]; onValue: (v: number[]) => void }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <ListInput
        label="Jubiläumsstufen"
        value={value}
        parse={parseNumberList}
        onChange={(v) => {
          setValue(v)
          onValue(v)
        }}
      />
      <button type="button" onClick={() => setValue([10])}>
        zurücksetzen
      </button>
    </>
  )
}

describe('Listenfelder', () => {
  it('lässt Komma und Leerzeichen tippen und meldet die Zahlen', async () => {
    const user = userEvent.setup()
    const seen: number[][] = []
    render(<Harness initial={[25, 40]} onValue={(v) => seen.push(v)} />)
    const input = screen.getByLabelText('Jubiläumsstufen')
    await user.type(input, ', 50, ')
    expect(input).toHaveValue('25, 40, 50, ')
    expect(seen.at(-1)).toEqual([25, 40, 50])
    // Ein Komma allein löst keine Änderung aus (wichtig fürs Autospeichern).
    expect(seen).toEqual([
      [25, 40, 5],
      [25, 40, 50],
    ])
    await user.tab()
    expect(input).toHaveValue('25, 40, 50')
  })

  it('übernimmt Änderungen von außen', async () => {
    const user = userEvent.setup()
    render(<Harness initial={[25]} onValue={() => {}} />)
    await user.click(screen.getByRole('button', { name: 'zurücksetzen' }))
    expect(screen.getByLabelText('Jubiläumsstufen')).toHaveValue('10')
  })

  it('zerlegt Zahlen und Texte', () => {
    expect(parseNumberList('10;25 40,, 0, x, 2.5')).toEqual([10, 25, 40])
    expect(parseTextList('Rot, Dunkel grün; ,Blau')).toEqual(['Rot', 'Dunkel grün', 'Blau'])
  })
})
