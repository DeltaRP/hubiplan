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
| Für dich: erste Schritte | oben auf `/hilfe`: wichtige Anleitungen passend zu den eigenen Rechten zum Abhaken (Liste `FIRST_STEPS` in `src/help/extras.ts`); die Haken stehen nur am eigenen Konto (`/api/me/help/`), in der Ansicht als Rolle gesperrt |
| Warum sehe ich das nicht? | Anleitungen, für die ein Recht fehlt (Modul an), erscheinen ausgegraut in der Suche und unter „Häufige Aufgaben“ der Seitenhilfe, mit dem Namen des Rechts und den Rollen, die Rechte vergeben dürfen |
| Wer hilft bei uns? | auf `/hilfe` und in der Seitenhilfe: Ansprechpartner der Einheit (Einstellungen › Organisation, Recht „Organisationsdaten bearbeiten“), sonst die der nächsten Einheit darüber, sonst nur Rollennamen. Nie automatisch Personen |
| Hinweise bei uns | unter einer Anleitung: kurze Hinweise der Einheit und der Einheiten darüber (höchstens 500 Zeichen, mit „Organisationsdaten bearbeiten“ auf der Seite der Anleitung) |
| Zeig es mir | in der Seitenhilfe unter einer Anleitung: hebt auf der Seite das erste Bedienelement hervor, das die Anleitung **fett** nennt; auf `/hilfe/<name>` öffnet es erst die Seite |
| Was ist neu | Anleitung `anleitungen/was-ist-neu.md`, verlinkt oben auf `/hilfe`; bei sichtbaren Neuerungen ergänzen (neueste oben) |
| App | Mein Konto in der Android-App: „Hilfe und Anleitungen im Browser“ öffnet `/hilfe` der Instanz |

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

## Angaben der Einheit

`GET/PATCH /api/orgs/<id>/help/` liefert Ansprechpartner (eigene oder geerbte), Hinweise je Anleitung
(`notes`, von oben nach unten), die Rollen mit „Rollen verwalten“ und die Beschriftungen der Rechte;
lesen darf jede Rolle der Einheit, ändern nur „Organisationsdaten bearbeiten“.
`PUT /api/orgs/<id>/help/notes/<guide.key>/` setzt den eigenen Hinweis (leer entfernt ihn). Beides
steht im Änderungsprotokoll und in der Datenübernahme (`help_contacts`, `help_notes`).
