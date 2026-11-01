# Konzept – Kurzfassung

Das vollständige Konzept steht im Konzeptdokument:
**[Konzept Vereinsverwaltung](https://claude.ai/artifact/U3Uyzy1yLiXfe4NKztqkvA)**.
Diese Datei fasst die Punkte zusammen, die für die Architektur des Codes wichtig sind.
Bei Abweichungen gilt das Konzeptdokument.

## Ziel

Webbasierte Vereinsverwaltung für jede Vereinsart, von 10 bis 10.000 Mitgliedern.
Responsiv für Smartphone, Tablet und Laptop; dazu eine Android-App (Repository
`hubiplan-android`, Beschreibung in [app.md](app.md)) und eine Vereinswebseite aus
HUBIplan-Daten (Repository `hubiplan-website`).

> **Historischer Stand:** Die Abschnitte „Ebenen“ und „Meilensteine Phase 1“ beschreiben den
> Start (Phase 1: nur Vorstände und Plattform, Mitglieder ohne Login, App „später“). Das ist
> überholt. Maßgeblich für den heutigen Umfang ist der folgende Abschnitt
> (UX-Audit 31.10.2026, F01).

## Funktionsumfang heute (Stand 31.10.2026)

Gepflegt von Ralf Philipsen; bei jeder neuen Funktion hier eine Zeile ergänzen.

| Bereich | Wer arbeitet damit | Inhalt |
| --- | --- | --- |
| Mitglieder | Vorstand, Mitgliederverwaltung | Akte mit Zeiträumen, Mitgliedsarten, Ehrungen/Würden, Jubiläen, Import/Export, Aufnahme, Änderungsanträge, Fotos, Ausweis |
| Untereinheiten | Vorstand, Verantwortliche der Einheit | frei verschachtelbare Einheiten (z. B. Züge, Abteilungen) mit eigenen Rollen, Kasse und Webseite |
| Termine | Vorstand, Mitglieder | Kalender, Zu-/Absagen bei einmaligen Terminen, Kalender-Abo |
| Dokumente | Vorstand, je nach Ordnerfreigabe Mitglieder | Ablage, Satzung |
| Meldungen | Vorstand | Mannschaften, Personen und Angaben an Veranstalter melden (Brief, E-Mail, Tabelle), Fassungen und Änderungsmeldungen, fremder Wettbewerb aus der Meldung |
| Rundschreiben | Vorstand | Mail/Brief/App an Mitglieder, Vorstände, Rolleninhaber; Abbestellen nur für „Information“ |
| Webseite | Vorstand, Webseitenpflege | Inhalte, Startseiten-Bausteine, Instagram/Facebook-Beiträge, Impressum/Datenschutz |
| Finanzen | Kassierer, Kassenprüfer | Beiträge/Rechnungen, Mahnungen, Kasse, Quittungen, Kontoauszüge (CAMT), Zuwendungsbestätigungen, Abschlüsse |
| Mein Bereich | jedes Mitglied mit Zugang | Ausweis, Rechnungen, Rundschreiben, eigene Daten |
| Einstellungen | Vorstand | Rollen, Erscheinungsbild, Briefvorlage, Verbund mit anderen Instanzen |
| Plattform | Plattform-Administration | Vereine/Dachverbände anlegen, Module freischalten |
| Android-App | Mitglieder, Vorstand, Kassierer | Ausweis, Termine, Rundschreiben, Verwaltung und Quittungen vor Ort |

## Ebenen

| Ebene | Rolle |
| --- | --- |
| **Plattform** | die installierte Instanz; legt Dachverbände und Vereine an, schaltet Module frei, sieht im Normalbetrieb keine Mitgliedsdaten |
| **Dachverband** (optional) | eigener Vorstand, eigene Benutzer, eigenes Erscheinungsbild; Zugriff auf Mitgliedsdaten seiner Vereine nur, wenn die Plattform ihn freischaltet (aus / lesen / lesen und ändern) |
| **Verein** | verwaltet seine Mitglieder selbst, mit eigenem Vorstand, eigenen Rollen, Farben und Logo; gehört höchstens einem Dachverband an |

Fehlt der Dachverband, hängt der Verein direkt unter der Plattform.
Technisch: **eine** mandantenfähige Anwendung mit **einer** Datenbank; jeder Datensatz
gehört zu einer Organisation (Typ Plattform, Dachverband, Verein, später Abteilung).

## Benutzer, Rollen und Rechte je Organisation

- **Berechtigungen** sind feste Bausteine der Software, nach Modulen gegliedert
  (z. B. „Mitglieder lesen“, „Mitglieder bearbeiten“, „Rollen verwalten“,
  „Theme ändern“, „Exportieren“). Neue Module bringen eigene Berechtigungen mit.
- **Rollen** gehören zu genau einer Organisation; Name und Berechtigungen legt die
  Organisation selbst fest (z. B. „Kassierer“ im Verein A).
- Rollenzuordnungen haben ein **Von-/Bis-Datum** – daraus entsteht die Historie.
- Ein **Benutzerkonto** (Login: E-Mail + Passwort, optional 2FA per TOTP) ist getrennt
  vom **Mitgliedsdatensatz** (Person). Ein Konto kann Rollen in mehreren Organisationen
  haben; nach dem Login wählt man, in welcher Organisation man arbeitet.

## Mitgliedschaft mit Zeiträumen und Mitgliedsarten

- **Person** und **Mitgliedschaft** werden getrennt gespeichert. Mitgliedschaft wird
  vom Verein aus gedacht: Mitglied im Dachverband wird man nur über einen seiner Vereine.
- Eine Mitgliedschaft (Person in einem Verein) besteht aus einem oder mehreren
  **Zeiträumen** (Eintritt, Austritt, Grund). Ein Wiedereintritt legt einen neuen
  Zeitraum an und überschreibt nichts. Zeiträume bleiben auch nach der Löschfrist erhalten.
- Jeder Verein definiert seine **Mitgliedsarten** selbst (aktiv, passiv, Ehrenmitglied …).
  Jede Art hat drei Kennzeichen:

  | Kennzeichen | Bedeutung |
  | --- | --- |
  | **an Dachverband melden** | Mitgliedschaften dieser Art zählen für den Dachverband |
  | **aktiv** | gilt als aktive Mitgliedschaft – eine Person darf im Dachverband nur in **einem** Verein aktiv sein |
  | **zählt für Mitgliedsdauer** | Zeiten dieser Art zählen für die Dauer im Verein |

- Die Mitgliedsart hängt mit **Von-/Bis-Datum** an der Mitgliedschaft; ein Wechsel
  beendet die alte Art am Vortag, der Zeitraum läuft weiter.
- Die erste **gemeldete** Mitgliedschaft macht die Person zum Dachverbandsmitglied und
  vergibt die Verbandsmitgliedsnummer. Endet die letzte gemeldete Mitgliedschaft, endet
  auch die Dachverbandsmitgliedschaft.
- **Dauer**: im Verein = Summe der zählenden Zeiträume; im Dachverband = Vereinigung
  aller gemeldeten Zeiträume (Überschneidungen zählen einmal), nach der Regel des
  Dachverbands („alle gemeldeten Zeiten“ oder „nur gemeldete aktive Zeiten“).

## Datentrennung: Datenbank-Zeilenschutz (RLS) je Organisation

Alle Organisationen teilen sich eine PostgreSQL-Datenbank. Die Trennung ist doppelt
gesichert:

1. Jeder Datensatz trägt seine Organisation; die Anwendung filtert jede Abfrage danach.
2. Zusätzlich sperrt PostgreSQL selbst den Zugriff auf fremde Zeilen per
   **Row-Level Security**. Die Anwendung setzt je Anfrage die aktive Organisation
   (z. B. als Sitzungsvariable), und die RLS-Regeln lassen nur passende Zeilen durch.
   Ein Programmierfehler führt so nicht zu einem Datenleck.

Der Zugriff eines Dachverbands auf Vereinsdaten läuft über eine eigene, protokollierte
Freigabe der Plattform. Umgesetzt wird RLS in Meilenstein 1.

## Mitgliedsausweis mit QR-Code

Jede Mitgliedschaft kann einen digitalen Mitgliedsausweis bekommen. Der QR-Code enthält
nur einen Link mit einem zufälligen, nicht erratbaren Schlüssel, keine Mitgliedsnummer.

- **Seite nach dem Scan** (ohne Anmeldung): Name, Foto (nur mit Foto-Einwilligung),
  Status („Gültige Mitgliedschaft“ bzw. „Keine gültige Mitgliedschaft“), Mitgliedsart,
  Verein, Abteilung und Dachverband sowie „Stand: Datum, Uhrzeit“. Ehemalige Mitglieder
  zeigen nur Name und Status, ohne Foto und Abteilung. Nach Ablauf der Löschfrist, bei
  gesperrtem oder ersetztem Code erscheint „ungültig“.
- **Recht „Mitgliedsausweise erstellen und sperren“** (Verein, Dachverband) bzw. für
  Abteilungsrollen (nur Mitglieder der Abteilung). Vorstandsrollen bekommen es automatisch.
- **Verwaltung** in der Mitgliedsakte: QR-Code erzeugen, neu erzeugen (alte Ausdrucke
  ungültig), sperren und wieder freigeben. Alles steht im Änderungsprotokoll.
- **PDF zum Drucken**: Scheckkartenformat, 10 Ausweise je A4-Seite, für ein Mitglied, die
  aktuelle Auswahl der Mitgliederliste, eine Abteilung oder alle Mitglieder eines
  Dachverbands (nur mit Plattform-Freigabe). Gesperrte Ausweise werden nicht gedruckt.
- **Mitgliederbereich**: Mitglieder sehen ihren eigenen Ausweis und können ihn als PDF laden.

## Erscheinungsbild

Jede Organisation setzt Logo und Farben (mindestens Primär- und Akzentfarbe, mit
Lesbarkeitsprüfung). Ohne eigene Einstellungen erbt ein Verein vom Dachverband, sonst von
der Plattform. Im Frontend sind die Farben CSS-Variablen (`frontend/src/theme/`).

## Technik

Django (LTS) + Django REST Framework mit OpenAPI, React + TypeScript, PostgreSQL,
Celery + Redis für Hintergrund-Jobs, Docker Compose. Versionen sind festgeschrieben,
Dependabot meldet Updates und Sicherheitslücken.

## Meilensteine Phase 1

| Nr. | Meilenstein | Inhalt |
| --- | --- | --- |
| 0 | Grundgerüst | Django/React, Docker, Tests und Sicherheits-Scan, Anmeldung mit 2FA |
| 1 | Organisationen und Rechte | Ebenen, Rollen, Berechtigungen, Organisation wechseln, Erscheinungsbild, RLS |
| 2 | Mitglieder: Kern | Person, Mitgliedschaft mit Zeiträumen, Mitgliedsarten, Liste und Akte, Dublettenprüfung, Protokoll |
| 3 | Abläufe | Art wechseln, Austritt, Wiedereintritt, Wechselanfrage, Archiv und Löschfrist |
| 4 | Zusatzfelder und Dauer | freie und wiederholbare Felder, Dauerberechnung, Jubiläen |
| 5 | Import und Export | Excel-Import mit Vorschau und Rückgängig, Export Excel/PDF |
| 6 | Dachverband und Betrieb | Freigaben, Dachverbandsansicht, Server, Backups, Sicherheitsprüfung |

## Datenübernahme: vollständiger JSON-Export und Import

- Dachverband, Verein und Abteilung exportieren unter „Einstellungen → Datenübernahme“
  (Abteilung: Reiter „Export“) alle Daten als JSON, auf Wunsch als ZIP mit Logos, Belegen
  und Fotos. Format `hubiplan-export`, Version 1. Benutzerkonten, Links und Ausweis-Token
  sind nicht enthalten.
- Ein Dachverband bekommt Mitgliedsdaten seiner Vereine nur gemäß Plattform-Freigabe und
  keine Vereinskasse. Die Plattform exportiert jede Organisation vollständig.
- Import auf der höheren Ebene, immer als neue Organisation bzw. Abteilung: Plattform
  (Dachverband oder Verein), Dachverband (Verein, auch von Hand unter „Vereine anlegen“),
  Verein (Abteilung). Erst Prüfung mit Vorschau und Dubletten (Name, Vorname,
  Geburtsdatum im Verbandsbereich), dann Übernahme in einer Transaktion.
- Rechte: `data.export`, `clubs.manage` (Dachverband), `dept.export`. Exporte und Importe
  stehen im Protokoll, Dateien werden nach 7 Tagen gelöscht.
