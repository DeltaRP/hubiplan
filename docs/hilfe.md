# Hilfe

Die Hilfe beantwortet „Wie mache ich …?“, „Was kann ich auf dieser Seite tun?“ und „Was heißt
dieses Wort?“. Konzept: `konzepte/hilfe-funktion.md` im Projektordner (Schritte H1–H6).

## Bausteine

| Baustein | Wo |
| --- | --- |
| Hilfe-Seite | `/hilfe`: Suche über Anleitungen, Seitenhilfen und Glossar, Anleitungen nach Bereichen; Menüpunkt „Hilfe“ unten in der Seitenleiste |
| Anleitung oder Seitenhilfe einzeln | `/hilfe/<name>` bzw. `/hilfe/seite/<name>` |
| Hilfe zu dieser Seite | Knopf oben in der Kopfleiste oder Taste `?`: Leiste rechts (schmal: Blatt von unten) mit der Seitenhilfe und den Anleitungen der Seite; Esc schließt |
| Glossar | `/glossar` wie bisher ([lernhilfen.md](lernhilfen.md)) |

Sichtbar ist nur, was zur Person passt: Das Modul (`modul`) muss freigeschaltet sein und die Person
braucht eines der Rechte (`rechte`) in der gewählten Einheit. In der Ansicht als Rolle gelten die
Rechte der Ansicht ([ansicht-als-rolle.md](ansicht-als-rolle.md)); die Hilfe zeigt dann, was diese
Rolle sieht.

## Texte pflegen

Jede Anleitung und jede Seitenhilfe ist eine Markdown-Datei, je Sprache eine, mit gleichem Namen:

```
frontend/src/help/de/anleitungen/passwort-aendern.md
frontend/src/help/en/anleitungen/passwort-aendern.md
frontend/src/help/de/seiten/mein-konto.md
```

Kopf (zwischen zwei Zeilen `---`, in beiden Sprachen gleich bis auf `titel` und `stichworte`):

```yaml
key: guide.password            # guide.… (Anleitung) oder page.… (Seitenhilfe, Ordner seiten/)
titel: Passwort ändern
bereich: konto                 # siehe AREAS in frontend/src/help/content.ts
modul: members                 # optional: nur mit diesem Modul
rechte: [members.edit]         # optional: eines davon nötig
routen: [/mein-konto/anmeldung]
stichworte: [Kennwort, vergessen]
```

Regeln (geprüft von `src/test/Hilfe.test.tsx`):

- Jede Datei gibt es auf Deutsch und Englisch, mit gleichem Kopf und gleichen Bildern.
- Rechte, Routen und Links (`[Text](/mitglieder)`) gibt es wirklich.
- Knopf- und Feldnamen stehen **fett** und genau so, wie die Oberfläche sie zeigt (deutsch: Schlüssel
  in `src/i18n/en.json`, englisch: deren Werte).
- Höchstens zehn Schritte je Anleitung, jeder ein Satz.
- Platzhalter der Einheit wie `{pl}` (z. B. „Züge“) werden eingesetzt (`org/terms.ts`).
- Wer eine Seite oder einen Ablauf ändert, passt die Hilfe im selben PR an.

## Bildschirmfotos

Bilder stehen im Text als `![Beschreibung](bild:name)`; die Beschreibung ist der Alternativtext.
Welche Stelle ein Bild zeigt, steht in `frontend/src/help/bilder.json` (Seite, Demozugang, Ausschnitt
als CSS-Auswahl im Inhalt). Die Bilder werden nie von Hand gemacht:

```bash
scripts/hilfe-bilder.sh              # alle Bilder
scripts/hilfe-bilder.sh konto-sprache # nur einzelne
```

Das Skript läuft nur lokal (WSL auf Ralfs PC), belegt einen Testplatz, startet in Wegwerf-Containern
Datenbank, Backend mit den erfundenen Demodaten (`seed_testdata`, Englisch freigeschaltet) und die
Oberfläche aus dem Arbeitsstand und fotografiert mit Playwright jede Stelle auf Deutsch und Englisch.
Ergebnis: `frontend/public/hilfe-bilder/<sprache>/<name>.png`. Bilder ansehen, dann einchecken. Ändert
sich eine Seite sichtbar, die Bilder dazu neu erzeugen. Der Test meldet fehlende Bilder.
