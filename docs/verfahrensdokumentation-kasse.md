# Verfahrensdokumentation: Kasse und Quittungen in HUBIplan

Diese Beschreibung ist die Vorlage für die Verfahrensdokumentation eines Vereins nach den
GoBD (BMF-Schreiben zu den Grundsätzen ordnungsmäßiger Führung und Aufbewahrung von Büchern,
Aufzeichnungen und Unterlagen in elektronischer Form). Jeder Verein ergänzt die Angaben in
Abschnitt 6 (wer, wo, wie oft) und lässt sie vom Vorstand bestätigen. Sie ersetzt keine
steuerliche Beratung.

## 1. Zweck und Umfang

HUBIplan führt die Kasse der Einheit (Einnahmen-/Ausgabenrechnung): Konten (Bank, Barkasse,
Sparkonto), Kategorien, Buchungen mit Belegen, Jahresabschluss und Kassenbericht. Dazu
kommen Rechnungen und Zahlungen (Beiträge), Quittungen mit Unterschrift auf dem
Bildschirm, Kontoauszüge (CAMT.053) und – nur bei Einheiten mit dem Schalter
„steuerbegünstigt mit eigenem Bescheid“ – Zuwendungsbestätigungen.

Nicht Teil davon: Registrierkasse für Verkäufe (dafür braucht es ein Kassensystem mit
technischer Sicherheitseinrichtung nach § 146a AO), Lohnbuchhaltung. Die Vorlage der
Zuwendungsbestätigung folgt dem amtlichen Muster; ihre rechtliche Freigabe bleibt beim
Vorstand bzw. der steuerlichen Beratung.

## 2. Beteiligte und Rechte

- Buchen und Quittungen ausstellen: Rollen mit dem Recht `finance.edit` (Kassierer, auch
  Kassierer einer Untereinheit mit eigener Kasse).
- Lesen: `finance.view` (z. B. Kassenprüfer).
- Abschluss aufheben: zusätzlich Rollenverwaltung (Vorstand), nur mit Grund. Der bisherige
  Stand (Bestände und Summen) bleibt mit Zeitpunkt, Person und Grund erhalten; nach dem
  erneuten Abschluss zeigt HUBIplan die Änderungen gegenüber diesem Stand.
- Eine Einheit mit Buchungen, Rechnungen, Quittungen, Zuwendungen, Kontoauszügen oder
  Jahresabschlüssen (auch nur zugeordneten Buchungen des Vereins) lässt sich nicht löschen,
  nur auf inaktiv setzen.
- Jede Änderung steht mit Person, Zeitpunkt und Weg (Browser oder App mit Gerätename) im
  Änderungsprotokoll. Die Einträge sind je Einheit **verkettet**: Jeder trägt eine laufende
  Nummer, die SHA-256-Prüfsumme seines Vorgängers und eine eigene Prüfsumme über alle
  Angaben. Wird ein Eintrag direkt in der Datenbank geändert, gelöscht oder eingeschoben,
  bricht die Kette. HUBIplan prüft sie täglich und meldet einen Bruch per Mail an die
  Betreiber; unter Einstellungen › Änderungsprotokoll steht das Ergebnis und lässt sich die
  Prüfung von Hand starten. Nach der Löschfrist (Datenschutz) werden Inhalte geleert, ohne
  die Kette zu brechen; solche Einträge werden gezählt.

## 3. Buchungen

- Jede Buchung bekommt beim Anlegen die nächste Buchungsnummer des Geschäftsjahres
  (`2026-0001`, fortlaufend, gesperrt gegen doppelte Vergabe). Eine Lücke entsteht nur,
  wenn eine Buchung am Tag ihrer Erfassung gelöscht wird; das steht im Änderungsprotokoll.
- **Festschreibung:** Eine Buchung ist festgeschrieben, sobald der Folgemonat ihres Datums
  vorbei ist (am 1. Mai alles bis Ende März). Nachträglich erfasste Buchungen bleiben bis
  zum Ende des Folgemonats ihrer Erfassung änderbar. Unter Abschluss & Berichte lässt sich
  die Kasse zusätzlich von Hand bis zu einem Tag festschreiben; das ist endgültig.
  Festgeschriebene Buchungen lassen sich nicht mehr ändern (nur die Zuordnung zu einer
  Veranstaltung) und nicht neu nummerieren.
- **Löschen** geht nur am Tag der Erfassung. Danach wird **storniert** (mit Pflicht-Grund):
  Eine Gegenbuchung mit heutigem Datum hebt die Buchung auf und verweist auf sie; beide
  bleiben unverändert sichtbar. Ein Storno geht auch für Buchungen abgeschlossener Jahre
  (die Gegenbuchung liegt im laufenden Jahr). Wird eine Zahlung zu einer Rechnung nach dem
  Tag ihrer Erfassung entfernt, wird ihre Buchung ebenso storniert.
- Belege (Fotos, PDFs) hängen an der Buchung und liegen privat auf dem Server. Löschen
  lässt sich ein Beleg nur 15 Minuten nach dem Hochladen durch dieselbe Person (Fehlgriff);
  danach wird er mit Grund **ausgeblendet**: Die Datei bleibt gespeichert und steht im
  Datenexport.
- Eine **Barkasse** kann an keinem Tag unter null fallen: Buchungen, Änderungen und
  Löschungen, die das bewirken würden, werden abgelehnt (Kassensturzfähigkeit).
- Bargeld wird zeitnah erfasst, möglichst am selben Tag (Vereinsregel, Abschnitt 6).
- **Jahresabschluss** sperrt das Geschäftsjahr: danach keine Änderung, kein Löschen, kein
  Neunummerieren und keine neuen Buchungen. Korrekturen laufen als Storno bzw. neue Buchung
  im offenen Jahr.

## 3a. Barkasse: Zählprotokoll und Kassenbericht (zuschaltbar)

Unter Finanzen › Einrichtung › Konten lässt sich „Zählprotokoll und Kassenbericht für Feste“
einschalten (je Einheit). Danach gibt es den Unterpunkt **Kassenzählung**:

- **Zählprotokoll (Kassensturz):** Bargeld nach Scheinen und Münzen zählen; HUBIplan
  vergleicht mit dem Bestand laut Kassenbuch am Ende des Tages. Eine Differenz braucht einen
  Grund und eine Kategorie und wird als Buchung „Kassendifferenz“ erfasst.
- **Kassenbericht für Feste (offene Ladenkasse):** Ohne Registrierkasse wird die
  Tageseinnahme rückwärts ermittelt: gezählter Endbestand − Anfangsbestand (Wechselgeld) +
  bar bezahlte Ausgaben + Entnahmen (§ 146 Abs. 1 AO, Anwendungserlass zu § 146). Sie wird je
  Kategorie (z. B. Getränke, Eintritt) als Einnahme gebucht; die Aufteilung muss genau
  aufgehen. Ausgaben und Entnahmen werden wie gewohnt einzeln gebucht.
- Beide halten fest, wer gezählt hat (empfohlen: zweite Person), werden als PDF mit
  Prüfsumme abgelegt, hängen als Beleg an den Buchungen und lassen sich danach nicht mehr
  ändern. Im Datenexport stehen sie in `kassenzaehlungen.csv` mit den PDFs.

## 3b. DATEV-Export für die Steuerberatung (zuschaltbar)

Unter Finanzen › Einrichtung › Konten lässt sich der DATEV-Export einschalten (je Einheit),
mit Berater- und Mandantennummer, Sachkontenlänge und Kontenrahmen. Jedes Konto bekommt ein
DATEV-Finanzkonto (z. B. 1200 Bank, 1000 Kasse), jede Kategorie ein Sachkonto. Unter
Abschluss & Berichte › Jahresabschluss gibt es dann je Geschäftsjahr den Buchungsstapel
(EXTF, Version 700, Windows-1252):

- Einnahme: Finanzkonto im Soll an das Sachkonto der Kategorie,
- Ausgabe: Finanzkonto im Haben an das Sachkonto der Kategorie,
- Umbuchung: Zielkonto im Soll an das Ausgangskonto,
- Belegfeld 1 ist die Buchungsnummer, Belegfeld 2 die Belegnummer/Referenz.

Stornos gehen als normale Gegenbuchungen hinüber. Fehlt einem verwendeten Konto oder einer
Kategorie das DATEV-Konto, nennt HUBIplan sie, statt eine unvollständige Datei zu liefern.

## 3c. Rücklagen nach § 62 AO (zuschaltbar)

Unter Finanzen › Einrichtung › Konten lässt sich „Rücklagen führen“ einschalten (je Einheit).
Unter Finanzen › Rücklagen werden Rücklagen angelegt (Projektrücklage, Wiederbeschaffungs-
rücklage, freie Rücklage, sonstige); Projekt- und Wiederbeschaffungsrücklagen brauchen einen
konkreten Zweck. Eine Rücklage bewegt kein Geld, sie bindet einen Teil der Mittel:

- **Zuführung** und **Auflösung** mit Datum, Betrag und Begründung (z. B. Vorstandsbeschluss);
  sie gehören zum Geschäftsjahr ihres Datums und sind nach dessen Abschluss gesperrt.
- Eine Rücklage fällt nie unter null; mit Bewegungen lässt sie sich nur archivieren.
- Die Seite zeigt die Mittel auf allen Konten, die gebundenen Rücklagen und den frei
  verfügbaren Rest. Die Höchstgrenze der freien Rücklage (§ 62 Abs. 1 Nr. 3 AO) prüft der
  Verein selbst.
- Im Datenexport stehen sie in `ruecklagen.csv` (Stand zu Beginn, Bewegungen, Stand am Ende).

## 3d. Rechnungen, Zuwendungsbestätigungen, Kontoauszüge

- **E-Rechnungen** (XRechnung als UBL oder CII, ZUGFeRD/Factur-X als PDF mit eingebettetem
  XML) lassen sich als Beleg anhängen. Die Datei wird unverändert aufbewahrt; HUBIplan liest
  Rechnungsnummer, Datum, Rechnungssteller, Beträge und Positionen aus und zeigt sie an.
  Reines XML wird nie im Browser geöffnet, sondern heruntergeladen; dazu gibt es eine
  lesbare Ansicht als PDF (maßgeblich bleibt das XML). Bei einer neuen Ausgabe füllt
  „E-Rechnung einlesen“ Datum, Betrag, Empfänger, Belegnummer und Text vor und hängt die
  Datei beim Buchen als Beleg an. XML-Dateien mit DTD oder ohne E-Rechnung werden abgelehnt.

- **Rechnungen** werden beim ersten Versand oder Abruf als PDF abgelegt (mit Prüfsumme).
  Danach gilt immer diese Fassung, auch wenn sich Briefkopf oder Bankverbindung ändern.
  Restcents bei Raten gehen auf die ersten Raten, damit der Jahresbetrag genau stimmt.
- **Zuwendungsbestätigungen** bekommen eine fortlaufende Nummer je Jahr; das PDF wird beim
  Ausstellen mit Prüfsumme abgelegt, eine Stornierung behält das Original. Ausgestellt wird
  nur mit vollständigem Namen und Anschrift des Zuwendenden.
- **Kontoauszüge** (CAMT.053) werden mit Fingerabdruck je Umsatz eingelesen (keine doppelten
  Umsätze, gleiche Umsätze im selben Auszug bleiben getrennt), Sammelbuchungen behalten ihre
  Einzelposten. Eine zugeordnete Buchung lässt sich in Betrag, Art und Konto erst nach dem
  Lösen der Zuordnung ändern; wird sie gelöscht, ist der Umsatz wieder offen. Die
  Originaldatei der Bank wird unverändert mit SHA-256 aufbewahrt; ein Auszug lässt sich nur
  löschen, solange aus ihm nichts gebucht oder zugeordnet ist.
- **Bestand** heißt Bestand heute; Buchungen mit Datum in der Zukunft stehen getrennt als
  „vorgemerkt“.

## 4. Quittungen mit Unterschrift

Ablauf:

1. Der Kassierer bereitet die Quittung vor: Richtung (Verein erhält / zahlt aus), Gegenseite,
   Betrag, Zweck, Barkasse, Kategorie, bei Bedarf Umsatzsteuersatz.
2. Der Kassierer unterschreibt (oder seine hinterlegte Unterschrift wird eingesetzt). Die
   Gegenseite unterschreibt im Vollbild auf dem Gerät des Kassierers; über dem Feld steht,
   was sie bestätigt („Ich habe 120,50 € von … erhalten. Zweck: …“). Erhält der Verein Geld
   und will der Zahler nicht unterschreiben, ist eine Begründung Pflicht. Bei Auszahlungen
   unterschreibt der Empfänger immer.
3. Ändern sich Richtung, Name, Betrag, Zweck oder Steuersatz, werden beide Unterschriften
   gelöscht.
4. **Abschluss** (nur durch die Person, die als Kassierer unterschrieben hat, nach
   ausdrücklicher Bestätigung) in einem Schritt: Buchung im Kassenbuch, **Belegnummer =
   Buchungsnummer**, Datum = Tag der Unterschrift, PDF wird erzeugt, als Beleg an die Buchung
   gehängt und mit Prüfsumme (SHA-256) im Änderungsprotokoll festgehalten.
5. Danach sind Quittung, Buchung und PDF nicht mehr änderbar oder löschbar. Das
   Neunummerieren eines Jahres mit Quittungen ist gesperrt, damit die Belegnummer auf dem PDF
   gültig bleibt.
6. **Storno** (mit Pflicht-Grund, nur im offenen Geschäftsjahr): Gegenbuchung im laufenden
   Jahr und zusätzliches PDF mit Storno-Vermerk; die ursprüngliche Quittung bleibt erhalten.
   War die Quittung eine Barzahlung zu einer Rechnung, ist die Rechnung danach wieder offen.

Gespeichert wird von einer Unterschrift nur die Form der Linien (keine Zeit-, Druck- oder
Geschwindigkeitswerte), dazu Name und Zeitpunkt. Die Unterschrift ist eine einfache
elektronische Signatur.

In der Android-App darf offline unterschrieben werden; der Abschluss mit Belegnummer folgt,
sobald Netz da ist, höchstens 30 Tage nach der Unterschrift.

## 5. Aufbewahrung, Sicherung, Prüfung

- Aufbewahrungsfrist für Buchungsbelege: 8 Jahre (§ 147 AO in der Fassung ab 2025),
  Bücher und Jahresabschlüsse 10 Jahre, jeweils ab dem Ende des Kalenderjahres, in dem das
  Geschäftsjahr endet. HUBIplan löscht nichts von selbst. Nach Ablauf zeigt Abschluss &
  Berichte › Jahresabschluss beim abgeschlossenen Jahr „Belege löschen“ (ab dem 9. Jahr:
  Belegdateien, archivierte Rechnungs-, Quittungs-, Zuwendungs- und Zählprotokoll-PDFs,
  Kontoauszugs- und SEPA-Dateien, Unterschriften) bzw. „Daten bereinigen“ (ab dem 11. Jahr
  zusätzlich: Namen, Anschriften, Buchungstexte und Bankdaten werden anonymisiert). Beträge,
  Daten, Konten, Kategorien und Nummern bleiben, damit Bestände stimmen. Auslösen dürfen nur
  Vorstände mit Rollenverwaltung; ein so bereinigtes Jahr lässt sich nicht mehr aufheben.
  Vorher den Datenexport prüfen, falls eine Betriebsprüfung oder ein Verfahren läuft
  (solange Steuern dieser Jahre noch festgesetzt werden können, läuft die Frist nicht ab, § 147 Abs. 3 AO).
- Tägliches verschlüsseltes Backup mit Rücksicherungstest (siehe [betrieb.md](betrieb.md));
  ein zweiter Sicherungsort außerhalb des Servers ist einzurichten (Abschnitt 6).
- **Datenexport für eine Prüfung:** Finanzen › Abschluss & Berichte › Jahresabschluss ›
  „Datenexport (ZIP)“ je Geschäftsjahr:
  - Kasse: `buchungen.csv` (mit Storno-Verweisen und Kennzeichen „festgeschrieben“),
    `konten.csv`, `quittungen.csv` (mit Prüfsummen), alle Belege (auch ausgeblendete, mit Grund);
  - Beiträge: `rechnungen.csv` und `rechnungsposten.csv` mit den archivierten Rechnungs-PDFs,
    `zahlungen.csv`, `mahnungen.csv`, `lastschriften.csv` und `lastschriftposten.csv` mit den
    SEPA-Dateien;
  - Spenden: `zuwendungen.csv`, `zuwendungsbestaetigungen.csv` mit den PDFs (auch stornierte);
  - Bank: `kontoauszuege.csv` mit den Originaldateien, `kontoumsaetze.csv`;
  - Barkasse: `kassenzaehlungen.csv` mit den PDFs der Zählprotokolle und Kassenberichte;
  - Rücklagen: `ruecklagen.csv` (wenn geführt);
  - `protokoll.csv`: Änderungsprotokoll der Finanzdaten ab Beginn des Geschäftsjahres, mit
    laufender Nummer und Prüfsummen; `protokollpruefung.txt`: Ergebnis der Kettenprüfung und
    Prüfsumme des letzten Eintrags (mit dem Export archivieren);
  - `abschluss.json` (Stand des Jahresabschlusses, falls vorhanden), `index.xml` nach dem
    Beschreibungsstandard für die Datenträgerüberlassung (für IDEA und ähnliche
    Prüfprogramme), `LIESMICH.txt` und `pruefsummen.txt` (SHA-256 jeder Datei).

  Alle Tabellen: Semikolon, UTF-8, Dezimalkomma, Datum TT.MM.JJJJ. Damit sind die Daten
  maschinell auswertbar (Datenträgerüberlassung nach § 147 Abs. 6 AO).
- Prüfen eines Quittungs-PDFs: SHA-256 der Datei mit der Spalte in `quittungen.csv` bzw. dem
  Eintrag im Änderungsprotokoll vergleichen.

## 6. Vom Verein auszufüllen

| Punkt | Angabe |
|---|---|
| Verantwortlich für die Kasse | |
| Wer stellt Quittungen aus (Rollen) | |
| Bargeld wird erfasst | z. B. am selben Tag, spätestens nach … Tagen |
| Kassensturz (Zählen der Barkasse) | z. B. monatlich und zum Jahresende, mit Zählprotokoll |
| Zweiter Sicherungsort | |
| Datenexport für das Archiv | z. B. nach jedem Jahresabschluss, abgelegt bei … |
| Bestätigt durch den Vorstand am | |
