# Meldungen

Eine Einheit meldet Mannschaften, Personen oder Angaben an einen Veranstalter, z. B. zwei
Mannschaften mit je fünf Schützen zum Vergleichsschießen des Dachverbands. Konzept:
`konzepte/meldungen.md` im Projektordner. App `backend/entries`, Oberfläche `/meldungen`.

Stand: Schritt 1 (Veranstalter außerhalb von HUBIplan), Schritt 2 (Interessenabfrage über
Terminzusagen, „Wofür bin ich gemeldet?“) und Schritt 3 (Ausschreibung an die eigenen
Untereinheiten mit Eingang). Noch nicht umgesetzt: Gebühren als Rechnung (Schritt 4), Verbund
(Schritt 5), Ausschreibungen eines Dachverbands an seine Vereine auf derselben Instanz.

## Freischalten und Rechte

- Modul „Meldungen“ (`entries`), je Einheit unter Plattform › Organisationen freischalten
  (wie Wettbewerbe nicht automatisch an).
- Recht „Meldungen abgeben“ (`entries.submit`). Vorstandsrollen (mit „Rollen verwalten“) haben
  es nach der Migration.
- Mitglieder auswählen darf nur, wer auch `members.view` hat. Gäste (Name, Verein) gehen ohne.
- Recht „Ausschreibungen an die eigenen Untereinheiten verwalten“ (`entries.manage`), ebenfalls
  für Vorstandsrollen nach der Migration; in Rollen der Untereinheiten „Meldungen … abgeben“
  (`dept.entries.submit`), nicht automatisch vergeben.

## Ausschreibung

Die Einheit überträgt die Ausschreibung, die sie per Brief oder Mail bekommen hat: Titel,
Veranstalter mit Anschrift und E-Mail, Datum, Ort, Meldeschluss, Stichtag, Meldegebühr, was nach
Meldeschluss noch geht (nichts, nur Ersatz, alles bis zum Anlass).

- **Bausteine** des Formulars: Mannschaften (Anzahl, Größe, Ersatzleute, Aufgaben wie
  „Mannschaftsführer“), Personenliste, Zahl, Auswahl, Text.
- **Angaben je Person:** Name immer, sonst nur, was angekreuzt ist (Geburtsdatum, Geburtsjahr,
  Mitgliedsnummer, Eintrittsdatum, Untereinheit, Mitgliedsart, Zusatzfelder).
- **Bedingungen:** aktives Mitglied am Stichtag, Mindest-/Höchstalter, Mitgliedsarten,
  Untereinheiten, nur eine Mannschaft je Person, Gäste erlaubt. Verstöße erscheinen als Hinweis;
  abgeben bleibt möglich (Ralf 2026-11-01).
- **Kopieren:** „Für das nächste Jahr kopieren“ übernimmt alles und schiebt Datum, Fristen und
  die Jahreszahl im Titel um ein Jahr.

## Meldung

- Mannschaften bekommen einen Namen aus Kurzname und römischer Zahl („Hubertus I“).
- Personen kommen aus der kompletten Mitgliederliste (Suche, auf Wunsch auch Ausgetretene) oder
  als Gast.
- **Abgeben** hält eine Fassung fest (`EntryVersion`, Stand verschlüsselt) und setzt den Zustand
  „abgegeben“. Jede spätere Änderung markiert die Meldung als geändert; „Änderung melden“ hält
  die nächste Fassung fest und beschreibt die Änderungen in Worten („In Hubertus I: B statt A.“).
  Ohne Änderung entsteht keine neue Fassung.
- Mannschaften und Plätze behalten ihre Kennung; „ersetzen“ tauscht nur die Person.
- **Zurückziehen** hält eine Fassung „Rückzug“ fest, danach ist die Meldung gesperrt.
  „Wieder öffnen“ macht sie erneut zum Entwurf mit den bisherigen Angaben (Fassungen bleiben,
  die nächste Abgabe ist wieder eine Meldung). „Meldung löschen“ entfernt sie samt Fassungen;
  die Ausschreibung bleibt (`POST …/entry/reopen/`, `DELETE …/entry/discard/`).
- **Bestätigung** des Veranstalters lässt sich vermerken (z. B. „per Mail am …“).

## Interessenabfrage über den Kalender

Unter „Ausschreibung“ lässt sich die Ausschreibung mit einem Termin im Kalender verknüpfen
(Modul Termine). „Termin mit Zusagen anlegen“ legt einen ganztägigen Termin am Tag des Anlasses
an, sichtbar für Mitglieder, mit Zu- und Absagen bis zum Abend vor dem Meldeschluss (das
Anlegen braucht das Recht, Termine zu verwalten). Wer zusagt, möchte mitmachen; eine eigene
Tabelle für das Interesse gibt es nicht.

Unter „Meldung“ stehen die Zusagen als Vorauswahl („Zusagen zum Termin“), je Person mit
Untereinheit, Geburtsjahr und Bemerkung; ein Klick ordnet sie einer Mannschaft oder Liste zu.
Die Zusagen sind nur eine Vorauswahl: Gemeldet werden kann weiter jedes Mitglied aus der
kompletten Mitgliederliste (Ralf 2026-11-01). Bei der Suche steht dabei, wer zu- oder abgesagt
hat. Die Zusagen sieht nur, wer die Mitglieder sehen darf.

## Ausschreibung an die eigenen Untereinheiten

Wer „Ausschreibungen an die eigenen Untereinheiten verwalten“ (`entries.manage`) hat, kann
beim Anlegen ankreuzen „Wir schreiben selbst aus, unsere Untereinheiten melden“, etwa für ein
Preisschießen, zu dem die Züge ihre Schützen melden. Unter „Ausschreibung“ wählt man die
angeschriebenen Untereinheiten (keine Auswahl: alle direkt darunter) und kann festlegen, dass
Verstöße gegen die Bedingungen das Abgeben sperren.

- **Untereinheiten melden in ihrem Bereich** (Bereich der Untereinheit › Meldungen), mit dem
  Recht „Meldungen … abgeben“ (`dept.entries.submit`) in einer Rolle der Untereinheit oder
  darüber. Mitglieder wählen sie dort nur aus der eigenen Untereinheit (samt Teilbaum). Die
  Meldung geht „in HUBIplan“ an den Veranstalter, ohne Brief.
- **Eingang des Veranstalters:** je angeschriebene Untereinheit Zustand, Anzahl Mannschaften und
  Personen, Hinweise und letzte Abgabe. Ein Klick öffnet die Meldung; der Veranstalter kann sie
  dort auch selbst eintragen (z. B. für Untereinheiten ohne eigenen Zugang), **bestätigen** oder
  **mit Rückfrage zurückgeben**. Die Untereinheit bekommt dann eine Mail, sieht die Rückfrage
  und gibt erneut ab (ohne Änderung ohne neue Fassung).
- **Erinnern:** „Fehlende erinnern“ schickt eine Mail an alle, die für eine noch nicht meldende
  Untereinheit melden dürfen und einen Zugang haben. Untereinheiten ohne solche Person werden
  genannt.
- **Meldeliste** aller abgegebenen Meldungen als Excel oder CSV, mit Spalte „Untereinheit“.
- **Doppelt gemeldet:** Meldet eine andere Untereinheit dieselbe Person, steht ein Hinweis da.
- **Wettbewerb:** Beim ersten Bestätigen entsteht ein eigener Wettbewerb (Einzelwertung,
  Wertung der Untereinheiten, bei Mannschaften Mannschaftswertung). Bestätigte Personen werden
  Starter mit der meldenden Untereinheit, Mannschaften werden Mannschaften. Spätere
  Bestätigungen führen nach, ein Rückzug entfernt wieder, was die Meldung angelegt hat
  (Starter mit erfassten Werten bleiben). Starter, die der Ausrichter selbst einträgt, bleiben
  unberührt.

Die Daten liegen beim Veranstalter (RLS), auch die Meldungen der Untereinheiten.

## Mitgliederbereich: „Wofür bin ich gemeldet?“

Im Mitgliederbereich zeigt die Kachel „Gemeldet“ die Anlässe, für die der Verein das Mitglied
gemeldet hat, kommende zuerst, vergangene noch ein Jahr lang. Gezeigt wird nur, was in der
letzten Fassung an den Veranstalter ging: kein Entwurf, keine noch nicht gemeldete Änderung,
nichts nach einem Rückzug. Wird jemand ersetzt, erscheint der Ersatz mit der nächsten Fassung.

## Meldewege

| Weg | Was passiert |
|---|---|
| Brief | PDF auf dem Briefbogen der Einheit (DIN 5008, `LetterDocument`), mit Platz für die eigenhändige Unterschrift. Unter „Fassungen“ zum Drucken. |
| E-Mail | Mail über den Postausgang an den Veranstalter, Brief als PDF im Anhang, Antwort an die abgebende Person, Kopie an sie. |
| Tabelle | Excel- und CSV-Datei der Meldung, z. B. zum Hochladen in ein Portal. |
| Sonstiges | nur Vermerk (z. B. „persönlich übergeben“). |

Brief, Excel und CSV gibt es für jede Fassung und als Vorschau vor dem Abgeben. Unterzeichnet
wird mit dem Namen der abgebenden Person und einer ihrer Funktionen in der Einheit. Ein
gespeichertes Unterschriftsbild gibt es noch nicht (auch die Briefvorlage lädt es nur beim
Erzeugen hoch).

## Wettbewerb

Ist das Modul Wettbewerbe an und die Ausschreibung hat „fremden Wettbewerb anlegen“ (Standard),
legt das erste Abgeben einen fremden Wettbewerb mit Titel, Veranstalter, Datum und Ort an, dazu
Einzel- und Mannschaftswertung, die Mannschaften und je gemeldeter Person einen Starter
(`EntryTeam.team`, `EntryPerson.starter`). Spätere Fassungen führen Mannschaften und Starter nach,
solange der Wettbewerb in Vorbereitung ist; danach gilt die Starterliste dort. Plätze trägt die
Einheit im Wettbewerb ein.

## Aufbewahrung

Ein Jahr nach dem Anlass (ohne Datum: nach der Abgabe) kürzt die tägliche Aufgabe
`entries.tasks.shorten_old_entries` jede Fassung auf Namen, Mannschaft und Aufgabe; weitere
Angaben je Person werden gelöscht. Beim Austritt greift die normale Löschfrist für die Akte;
Meldungen behalten den Namen als Text.

## Export

Alle Tabellen sind Teil des vollständigen Exports und der Datenübernahme (`datatransfer`);
Meldungen kommen mit den Mitgliedsdaten mit, Ausschreibungen immer.
