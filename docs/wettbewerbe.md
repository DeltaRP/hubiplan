# Wettbewerbe

Eigene Schießen und andere Wettbewerbe mit Einzel- und Zugwertung, Stechen, Auswertung,
Druckvorlagen und einem Standmodus für Tablet und Handy. Konzept im Projektordner
(`konzepte/wettbewerbe.md`); dies ist Schritt 1 (Preisschießen).

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
- Vorlage beim Anlegen: „Schießen mit Einzel- und Zugwertung“ (5 Schuss, 3 gewertet, 10
  Preisplätze; Zug: beste 5, 3 Preisplätze).

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
  auf dem Handy Speichern am unteren Rand.
- **Offline:** Starterliste und Mitgliederliste (`members/`) liegen auf dem Gerät
  (localStorage). Eingaben gehen in eine Warteschlange und werden über `sync/` nachgereicht
  (neue Starter mit Gerätekennung `client_key`, daher nichts doppelt). Ist ein Wert auf dem
  Server später geändert worden, gilt der spätere und der Standmodus zeigt es an. Neu laden
  ohne Netz folgt mit dem Standmodus für das Vogelschießen (Schritt 2b).

## Ausgaben

`export/?als=`: `pdf` (Ergebnisliste mit Kennzahlen), `xlsx`, `schiessliste`
(`sortierung=name|einheit|nummer`, `leerzeilen=`, `leer=1` für eine Liste ohne Namen),
`stechliste&stechen=<id>`.

## Daten

App `competitions`, Tabellen mit `organization` und RLS. Export und Datenübernahme
enthalten alles (mitgliederbezogen). Keine Dateifelder.
