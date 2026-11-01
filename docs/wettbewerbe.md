# Wettbewerbe

Eigene Schießen und andere Wettbewerbe mit Einzel- und Zugwertung, Stechen, Auswertung,
Druckvorlagen und einem Standmodus für Tablet und Handy; Vogelschießen mit Pfändern; fremde
Wettbewerbe, bei denen die Einheit ihre Plätze einträgt. Konzept im Projektordner
(`konzepte/wettbewerbe.md`); umgesetzt sind Schritt 1 (Preisschießen), Schritt 2
(Vogelschießen), 2b (Standmodus) und von Schritt 3 der Teil ohne Meldungen.

## Einschalten und Rechte

- Modul `competitions`, je Einheit von der Plattform freizuschalten (Plattform ›
  Organisationen › Module „Wettbewerbe“). Nur Vereine und Dachverbände.
- `competitions.manage` „Wettbewerbe verwalten“: anlegen, Wertungen, Zustand, löschen,
  kopieren. Bestehende Rollen mit „Rollen verwalten“ bekommen es per Migration.
- `competitions.results` „Ergebnisse erfassen“ (z. B. Schießmeister): Starter, Werte und
  Stechen eintragen. Sieht von Startern nur Name, Untereinheit und Startnummer.

## Aufbau

- **Wettbewerb:** Titel, Datum, Anlass, Art, Ort, Beschreibung, weitere Angaben (frei),
  Zustand (Vorbereitung, läuft, vorläufig, endgültig), Webseite (aus, live, nach Abschluss;
  die Anzeige auf der Webseite folgt in einem späteren Schritt).
- **Wertungen:** Einzelwertung (Schüsse je Schütze, davon gewertet, Höchstwert je Schuss,
  Einheit, Nachkommastellen, größer/kleiner ist besser) und Wertung der Untereinheiten (aus
  einer Einzelwertung: Summe der besten k, Summe aller, Durchschnitt). Bei „beste k“ wird eine
  Untereinheit mit weniger als k Schützen nicht gewertet. Je Wertung Preisplätze und die
  Bedingungen fürs Stechen.
- **Starter:** Mitglieder (Untereinheit am Wettbewerbstag vorbelegt, änderbar) und Gäste
  (Name, Verein; ob ein Gast für einen Zug zählt, entscheidet man im Einzelfall). Der Name
  wird beim Starter mitgespeichert und bleibt nach Austritt erhalten.
- **Erfasst** wird je Schütze die Summe der gewerteten Schüsse von der Karte.
- Vorlagen beim Anlegen: „Schießen mit Einzel- und Zugwertung“ (5 Schuss, 3 gewertet, 10
  Preisplätze; Zug: beste 5, 3 Preisplätze), „nur Einzelwertung“, „Vogelschießen mit
  Pfändern“, „Fremder Wettbewerb“. Form (`rangliste`/`vogel`) und eigen/fremd (`own`) stehen
  nach dem Anlegen fest.

## Rangliste und Stechen

`backend/competitions/ranking.py` rechnet ohne Datenbank. Gleiche Werte teilen sich den
Platz. Berührt ein Gleichstand einen Preisplatz, ist ein Stechen nötig; vorher lässt sich der
Wettbewerb nicht endgültig abschließen. Ein Stechen gilt für die Gruppe, die es betrifft;
bleibt es gleich, folgt ein weiteres. Im Stechen der Untereinheiten schießt je Einheit ein
Mitglied (vorgeschlagen: der beste Schütze der Einheit, jedes Mitglied wählbar).

## Erfassen und Standmodus

- Suchfeld immer aktiv: Name (auch „muel“ für „Müller“) oder Startnummer, Enter, Punkte,
  Enter. Nicht gefunden: als Gast hinzufügen. Hat ein Schütze schon Punkte, kommt eine
  Rückfrage.
- Standmodus `/stand/<einheit>/<wettbewerb>`: Vollbild ohne Menü, große Bedienelemente,
  auf dem Handy Speichern am unteren Rand. Der Bildschirm bleibt an (Wake Lock).
- **Offline:** Starterliste und Mitgliederliste (`members/`) liegen auf dem Gerät
  (localStorage). Eingaben gehen in eine Warteschlange und werden über `sync/` nachgereicht
  (neue Starter mit Gerätekennung `client_key`, daher nichts doppelt). Ist ein Wert auf dem
  Server später geändert worden, gilt der spätere und der Standmodus zeigt es an. Beim
  Vogelschießen gehen auch Schüsse, Rückgängig und Losnummern in die Warteschlange (mit
  Gerätekennung, also nichts doppelt); das Gerät rechnet die Reihenfolge selbst weiter.
- **Neu laden ohne Netz:** `public/sw-stand.js` merkt sich die Seite des Standmodus und ihre
  Dateien (nur Seiten unter `/stand/` und Dateien unter `/assets/`, nie `/api/`). Ist der
  Server beim Start nicht erreichbar, öffnet sich der Standmodus mit dem Speicher des Geräts.

Beim gewählten Schützen gibt es „Wert löschen“ (Abgleich `score` mit `value: null`) und „Aus
dem Wettbewerb entfernen“ (`starter_delete`, auch für offline angelegte Starter; ein zweites
Senden ist harmlos). Wer Wettbewerbe verwaltet und angemeldet ist, kann im Standmodus
„Endgültig abschließen“, sobald alle Eingaben des Geräts abgeglichen sind (nicht über einen
Standzugang); offene Stechen verhindern den Abschluss wie unter „Einrichten“.

## Vogelschießen

- **Pfänder** (`Prize`) in fester Reihenfolge, Vorlage Kopf, linker Flügel, rechter Flügel,
  Schweif, Rumpf; Namen, Anzahl und Preis frei. Schalter „wer ein Pfand errungen hat, scheidet
  aus“ (Standard an) und „Pfänder in fester Reihenfolge“ (Standard aus: jedes hängende Teil
  kann fallen).
- **Losnummer** = Startnummer: aus dem Hut eintragen (doppelte Nummern werden abgelehnt) oder
  digital ziehen (freie Nummer aus 1 … Anzahl der Schützen, `draw/`), dazu „alle ohne Nummer
  auf einmal auslosen“ (`draw-all/`). Wie gezogen und wann steht beim Starter.
- **Reihenfolge** (`bird.py`, gleiche Regel auf dem Gerät in `frontend/src/api/bird.ts`): alle
  mit Losnummer aufsteigend, ohne die, die fehlen oder sich zurückgezogen haben, und ohne die
  mit Pfand (wenn „scheidet aus“). Dran ist die nächsthöhere Nummer nach dem letzten Schuss;
  danach beginnt eine neue Runde.
- **Live** im Standmodus: „Schuss“ zählt (`Shot`), „Pfand gefallen“ wählt Teile (auch zwei mit
  einem Schuss), „Schütze fehlt“, „Rückgängig“ nimmt den letzten Schuss samt Pfändern zurück.
  Tastatur: Leertaste = Schuss, Ziffern = Pfand, Enter speichert, Strg+Z = Rückgängig.
  Gezählt werden Schuss-Nr. gesamt und Schüsse für das Pfand (seit dem vorher gefallenen).
- **Nachträglich** (auf Papier gezählt): je Pfand Schütze, Schuss-Nr. gesamt, Schüsse für das
  Pfand; Gesamtzahl der Schüsse unter „Einrichten“.
- Auswertung: Pfänderliste, Schüsse insgesamt, Schützen, Runden, Dauer, Pfänder je Zug.

## Fremde Wettbewerbe

Ein anderer richtet aus (Feld „Ausrichter“). Die Einheit trägt ihre Schützen ein (nur
Mitglieder), stellt Mannschaften zusammen (`Team`, nur bei fremden Wettbewerben) und trägt
Platz, Wert und Bemerkung ein (`Placing`, `placings/`), optional mit „Teilnehmer insgesamt“
für „Platz 2 von 14“. Die Verbindung zu den Meldungen (Starter aus der Meldung, Ergebnisse
vom Ausrichter in HUBIplan) folgt, sobald es die Meldungen gibt.

## Standzugang

Für ein geliehenes Gerät ohne Konto erzeugt, wer Wettbewerbe verwaltet, unter „Einrichten“
einen Standzugang (Link und QR-Code, `/stand/zugang/<schlüssel>`). Er öffnet nur diesen
Wettbewerb im Standmodus, erlaubt nur Erfassen (`/api/public/stand/<schlüssel>/…`: Einrichtung,
Starter, Mitglieder nur mit Name und Untereinheit, Abgleich), läuft am Ende des
Wettbewerbstags (oder heute, wenn der schon war) ab und lässt sich beenden. Gespeichert wird
nur der Hash des Schlüssels; im Änderungsprotokoll steht „Standzugang <Bezeichnung>“.

## Termin im Kalender

Ein Wettbewerb kann zu einem einmaligen Termin der eigenen Einheit gehören (`event`). Beim
Anlegen wählt man einen Termin aus dem Kalender (Titel und Datum kommen mit; Ort und
Beschreibung, wenn sie leer sind) oder lässt einen neuen ganztägigen Termin „Mitglieder“ mit
Titel, Datum, Ort und Beschreibung anlegen (`create_event`, nur mit „Termine verwalten“).
Unter „Einrichten“ lässt sich die Verknüpfung ändern, lösen oder ein Termin anlegen
(`event/`); weicht das Datum ab, erscheint ein Hinweis. Zur Auswahl stehen die Termine, die man
im Kalender sieht, ohne Serien (`event-candidates/?suche=&datum=`). Mit Zu- und Absagen
übernimmt „Zusagen als Starter übernehmen“ (`starters/from-event/`) alle Mitglieder mit
Zusage, die noch nicht Starter sind. Wird der Termin gelöscht, bleibt der Wettbewerb.

## Ausgaben

`export/?als=`: `pdf` (Ergebnisliste mit Kennzahlen, beim Vogelschießen die Pfänderliste),
`xlsx`, `schiessliste` (`sortierung=name|einheit|nummer`, `leerzeilen=`, `leer=1` für eine
Liste ohne Namen), `stechliste&stechen=<id>`, beim Vogelschießen `losliste` (nach Losnummer
mit Feld für Striche) und `pfaenderliste` (leer zum Ausfüllen). Schieß- und Losliste füllen
die letzte Seite mit leeren Zeilen auf (mindestens `leerzeilen`); die leere Schießliste ist
genau eine volle Seite.

## Daten

App `competitions`, Tabellen mit `organization` und RLS. Export und Datenübernahme
enthalten alles (mitgliederbezogen); die Wettbewerbe kommen nach den Terminen (Verweis). Keine Dateifelder.
