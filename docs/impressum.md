# Impressum und Datenschutzhinweise

Pflichtangaben der Plattform und der Einheiten (Modell `organizations.Imprint`,
Logik in `backend/organizations/imprint.py`). HUBIplan bildet die Angaben nur
technisch ab; ob sie vollständig sind, prüft der Betreiber bzw. die Einheit
(keine Rechtsberatung).

## Wer welches Impressum hat

- **Plattform** (Plattform › Impressum): Betreiber, Anschrift, Kontakt, Register,
  Datenschutzerklärung. Immer ein eigenes Impressum.
- **Einheit** (Einstellungen › Impressum, Recht `org.edit`): drei Möglichkeiten
  - *eigenes Impressum* (Standard für Dachverband und Verein),
  - *auf eigenes Impressum verlinken* (z. B. die Vereins-Website),
  - *von der übergeordneten Einheit übernehmen* (Standard für Untereinheiten).
  Die Untereinheiten wählt man oben auf derselben Seite aus.
- Am Ende der Kette steht die Plattform: Hat keine Einheit darüber ein
  Impressum, gilt das der Plattform mit einem Hinweis.

Leere Felder kommen aus den Stammdaten (Name, Anschrift, Kontakt aus
Einstellungen › Organisation). **Vertretungsberechtigte** sind die heutigen
Inhaber der Rollen mit dem Kennzeichen „vertritt die Einheit (§ 26 BGB)“
(Einstellungen › Rollen & Benutzer); ein Freitext ersetzt sie. Öffentlich
erscheinen nur Name und Funktion.

Die **Datenschutzhinweise** (Einheit, Art. 13 DSGVO) bzw. die
Datenschutzerklärung (Plattform) sind ein Text in HUBIplan oder ein Link. Die Einheit
pflegt sie unter **Einstellungen › Datenschutz**, zusammen mit den Datenschutzhinweisen
der Webseite: eine Seite, zwei getrennte Abschnitte (für Mitglieder, für Besucher der
Webseite), je mit Entwurf und „Veröffentlichen“. Untereinheiten mit eigener Webseite
sehen dort nur den Webseiten-Abschnitt. Die Plattform pflegt ihre Erklärung unter
Plattform › Impressum. Für den
Text erzeugt HUBIplan einen Vorschlag aus den Einstellungen (`imprint_generator.py`: Module, Lastschrift, Meldung an die übergeordnete Einheit, Untereinheiten, Mitgliederbereich, Löschfrist; für die Plattform Cookies, Sicherungen, Mailversand). Unbekanntes steht in eckigen Klammern. `seed_testdata` füllt leere Impressen der Demo-Einheiten mit erfundenen Angaben.

Fehlen übliche Angaben (Anschrift, Vertretung, E-Mail, Telefon,
Datenschutzhinweise), zeigt die Startseite dem Vorstand einen Hinweis. Gesperrt
wird nichts.

## Wo es erscheint

- Öffentliche Seiten ohne Anmeldung: `/impressum`, `/datenschutz` (Plattform),
  `/impressum/<key>`, `/datenschutz/<key>` (Einheit; fester Schlüssel, ändert
  sich nie). API: `/api/public/imprint/` und `/api/public/imprint/<key>/`.
- Fußzeile auf allen öffentlichen Seiten (Anmeldung, Ausweisprüfung, Foto-Upload,
  Rundschreiben-Abmeldung) und in der App, jeweils mit der passenden Einheit.
- Jede Mail über `outbox.mail.send`: Absenderzeile „im Auftrag von …“ mit Links
  zu Impressum und Datenschutz der Einheit (ohne Einheit: Plattform).
- Kalender-Abos: Link zum Impressum in der Kalenderbeschreibung
  (`X-WR-CALDESC`).

Export und Import einer Einheit übernehmen das Impressum (ohne Schlüssel) und
das Rollen-Kennzeichen.
