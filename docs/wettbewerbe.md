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

## Scheiben, Treffer und Gleichstandsregeln

Schritt 1 der Schießscheiben-Auswertung (Konzept: `konzepte/schiessscheiben-recherche.md`,
Abschnitt 6). Eine Einzelwertung kann eine **Scheibe** aus dem Katalog
(`backend/competitions/targets.py`: LG 10 m DSB, LG Kyffhäuser auch mit 5 Spiegeln, UFOLEP,
Laufende Scheibe, LP 10 m, KK 50 m und 100 m, Pistole 25 m) oder eine **eigene Scheibe**
(Durchmesser höchster Ring, Ringbreite, Kaliber, Ringe, Innenzehner, Teilerfaktor) haben.

- Wertung eines Treffers bei Abstand *d* zur Mitte: Grenze *g* = Radius höchster Ring +
  Kaliber/2, Wert = höchster Ring + (*g* − *d*)/Ringbreite; Zehntel abgeschnitten, höchstens
  x,9; Ring abgeschnitten, unter dem niedrigsten Ring 0. Innenzehner je Scheibe „berühren“
  (LP, KK) oder „ganz weggeschossen“ (LG-Punkt). Teiler = *d* in 1/100 mm mal Teilerfaktor.
- **Wertungsart**: „frei“ (wie bisher, Summe eingeben), Ringe, Zehntel oder Teiler. Bei
  Ringe/Zehntel/Teiler stellt HUBIplan Nachkommastellen, Richtung und Höchstwert selbst ein.
- **Treffer** (`Hit`, x/y in mm, y nach oben, Quelle angetippt/Foto/von Hand): `GET/PUT
  competitions/<id>/hits/` ersetzt die Treffer eines Starters. Bei Ringe/Zehntel zählt die
  Summe der besten „davon in der Wertung“, bei Teiler der beste Teiler (bzw. die Summe der
  besten). Ändert sich Scheibe, Wertungsart oder Zahl der gewerteten Schüsse, rechnet HUBIplan
  alle Werte mit Treffern neu. Ohne Treffer bleibt die eingegebene Summe.
- **Gleichstandsregeln** (`tiebreak.py`), in einstellbarer Reihenfolge vor dem Stechen: Serien
  von hinten, mehr 10er/9er …, Innenzehner, Zehntelsumme, bester Teiler, schlechtester Schuss
  näher an der Mitte; Vorlagen „wie DSB“ und „wie BHDS“. Sie greifen nur, wenn alle Gleichen
  Treffer haben; sonst bleibt der Platz geteilt (auf Preisplätzen: Stechen). Die Auswertung
  nennt die Regel, die entschieden hat.
- `GET competitions/targets/` liefert Katalog, Wertungsarten und Regeln für die Oberfläche.

Ergebnisse sind vereinsintern, nicht amtlich. Die mit „prüfen“ markierten Maße in der Recherche
sind vor ernsthafter Nutzung gegen die aktuelle Sportordnung zu lesen.

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

**Mehrere Geräte gleichzeitig.** Jedes Gerät fragt alle 3 s nur einen kurzen Stand ab
(`version/`, beim Standzugang `/api/public/stand/<schlüssel>/version/`: Prüfsumme über Starter,
Werte, Schüsse, Pfänder und Stechen); ändert er sich, holt es Starter und Werte neu. Ohne eigene
Eingaben wird zusätzlich alle 15 s abgeglichen. Echter Push (offene Verbindungen) ginge mit den
synchronen Gunicorn-Workern nicht; das Nachfragen ist billig. „Zuletzt erfasst“ zeigt die
Eingaben aller Geräte (`scored_at` je Starter). Rechts neben der Erfassung (auf dem Handy
darunter) stehen die Tabellen aller Wertungen mit allen Plätzen (`standings` ohne Statistik).
Legen zwei Geräte ohne Netz dasselbe Mitglied an, wird der zweite Starter mit dem ersten
zusammengeführt: Seine Gerätekennung wird zum zweiten Namen (`Starter.aliases`), die Werte
laufen wie sonst (der spätere gilt), und das Gerät zeigt einen Hinweis. Gäste werden nicht
zusammengeführt (gleicher Name kann eine andere Person sein).

**Abschluss im Standmodus** (angemeldet): unten „Abschluss“ mit den Schützen ohne Ergebnis,
„Schießen beenden“ (Zustand vorläufig, nur verwalten), „Stechen anlegen …“ bei Gleichstand auf
einem Preisplatz und die Werte im Stechen, danach „Endgültig abschließen“. Die Regeln des
Stechens (Schüsse, davon gewertet) werden beim Anlegen festgelegt, vorbelegt aus dem vorigen
Stechen oder dem Vorschlag unter „Einrichten“, und lassen sich ändern, solange kein Wert
eingetragen ist (`PATCH shootoffs/<id>/`). Ein Gast kann statt eines Vereins eine Untereinheit
bekommen (Vorschläge beim Tippen) und zählt dann für deren Wertung. Der Standmodus ist dunkel
in der Vereinsfarbe.

Über den Standzugang (ohne Anmeldung) gehen Stechen anlegen, Regeln ändern, Werte und beim
Zugstechen der Schütze (`/api/public/stand/<schlüssel>/shootoffs/`, `shootoffs/<id>/`,
`shootoff-entries/<id>/`, `unit-members/`; im Protokoll „Standzugang <Bezeichnung>“), wie mit
„Ergebnisse erfassen“. „Schießen beenden“, Abschluss, Zurücksetzen und Stechen entfernen bleiben
angemeldet. Stechen brauchen Empfang (keine Warteschlange), damit nicht zwei Tablets zwei Stechen
anlegen.

**Zurücksetzen** (`reset/`, „Einrichten“, nur verwalten, nicht bei endgültig): löscht Werte,
Stechen, Plätze, Schüsse und gefallene Pfänder, wahlweise auch alle Starter; Regeln, Pfänder,
Mannschaften, Standzugang und Termin bleiben, der Zustand geht auf „Vorbereitung“. Der Zähler
`generation` steigt; Geräte schicken ihn beim Abgleich mit, Eingaben von vor dem Zurücksetzen
werden verworfen und das Gerät sagt es.

## Vogelschießen

- **Pfänder** (`Prize`) in fester Reihenfolge, Vorlage Kopf, linker Flügel, rechter Flügel,
  Schweif, Rumpf; Namen, Anzahl und Preis frei. Schalter „wer ein Pfand errungen hat, scheidet
  aus“ (Standard an) und „Pfänder in fester Reihenfolge“ (Standard aus: jedes hängende Teil
  kann fallen).
- **Losnummer** = Startnummer: aus dem Hut eintragen (doppelte Nummern werden abgelehnt) oder
  digital ziehen (`draw/`, zufällig aus den freien Nummern 1 … „Lose im Hut“; ohne diese
  Angabe 1 … Anzahl der Schützen, dann bekommt ein Nachzügler meist die nächste Nummer), dazu
  „alle ohne Nummer auf einmal auslosen“ (`draw-all/`). Mit „Lose im Hut“ sind Lücken normal und
  werden nicht gemeldet. Wie gezogen und wann steht beim Starter.
- **Reihenfolge** (`bird.py`, gleiche Regel auf dem Gerät in `frontend/src/api/bird.ts`): alle
  mit Losnummer aufsteigend, ohne die, die fehlen oder sich zurückgezogen haben, und ohne die
  mit Pfand (wenn „scheidet aus“). Dran ist die nächsthöhere Nummer nach dem letzten Schuss;
  danach beginnt eine neue Runde.
- **Live** im Standmodus: „Schuss“ zählt (`Shot`), „Pfand gefallen“ wählt Teile (auch zwei mit
  einem Schuss), „Schütze fehlt“, „Rückgängig“ nimmt den letzten Schuss samt Pfändern zurück.
  Tastatur: Leertaste = Schuss, Ziffern = Pfand, Enter speichert, Strg+Z = Rückgängig.
  Bei fester Reihenfolge heißt der Knopf „<nächstes Pfand> gefallen“ und speichert mit einem
  Klick; „mehrere auf einmal“ wählt bis wohin. Sind alle Pfänder gefallen, zählt kein Schuss
  mehr (auch nicht von anderen Geräten); der Standmodus bietet Rückgängig und den Abschluss.
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

Für ein geliehenes Gerät ohne Konto erzeugt, wer Wettbewerbe verwaltet, unter „Erfassen“ (Knopf
„Anderes Gerät per QR-Code“, ebenso oben im Standmodus)
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
enthalten alles (mitgliederbezogen, auch die Treffer); die Wettbewerbe kommen nach den Terminen (Verweis). Keine Dateifelder.
