# HUBIplan

HUBIplan ist eine webbasierte Vereinsverwaltung für Vereine jeder Art, von 10 bis
10.000 Mitgliedern. Sie löst Excel-Listen und Papier ab und läuft im Browser auf
Smartphone, Tablet und Laptop. Pilot sind der Hubertus-Schützenverein
Neuss-Grimlinghausen von 1920 und sein Dachverband, der Bürger-Schützenverein
Neuss-Grimlinghausen von 1855 e.V.

Zu HUBIplan gehören zwei weitere Repositories:

- [hubiplan-website](https://github.com/DeltaRP/hubiplan-website): öffentliche
  Vereinswebseiten aus den Daten von HUBIplan
- [hubiplan-android](https://github.com/DeltaRP/hubiplan-android): Android-App für
  Mitglieder, Vorstand und Kasse

Konzept in Kurzfassung: [docs/konzept.md](docs/konzept.md). Testserver (nur erfundene
Daten): [docs/testserver.md](docs/testserver.md). Echtbetrieb:
[docs/echtbetrieb.md](docs/echtbetrieb.md).

## Inhalt

- [Aufbau](#aufbau)
- [Funktionen](#funktionen)
- [Technik](#technik)
- [Schnellstart mit Docker](#schnellstart-mit-docker)
- [Entwicklung ohne Docker](#entwicklung-ohne-docker)
- [Tests](#tests)
- [Ausrollen und Betrieb](#ausrollen-und-betrieb)
- [Projektstruktur](#projektstruktur)
- [Weitere Dokumentation](#weitere-dokumentation)
- [Lizenz](#lizenz)

## Aufbau

Eine Installation (Instanz) von HUBIplan ist mandantenfähig: eine Anwendung, eine
Datenbank, viele Organisationen.

| Ebene | Aufgabe |
| --- | --- |
| **Plattform** | die Instanz; legt Dachverbände und Vereine an, schaltet Module frei, sieht im Normalbetrieb keine Mitgliedsdaten |
| **Dachverband** (optional) | eigener Vorstand und eigene Benutzer; sieht Daten seiner Vereine nur, soweit die Plattform das freigibt (aus, lesen, lesen und ändern) |
| **Verein** | verwaltet seine Mitglieder selbst, gehört höchstens einem Dachverband an |
| **Untereinheiten** | frei verschachtelbar (z. B. Abteilungen, Züge, Gruppen); die Bezeichnung mit Artikel legt jeder Verein selbst fest |

Alle Einheiten sind vom selben Typ; Schalter legen fest, was eine Einheit kann
(eigene Mitglieder, Kasse, Rechnungen, Zugänge, Webseite). Jede Einheit hat eigene Rollen
mit selbst gewählten Rechten und ein eigenes Erscheinungsbild (Farben, Logo oder Wappen).
Die Trennung der Mandanten sichert neben der Anwendung auch PostgreSQL Row-Level Security ab.

**Verbund (optional):** Ein Verein kann auf einer anderen HUBIplan-Instanz laufen als sein
Dachverband. Die Instanzen koppeln sich mit einem Einmalcode und tauschen nur die
freigegebenen Daten aus, Ende-zu-Ende verschlüsselt und unterschrieben
([docs/verbund.md](docs/verbund.md)).

## Funktionen

**Mitglieder**
- Mitgliedschaften mit Zeiträumen und selbst definierten Mitgliedsarten (z. B. „an
  Dachverband melden“, „aktiv“, „zählt für die Mitgliedsdauer“)
- Aufnahme mit Dublettenprüfung im Dachverband, Austritt, Wiedereintritt, Wechsel der
  Untereinheit oder des Vereins, Löschfrist
- Zusatzfelder (auch Jahreszeiträume), Geschlecht, Mitgliederfotos mit Einwilligung
- Ehrungen, Mitgliedsdauer und Jubiläen (auch von Vereinen und Untereinheiten),
  Geburtstage, Mitgliederentwicklung
- Chronik der Würden (z. B. Könige) mit Excel-Import
- Änderungsmeldungen der Mitglieder, die der Vorstand freigibt
- Mitgliedsausweis mit QR-Code
- Import von Altdaten (Excel), Export als Excel und PDF, Datenübernahme als JSON
- Autospeichern, Rückgängig und Papierkorb, Änderungsprotokoll

**Zugänge**
- Anmeldung mit E-Mail und Passwort, optional Zwei-Faktor-Anmeldung (TOTP)
- Mitgliederbereich („Mein Bereich“) und Bereich für Untereinheiten mit Anmeldelink
- Zugänge für Kassierer der Untereinheiten und für Kassenprüfer
- „Mein Konto“: Profil, Anmeldung und Sicherheit, App und andere Instanzen, Briefvorlage
  und Unterschrift

**Beiträge und Finanzen**
- Beitragssätze je Mitgliedsart und Altersstufe, Beitragslauf mit Rechnungen an
  Mitglieder und Sammelrechnungen an Untereinheiten
- Verbandsbeitrag des Dachverbands je gemeldetem Mitglied
- Rechnungen als PDF mit QR-Code, Versand per E-Mail, Mahnstufen mit Gebühr
- SEPA-Lastschrift mit Mandaten, Lastschriftdatei (pain.008) und Vorabankündigung
- Kasse mit Konten, Kategorien, Buchungen, Belegen, Projekten und eigenem
  Geschäftsjahr; Zahlungseingänge werden automatisch gebucht
- Kontoauszug als CAMT.053 einlesen: Zahlungen werden offenen Rechnungen,
  Lastschriftläufen und schon erfassten Buchungen zugeordnet, Saldo-Abgleich mit dem
  Kassenbuch ([docs/kontoauszug.md](docs/kontoauszug.md))
- Digitale Quittungen mit Unterschrift auf dem Display, Barkasse nie unter null,
  ZIP-Export für die Prüfung nach GoBD
  ([Verfahrensdokumentation](docs/verfahrensdokumentation-kasse.md))
- Zuwendungsbestätigungen nach amtlichem Muster (nur eingetragene Vereine): Geld- und
  Sachzuwendungen, Sammelbestätigung zum Jahresende, Doppel und Storno
  ([docs/zuwendungen.md](docs/zuwendungen.md))
- optional Umsatzsteuer je Posten und steuerliche Bereiche
- Kassenbericht als PDF, Jahresabschluss mit Sperre des Geschäftsjahres

**Termine**
- Kalender für Dachverband, Verein und Untereinheiten mit Kategorien, Serienterminen,
  Anhängen und Sichtbarkeit je Termin (öffentlich, Mitglieder, nur Vorstand)
- Zu- und Absagen mit Anmeldeschluss, Höchstzahl und Begleitpersonen,
  Teilnehmerliste als Excel und PDF
- Einladung, Änderung, Absage und Erinnerung per E-Mail
- Jahresprogramm als PDF, öffentlicher Link (iCal, JSON), persönliches Kalender-Abo

**Kommunikation und Dokumente**
- Rundschreiben als Mail, Serienbrief, Mitteilung im Mitgliederbereich oder Push in die App
- Postausgang: jede Mail wird gespeichert und über SMTP versendet
- Briefbogen je Einheit und Word-Briefvorlage (`.dotx`/`.docx`) für Vorstände
- Dokumentenablage mit Ordnern und Rechten, Satzung mit allen Fassungen und
  optionalem öffentlichem Link
- Impressum und Datenschutzhinweise je Einheit und für die Plattform

**Webseite**
- Inhalte der Vereinswebseite (Begrüßung, Chronik, Textseiten, Bilderkarussell,
  Startseite aus Bausteinen) mit Entwurf und Veröffentlichen
- Wartungsmodus, Vorschau-Link, Prüfliste vor dem Veröffentlichen
- Kontaktformular mit Spamschutz ohne Fremddienst, Funktionsadressen
- eigene Beiträge von Instagram und Facebook auf der Webseite
  ([docs/social-media-beitraege.md](docs/social-media-beitraege.md))
- öffentliche, versionierte Schnittstelle `/api/public/site/v1/` für
  [hubiplan-website](https://github.com/DeltaRP/hubiplan-website)

**App**
- Schnittstelle `/api/app/v1/` für die Android-App: Verbinden per QR-Code,
  Geräteschlüssel je Gerät, jederzeit widerrufbar
- Push über Web-Push (RFC 8291, UnifiedPush), für die Play-Fassung über ein eigenes
  Push-Gateway (`backend/pushgateway`)
- Beschreibung: [docs/app.md](docs/app.md)

## Technik

| Teil | Technik |
| --- | --- |
| Backend (`backend/`) | Python 3.13, Django 5.2 LTS, Django REST Framework, drf-spectacular (OpenAPI), django-allauth (Anmeldung, 2FA) |
| Frontend (`frontend/`) | React 19, TypeScript, Vite, Node.js 24 |
| Datenbank | PostgreSQL 18 mit Row-Level Security |
| Hintergrund-Jobs | Celery mit Redis 8 (Worker und Zeitplan) |
| Dateien | openpyxl (Excel), reportlab und pypdfium2 (PDF), Pillow (Bilder) |
| Server | Docker Compose, Caddy (HTTPS), gunicorn; im Echtbetrieb hinter nginx von HestiaCP |

Die Oberfläche spricht ausschließlich über die REST-API mit dem Backend.

## Schnellstart mit Docker

Voraussetzung: [Docker Desktop](https://www.docker.com/products/docker-desktop/) oder
Docker mit Compose-Plugin.

```bash
docker compose up --build
```

Beim ersten Start werden die Images gebaut und die Datenbank angelegt. Danach:

| Adresse | Inhalt |
| --- | --- |
| http://localhost:5173 | Oberfläche (Anmeldung) |
| http://localhost:8000/admin/ | Django-Admin |
| http://localhost:8000/api/docs/ | API-Dokumentation (OpenAPI, nur angemeldet; im Serverbetrieb aus) |
| http://localhost:8000/_allauth/openapi.html | API-Doku für Anmeldung und 2FA |

Ersten Benutzer anlegen (in einem zweiten Terminal, während `docker compose up` läuft):

```bash
docker compose exec backend python manage.py createsuperuser
```

Demodaten anlegen (Dachverband und Verein mit 14 Zügen, rund 180 erfundene Mitglieder,
Demo-Webseite im Wartungsmodus):

```bash
docker compose exec backend python manage.py seed_testdata --password <eigenes-Passwort>
```

Danach unter http://localhost:5173 anmelden, z. B. mit
`vorstand@hubertus-grimlinghausen.test`. Weitere Testzugänge stehen in
[docs/testserver.md](docs/testserver.md#demodaten).

Dienste in `docker-compose.yml`:

| Dienst | Aufgabe |
| --- | --- |
| `postgres` | Datenbank (Volume `postgres-data`) |
| `redis` | Warteschlange für Celery |
| `backend` | Django-Entwicklungsserver, führt beim Start die Migrationen aus |
| `worker`, `beat` | Celery-Worker und Zeitplan |
| `frontend` | Vite-Entwicklungsserver, leitet `/api`, `/_allauth` und `/admin` ans Backend weiter |

Änderungen in `backend/` und `frontend/src/` werden ohne Neustart übernommen.

**Konfiguration:** Ohne weitere Angaben gelten Standardwerte für die Entwicklung. Zum
Anpassen `.env.example` nach `.env` kopieren. Die `.env` wird nie eingecheckt.

> Das Postgres-Passwort wird nur beim allerersten Start übernommen. Wer es später ändert,
> muss die Datenbank neu anlegen: `docker compose down -v` (löscht alle lokalen Daten).

## Entwicklung ohne Docker

**Backend** (Python 3.12 oder neuer; Datenbank und Redis z. B. mit
`docker compose up postgres redis`):

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
export DJANGO_DEBUG=true
export DATABASE_URL=postgres://hubiplan:hubiplan@localhost:5432/hubiplan
python manage.py migrate
python manage.py runserver
celery -A config worker --loglevel=info --pool=solo   # eigenes Terminal
```

Maßgeblich ist PostgreSQL, denn die Row-Level Security gibt es nur dort.

**Frontend** (Node.js 24):

```bash
cd frontend
npm install
npm run dev
```

Die Oberfläche läuft dann unter http://localhost:5173 und spricht das Backend auf
Port 8000 an (anderes Ziel: Umgebungsvariable `BACKEND_URL`).

## Tests

Vor jedem Ausrollen läuft der vollständige Test mit `scripts/test.sh`, lokal in WSL
(Distribution `Debian`) mit Docker:

```bash
scripts/test.sh <commit>                 # Backend und Frontend
BACKUP_TEST=1 scripts/test.sh <commit>   # zusätzlich Backup und Rücksicherung
```

Das Skript prüft nur den eingecheckten Stand (`git archive`) in Wegwerf-Containern:

- **Backend:** ruff und pytest gegen PostgreSQL 18
- **Frontend:** TypeScript, oxlint, Prettier und Vitest

Ein grüner Lauf endet mit `Alles grün: …` und vermerkt den Stand als getestet. Nur
solche Stände rollt `deploy/deploy.sh` aus. Den Commit immer fest angeben, weil andere
Sitzungen den Klon umschalten können.

Feste Regeln:

- **Tests laufen nie auf dem Testserver**, auch keine Test-Container.
- **Höchstens zwei Testläufe gleichzeitig, jeder höchstens 8 Kerne**, für alle Projekte
  auf Ralfs PC zusammen. `scripts/test.sh` holt sich dafür einen Platz mit
  `scripts/testplatz.sh` ([docs/testserver.md](docs/testserver.md#testplätze)).
- GitHub Actions („CI“) läuft nur von Hand (workflow_dispatch), nie automatisch.

Einzelne Prüfungen während der Entwicklung:

```bash
cd backend && ruff check . && ruff format --check .
cd frontend && npm run typecheck && npm run lint && npm run format:check
```

## Ausrollen und Betrieb

Neue Stände gehen erst auf den Testserver, dann in den Echtbetrieb.

| Server | Beschreibung |
| --- | --- |
| Testserver, nur erfundene Daten | [docs/testserver.md](docs/testserver.md) |
| Echtbetrieb hinter nginx von HestiaCP | [docs/echtbetrieb.md](docs/echtbetrieb.md) |

`docker-compose.server.yml` startet auf beiden Servern:

| Dienst | Aufgabe |
| --- | --- |
| `web` | Caddy: gebaute Oberfläche, Weiterleitung an das Backend, Sicherheits-Header |
| `backend` | Django mit gunicorn, führt beim Start die Migrationen aus |
| `worker`, `beat` | Celery für Import, Export, Mails, Verbund und wiederkehrende Jobs |
| `backup` | tägliches mit age verschlüsseltes Backup mit Rücksicherungstest |
| `postgres`, `redis` | Datenbank und Warteschlange, von außen nicht erreichbar |

Die Container laufen schreibgeschützt und ohne Zusatzrechte; die Anwendung nutzt keinen
Datenbank-Superuser. Im Echtbetrieb kommt `docker-compose.proxy.yml` dazu.

Ausrollen auf den Testserver (aus WSL, nur nach grünem `scripts/test.sh`):

```bash
DEPLOY_KEY=~/.ssh/hubiplan_dev deploy/deploy.sh <commit>
```

Das Skript überträgt den eingecheckten Stand, baut die Images auf dem Server und startet
alles neu; Datenbank und `.env` bleiben erhalten. Geheimnisse stehen nur in der `.env`
auf dem Server (Vorlage `.env.server.example`) und werden beim ersten Ausrollen zufällig
erzeugt.

Dienste, Geheimnisse, Backups, Rücksicherung, Mail und Alarm-Mails:
[docs/betrieb.md](docs/betrieb.md).

## Projektstruktur

```text
backend/
  config/          Einstellungen, URLs, Celery
  core/            Health-Check, CSRF, /api/me/, Row-Level Security, Dateiprüfung
  accounts/        Benutzerkonten (E-Mail als Login)
  organizations/   Plattform und Einheiten, Impressum, Demodaten (seed_testdata)
  access/          Rollen und Rechte
  members/         Mitglieder, Mitgliedschaften, Mitgliedsarten, Jubiläen
  customfields/    Zusatzfelder
  honors/          Würden und Chronik
  cards/           Mitgliedsausweise mit QR-Code
  exchange/        Import und Export (Excel, PDF)
  datatransfer/    Datenübernahme als JSON
  changes/         Rückgängig und Papierkorb
  audit/           Änderungsprotokoll
  portal/          Mitgliederbereich, Bereich für Untereinheiten, Anmeldelinks
  billing/         Beiträge, Beitragsläufe, Rechnungen, SEPA
  finance/         Kasse, Projekte, Quittungen, Jahresabschluss, GoBD-Export
  events/          Termine, Zu- und Absagen, Kalender-Abos
  circulars/       Rundschreiben
  letterhead/      Briefbogen und Word-Briefvorlage
  documents/       Dokumentenablage
  statutes/        Satzungen
  outbox/          Postausgang
  website/         Webseite: Inhalte, öffentliche Schnittstelle, Kontaktformular, Social Media
  peering/         Verbund mit anderen Instanzen
  devices/         App-Geräte, Push, Schnittstelle /api/app/v1/
  pushgateway/     eigenständiges Push-Gateway für die Play-Fassung der App
  tests/           pytest
frontend/
  src/api/         Aufrufe ans Backend
  src/components/  gemeinsame Bausteine, Layout mit Navigation
  src/pages/       Seiten, nach Bereichen gegliedert
  src/learning/    Lernhilfen und Glossar
  src/theme/       Farben und Logo als CSS-Variablen
  src/modules.tsx  Bereiche der linken Navigation
  lizenzen/        erzeugt die Lizenzliste der Browser-Bibliotheken
deploy/            Caddy, Ausrollen, Servereinrichtung, Backup, HestiaCP-Vorlagen
scripts/           test.sh (Testlauf vor dem Ausrollen), testplatz.sh (Testplätze)
docs/              Betrieb und Beschreibungen einzelner Bereiche
```

## Weitere Dokumentation

| Datei | Inhalt |
| --- | --- |
| [docs/konzept.md](docs/konzept.md) | Konzept in Kurzfassung: Ebenen, Rollen, Mitgliedschaften |
| [docs/testserver.md](docs/testserver.md) | Testserver, Ausrollen, Testplätze, Demodaten |
| [docs/echtbetrieb.md](docs/echtbetrieb.md) | Echtbetrieb hinter HestiaCP |
| [docs/betrieb.md](docs/betrieb.md) | Dienste, Geheimnisse, Backups, Mail, Notfall |
| [docs/sicherheitspruefung.md](docs/sicherheitspruefung.md) | Sicherheitsprüfung |
| [docs/verbund.md](docs/verbund.md) | Verbund mit anderen Instanzen |
| [docs/app.md](docs/app.md) | Schnittstelle für die App, Push |
| [docs/rueckgaengig.md](docs/rueckgaengig.md) | Autospeichern, Rückgängig, Papierkorb |
| [docs/rundschreiben.md](docs/rundschreiben.md) | Rundschreiben |
| [docs/briefvorlage.md](docs/briefvorlage.md) | Briefbogen und Briefvorlage |
| [docs/dokumente.md](docs/dokumente.md) | Dokumentenablage und Satzung |
| [docs/ehrungen.md](docs/ehrungen.md) | Ehrungen |
| [docs/impressum.md](docs/impressum.md) | Impressum und Datenschutzhinweise |
| [docs/social-media-beitraege.md](docs/social-media-beitraege.md) | Social-Media-Beiträge auf der Webseite |
| [docs/verfahrensdokumentation-kasse.md](docs/verfahrensdokumentation-kasse.md) | Verfahrensdokumentation Kasse und Quittungen (GoBD) |
| [docs/lernhilfen.md](docs/lernhilfen.md) | Lernhilfen, Glossar, Prüflisten |
| [docs/lizenzen.md](docs/lizenzen.md) | Lizenzen der Abhängigkeiten |

## Lizenz

Copyright © 2026 Ralf Philipsen (Philipsen EDV)

HUBIplan ist freie Software: Sie dürfen es unter den Bedingungen der **GNU Affero General
Public License**, wie von der Free Software Foundation veröffentlicht, weitergeben
und/oder ändern, entweder gemäß Version 3 der Lizenz oder (nach Ihrer Wahl) jeder
späteren Version (`AGPL-3.0-or-later`).

HUBIplan wird in der Hoffnung verbreitet, dass es nützlich ist, aber **ohne jede
Gewährleistung**, sogar ohne die implizite Gewährleistung der Marktreife oder der
Eignung für einen bestimmten Zweck. Einzelheiten stehen in der Lizenz. Den vollständigen
Lizenztext (englisch, maßgeblich) enthält die Datei [LICENSE](LICENSE).

Kurz gesagt: Jeder darf HUBIplan nutzen, verändern und weitergeben. Wer eine veränderte
Fassung weitergibt **oder als Online-Dienst betreibt**, muss den Quellcode dieser Fassung
unter derselben Lizenz zugänglich machen.

Jede Instanz zeigt unter „Lizenzen“ (Fußzeile) den Lizenztext und die Lizenzen der im
Browser-Code enthaltenen Bibliotheken. Lizenzen der Abhängigkeiten und die Pflichten bei
der Weitergabe von Images: [docs/lizenzen.md](docs/lizenzen.md).
