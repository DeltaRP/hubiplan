// App-eigene Rückfragen statt der Browserdialoge (window.confirm/alert/prompt).
//
//   if (!(await confirmDialog('Rolle „Kassierer“ entfernen?'))) return
//   const reason = await promptDialog({ title: 'Termin absagen', label: 'Hinweis (optional)' })
//
// Der Dialog hängt sich selbst an document.body, braucht also keinen Provider,
// übernimmt das Vereins-Theme (CSS-Variablen an <html>) und ist per Tastatur
// bedienbar: Fokus bleibt im Dialog, Esc bricht ab, danach kehrt der Fokus zurück.
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { AppDialog } from './AppDialog.tsx'
import type {
  AlertOptions,
  ChoiceOptions,
  ConfirmOptions,
  DialogSpec,
  PromptOptions,
} from './AppDialog.tsx'

export type { AlertOptions, ChoiceOptions, ConfirmOptions, PromptOptions }

function open(spec: DialogSpec): Promise<boolean | string | null> {
  return new Promise((resolve) => {
    const previous = document.activeElement as HTMLElement | null
    const host = document.createElement('div')
    host.className = 'app-dialog-host'
    // Seite dahinter für Tastatur und Screenreader sperren
    const others = Array.from(document.body.children).filter(
      (el) => el !== host && !el.hasAttribute('inert'),
    )
    document.body.appendChild(host)
    for (const el of others) el.setAttribute('inert', '')
    const root = createRoot(host)
    const done = (result: boolean | string | null) => {
      for (const el of others) el.removeAttribute('inert')
      root.unmount()
      host.remove()
      if (previous && document.contains(previous)) previous.focus()
      resolve(result)
    }
    flushSync(() => root.render(createElement(AppDialog, { spec, onDone: done })))
  })
}

/** Rückfrage mit Ja/Abbrechen; liefert true, wenn bestätigt. */
export function confirmDialog(options: string | ConfirmOptions): Promise<boolean> {
  const opts = typeof options === 'string' ? { message: options } : options
  return open({ kind: 'confirm', options: opts }) as Promise<boolean>
}

/** Eingabe abfragen; liefert den Text oder null bei Abbruch. */
export function promptDialog(options: PromptOptions): Promise<string | null> {
  return open({ kind: 'prompt', options }) as Promise<string | null>
}

/** Auswahl zwischen mehreren Knöpfen; liefert den Wert des gewählten. */
export function choiceDialog(options: ChoiceOptions): Promise<string> {
  return open({ kind: 'choice', options }) as Promise<string>
}

/** Hinweis mit OK. */
export function alertDialog(options: string | AlertOptions): Promise<void> {
  const opts = typeof options === 'string' ? { message: options } : options
  return open({ kind: 'alert', options: opts }).then(() => undefined)
}

/** Rückfrage vor dem Entfernen einer Abteilungsrolle; nennt ggf. die Inhaber. */
export function confirmRoleRemoval(name: string, holders: string[] | number): Promise<boolean> {
  const count = typeof holders === 'number' ? holders : holders.length
  const who =
    typeof holders === 'number'
      ? `${count === 1 ? 'Ein Mitglied hat' : `${count} Mitglieder haben`} diese Rolle.`
      : `${holders.join(', ')} ${count === 1 ? 'hat' : 'haben'} diese Rolle.`
  return confirmDialog({
    title: `Rolle „${name}“ entfernen?`,
    message:
      count > 0
        ? `${who} Die Rolle wird auch bei den Mitgliedern entfernt, einschließlich früherer Einträge in der Mitgliedsakte.`
        : undefined,
    confirmLabel: 'Entfernen',
  })
}
