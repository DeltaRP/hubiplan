# Wettbewerbe

Eigene Schießen und andere Wettbewerbe mit Einzel- und Zugwertung, Stechen, Auswertung,
Druckvorlagen und einem Standmodus für Tablet und Handy; Vogelschießen mit Pfändern; fremde
Wettbewerbe, bei denen die Einheit ihre Plätze einträgt. Konzept im Projektordner
(`konzepte/wettbewerbe.md`); umgesetzt sind Schritt 1 (Preisschießen), Schritt 2
(Vogelschießen), 2b (Standmodus), Schritt 3 (fremde Wettbewerbe, Meldungen) und Schritt 4
(Auszeichnungen und Geschichte).

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
- **Antippen am Stand** (Schritt 2): Hat die Einzelwertung eine Scheibe und Ringe, Zehntel oder
  Teiler, zeigt der Standmodus nach der Schützenwahl das Scheibenbild (aus den Maßen gezeichnet,
  `target_info` der Wertung). Antippen setzt einen Treffer, Ziehen verschiebt ihn mit Lupe;
  Ansicht ganze Scheibe, Spiegel oder Mitte; Karten mit mehreren Spiegeln haben je Spiegel eine
  Ansicht. Die Summe läuft mit (`targetMath.ts`, gleiche Formel wie der Server). Gespeichert wird
  über den Abgleich (Eingabe `hits` mit Gerätezeit, auch ohne Empfang); eine spätere Änderung auf
  dem Server gewinnt. „Nur die Summe eingeben“ schaltet auf das bisherige Zahlenfeld.

Ergebnisse sind vereinsintern, nicht amtlich. Die mit „prüfen“ markierten Maße in der Recherche
sind vor ernsthafter Nutzung gegen die aktuelle Sportordnung zu lesen.

**Prüfdaten** (Schritt 3, `competitions/vision/synth.py`): künstliche Scheibenfotos aus den
  Maßen, Löcher an bekannten Stellen (Streuung, eng/überlappend, Loch in Loch, weit), dazu
  Schräge, Drehung, Unschärfe, Lichtverlauf, Schatten, Rauschen, JPEG; gleicher Startwert,
  gleiches Bild. `python manage.py scheiben_pruefdaten <ordner> --anzahl 200` schreibt Bilder
  und Lösungen (`loesungen.jsonl`). Die Messlatte (`vision/benchmark.py`) zählt Schusszahl
  richtig, Ringe richtig, Summe richtig, „bitte prüfen“ (und ob zu Recht) und vor allem
  „unbemerkt falsch“. Nur erfundene Daten; echte Probefotos bleiben auf Ralfs PC.

**Fotoerkennung** (Schritt 4, `competitions/vision/detect.py`, OpenCV ohne Oberfläche): Im
  Standmodus nimmt „Foto der Scheibe“ ein Bild auf (Handy: Rückkamera), verkleinert es im
  Browser und schickt es an `POST competitions/<id>/photo/` bzw. über den Standzugang an
  `…/stand/<schlüssel>/photo/` (`scoring`, `photo`). Zurück kommt nur ein **Vorschlag**
  (`hits` mit Quelle „foto“, `needs_review`, `note`); er erscheint im Antipp-Bild, wird dort
  geprüft und verschoben und erst mit „Speichern“ wie angetippte Treffer gespeichert (Quelle
  bleibt „foto“, bis jemand den Treffer verschiebt). Das Foto wird **nur im Speicher**
  ausgewertet und nie abgelegt; höchstens 15 MB und 60 Fotos je 10 Minuten und Konto bzw.
  Standzugang. Ohne Empfang geht die Fotoerkennung nicht, Antippen geht immer.
  - Ablauf: Spiegel als Ellipse finden, dann Spiegelrand und Ringlinien entlang von Strahlen
    suchen und die volle Abbildung schätzen (Schräge, Lichtverlauf); Löcher als deutliche
    Abweichung von der örtlichen Helligkeit, vor hellem Hintergrund über den geschlossenen
    Lochrand. Überlappende Löcher: je Fläche werden mehrere Anzahlen Kreise eingepasst
    (Umriss vor dem Glätten, damit die Kerben zwischen den Löchern erhalten bleiben); die
    bekannte Schusszahl geht dorthin, wo ein weiterer Kreis die Flächen am meisten besser
    deckt. Weil der Bleirand auf Weiß ein Loch größer wirken lässt, probiert die Erkennung
    Lochgrößen von 1,0 bis 1,16 × Kaliber und nimmt die am besten passende.
  - „Bitte prüfen“, wenn die Schusszahl nicht passt, eine Fläche nicht eindeutig ist, drei
    oder mehr Löcher ineinander liegen (der Umriss lässt die Lage dann offen), ein Treffer
    0,1 mm oder näher an einer Ringlinie liegt oder der Spiegel unsicher erkannt wurde.
  - Nur Scheiben mit schwarzem Spiegel (`photo` in `target_info`). Karten mit bis zu fünf
    Spiegeln (üblich: vier Ecken und Mitte) werden Spiegel für Spiegel ausgewertet; die
    Spiegel sind in Lesereihenfolge des Fotos nummeriert (oben links zuerst), jeder Treffer
    trägt seine Spiegelnummer. Messlatte Fünf-Spiegel-Karte (künstliche Fotos, 10 Karten,
    leicht): alle 50 Spiegel gefunden, 60–80 % der Spiegel ganz richtig, unbemerkt falsch 0 %,
    etwa 1,3 s je Foto. Im Verein üblich ist aber die Karte mit einem Spiegel und mehreren
    Schuss darin.
  - Stand der Messlatte (01.11.2026, künstliche Fotos, je 60, LG DSB und Kyffhäuser, Schwierigkeit
    leicht / mittel / schwer): Schusszahl richtig 100 / 95 / 90 %, alle Ringe richtig 85 / 73 /
    60 %, unbemerkt falsch 0 / 0 / 0 %, „bitte prüfen“ 80 / 83 / 90 % (vorher 93 / 88 / 85 %
    und 68 / 58 / 45 %). Nur dichte Gruppen (je 40, eng und Loch in Loch, leicht und mittel):
    Schusszahl 95 % (vorher 80 %), alle Ringe 69 % (vorher 33 %), unbemerkt falsch 0 %. Einzelne
    Löcher liegen meist auf 0,03–0,1 mm genau; Fehler kommen fast nur aus dichten Gruppen auf
    dunkler Unterlage (dann „bitte prüfen“). Die Mitte der Scheibe findet die Erkennung auf
    etwa 0,06 mm. Etwa 0,7 s je Foto (höchstens 3 s).
  - **Live-Kamera** (Schritt 5): „Live-Kamera“ zeigt das Kamerabild mit Rahmen (rot, bis
    die Lage passt, dann grün) und Hinweisen (näher heran, weiter weg, in die Mitte, gerade
    von oben, ruhig halten, mehr Licht). Jedes Bild wird im Browser verkleinert geprüft
    (`aim.ts`: Spiegel suchen, Lage, Rundheit als Maß für Schräge, Schärfe); nach sechs
    guten, ruhigen Bildern hintereinander löst die Kamera aus und nimmt das schärfste davon
    in voller Auflösung. „Jetzt auslösen“ geht immer. Braucht HTTPS und die Kamerafreigabe
    des Browsers; sonst bleibt „Foto der Scheibe“.
  - Grenzen: Ein Loch im Schwarzen auf dunkler Unterlage ist kaum zu sehen; die Scheibe also
    auf eine helle Unterlage legen oder gegen das Licht halten. Echte Fotos können anders
    aussehen als die künstlichen; die Werte zeigen nur, ob die Erkennung besser oder
    schlechter wird.
  - **Summe gegen Foto prüfen** (Schritt 6): Auch bei „Nur die Summe eingeben“ gibt es
    „Foto der Scheibe“. Das Foto wird nur zum Vergleich ausgewertet: „Foto zum Vergleich:
    46 Ringe“ steht neben der Eingabe, eine Abweichung wird markiert, und vor dem Speichern
    fragt HUBIplan nach („Weicht vom Foto ab“). Gespeichert wird die eingegebene Summe;
    „Treffer ansehen“ wechselt zum Antipp-Bild mit den erkannten Treffern.
  - **Spiegelausschnitte sammeln** (Schritt 6, nur mit Einwilligung des Vereins): Es gibt
    keine ausgewerteten echten Scheiben. Unter Einstellungen › Datenschutz › „Fotoerkennung verbessern“ kann
    der Verein (Recht Wettbewerbe verwalten) erlauben, dass bestätigte Spiegel gesammelt
    werden; standardmäßig aus. Beim Foto wird je Spiegel der entzerrte Ausschnitt (Graubild,
    12 Bildpunkte je mm) höchstens 12 Stunden im Cache bereitgelegt, das Gerät bekommt nur
    einen Schlüssel. Erst beim Speichern der bestätigten Treffer kommt der Ausschnitt mit den
    bestätigten und den erkannten Trefferpunkten in die Tabelle `PhotoSample`: ohne Starter,
    Wettbewerb, Uhrzeit oder Namen (nur Tag des Sammelns). Ausschalten löscht nichts; „Alle
    Ausschnitte löschen“ löscht sofort alle des Vereins. Beides steht im Änderungsprotokoll.
    `manage.py scheiben_ausschnitte <ordner>` gibt die Ausschnitte (aller einwilligenden
    Vereine) mit Lösung aus, zum Prüfen und Verbessern der Erkennung; nicht ins Repository.

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

## Auszeichnungen und Geschichte (Schritt 4)

- **Auszeichnungen** (`<id>/awards/`): je Wertung für Platz *a* bis *b* oder beim Vogelschießen
  je Pfand: Titel ohne Jahr („Vereinsmeister“, angezeigt „Vereinsmeister 2027“), Preis (Pokal,
  Medaille), Würde (Vorschlag), Wanderpokal. Kopie aus dem Vorjahr übernimmt sie mit.
- **Vergabe** beim Setzen auf „endgültig“ (`AwardGrant`, mit Name als Text, Mitglied,
  Untereinheit bei der Zugwertung, Platz, Wert). Geht der Wettbewerb zurück (Korrektur), fallen
  die noch offenen Vergaben weg; „Neu vergeben“ (`<id>/grant/`) nach Änderungen.
- **Würdenvorschlag:** Die Vergabe schlägt die Würde vor; erst „Würde eintragen“
  (`grants/<pk>/dignity/` mit `decision=bestaetigen|ablehnen`) legt die Regentschaft an
  (Jahr des Wettbewerbs, Herkunft = Untereinheit des Starters). Bestätigen braucht zusätzlich
  „Mitglieder bearbeiten“. Entschiedene Vorschläge bleiben bei einer Korrektur stehen.
- **Reihen** (`series/`): verbinden denselben Wettbewerb über die Jahre. `series/<id>/` liefert
  das Archiv: Sieger (Plätze 1–3) je Jahr und Wertung, Titel, Bestenliste (nur Jahre mit
  gleicher Bezeichnung, Einheit, Zahl gewerteter Schüsse, Wertungsart und Mannschaftsgröße),
  Plätze der Untereinheiten über die Jahre.
- **Wanderpokale** (`trophies/`): Inhaber über die Jahre, „in den Besitz nach *n* Siegen in
  Folge“ (gleicher Träger mehrmals hintereinander).
- **Frühere Jahre** (`grants/` POST, `manual`): Jahr, Titel oder Pokal, Mitglied oder Name,
  optional Platz und Reihe; auch nur „Sieger je Jahr“.
- **Mitgliedsakte**, Reiter „Wettbewerbe“ (`member/<membership>/`, Recht „Mitglieder
  ansehen“): Starts mit Platz und Wert, Titel und Auszeichnungen. Mitglieder-Export: Spalte
  „Wettbewerbstitel“ („Vereinsmeister: 2019, 2023“).
- Seitenleiste: Wettbewerbe › Reihen, Wanderpokale, Titel und Würden.

## Webseite und Mitgliederbereich (Schritt 5)

- Je Wettbewerb **Auf der Webseite**: nicht, live während des Wettbewerbs (ab „läuft“, mit
  Vermerk live bzw. vorläufig) oder nach Abschluss (erst „endgültig“), dazu der **Umfang**: nur
  Wertung der Untereinheiten und Mannschaften, Plätze 1 bis 3 mit Namen, ganze Rangliste.
- Baustein **„Ergebnisse“** (Webseite › Menü und Bereiche, nur mit Modul Wettbewerbe) und Block
  **„Aktuelle Ergebnisse“** auf der Startseite (die drei neuesten mit Plätzen 1 bis 3; aus,
  bis die Einheit ihn unter Menü und Bereiche › Startseite einschaltet).
- Öffentliche Schnittstelle (`website/results.py`): `results/` (Wettbewerbe, Reihen mit
  „Archiv auf der Webseite“, Wanderpokale mit „Inhaber auf der Webseite“), `results/?start=1`
  (Startseite), `results/<Kennung>/` (Rangliste), `results/<Kennung>/version/` (kleiner Stand),
  `results/series/<Kennung>/` (Sieger je Jahr, Titel). Laufende Wettbewerbe mit
  `Cache-Control: max-age=5`; die Seite fragt live alle 15 Sekunden den Stand ab (Ralf
  2026-11-01) und lädt die Tabelle nur bei einer Änderung.
- **Namen** im Namensformat der Webseite. Einwilligungen: „Wettbewerbsergebnisse“
  (Widerspruch, wie Würden) und „Wettbewerbsergebnisse unter 18“ (Einwilligung; maßgeblich ist
  das Alter am Wettbewerbstag). Ohne Erlaubnis steht „ohne Namen“, der Platz bleibt. Gäste
  erscheinen mit Namen und Verein. Der Datenschutztext der Webseite nennt Ergebnisse, sobald der
  Baustein an ist.
- **Mitgliederbereich** „Meine Ergebnisse“ (`/api/portal/<Zugang>/results/`, auch für die
  App): eigene Starts (ohne Vorbereitung) mit Platz und Wert, Titel und Auszeichnungen.

## Ausgaben

`export/?als=`: `pdf` (Ergebnisliste mit Kennzahlen, beim Vogelschießen die Pfänderliste),
`xlsx`, `schiessliste` (`sortierung=name|einheit|nummer`, `leerzeilen=`, `leer=1` für eine
Liste ohne Namen), `stechliste&stechen=<id>`, beim Vogelschießen `losliste` (nach Losnummer
mit Feld für Striche) und `pfaenderliste` (leer zum Ausfüllen). Schieß- und Losliste füllen
die letzte Seite mit leeren Zeilen auf (mindestens `leerzeilen`); die leere Schießliste ist
genau eine volle Seite.

## Daten

App `competitions`, Tabellen mit `organization` und RLS. Export und Datenübernahme
enthalten alles (mitgliederbezogen, auch die Treffer) außer den gesammelten
Spiegelausschnitten und der Einwilligung dazu (`PhotoSample`, `PhotoSampleConsent`; nur für
die Fotoerkennung, ohne Bezug zu Personen); die Wettbewerbe kommen nach den Terminen (Verweis). Keine Dateifelder.
