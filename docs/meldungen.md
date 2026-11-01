# Meldungen

Eine Einheit meldet Mannschaften, Personen oder Angaben an einen Veranstalter, z. B. zwei
Mannschaften mit je fünf Schützen zum Vergleichsschießen des Dachverbands. Konzept:
`konzepte/meldungen.md` im Projektordner. App `backend/entries`, Oberfläche `/meldungen`.

Stand: Schritt 1 (Veranstalter außerhalb von HUBIplan). Noch nicht umgesetzt: Interessenabfrage
über Terminzusagen (Schritt 2), Ausschreibungen eines Veranstalters in HUBIplan mit Eingang und
internen Meldungen der Untereinheiten (Schritt 3), Gebühren als Rechnung (Schritt 4), Verbund
(Schritt 5).

## Freischalten und Rechte

- Modul „Meldungen“ (`entries`), je Einheit unter Plattform › Organisationen freischalten
  (wie Wettbewerbe nicht automatisch an).
- Recht „Meldungen abgeben“ (`entries.submit`). Vorstandsrollen (mit „Rollen verwalten“) haben
  es nach der Migration.
- Mitglieder auswählen darf nur, wer auch `members.view` hat. Gäste (Name, Verein) gehen ohne.

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
- **Bestätigung** des Veranstalters lässt sich vermerken (z. B. „per Mail am …“).

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
