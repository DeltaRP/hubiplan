# HUBIplan

**Freie, webbasierte Vereinsverwaltung für Vereine jeder Art, von 10 bis 10.000 Mitgliedern.**

HUBIplan ersetzt Excel-Listen, Papierordner und Zettelkasse durch eine gemeinsame Anwendung im
Browser, auf Smartphone, Tablet und Laptop. Mitglieder, Beiträge, Kasse, Termine, Rundschreiben,
Dokumente und die Vereinswebseite liegen an einem Ort, mit klaren Rechten für Vorstand,
Untereinheiten und Mitglieder. Entstanden ist HUBIplan für einen Schützenverein mit vielen
Zügen und seinen Dachverband; alle Funktionen sind aber allgemein gehalten und lassen sich
einzeln ein- und ausschalten.

> **English:** HUBIplan is free (AGPL-3.0-or-later), self-hostable membership management for
> clubs and associations, built with Django, React and PostgreSQL. It targets German clubs
> (SEPA, GoBD-compliant cash book, German donation receipts), so the user interface and the
> documentation are in German. Issues, questions and security reports in English are welcome.

Zu HUBIplan gehören drei Repositories:

| Repository | Inhalt |
| --- | --- |
| **hubiplan** (dieses) | die Vereinsverwaltung: Backend, Oberfläche, Betrieb |
| [hubiplan-website](https://github.com/DeltaRP/hubiplan-website) | öffentliche Vereinswebseiten aus den Daten von HUBIplan |
| [hubiplan-android](https://github.com/DeltaRP/hubiplan-android) | Android-App für Mitglieder, Vorstand und Kasse |

## Inhalt

- [Funktionen](#funktionen)
- [Aufbau](#aufbau)
- [Technik](#technik)
- [Ausprobieren mit Docker](#ausprobieren-mit-docker)
- [Entwicklung](#entwicklung)
- [Selbst betreiben](#selbst-betreiben)
- [Projektstruktur](#projektstruktur)
- [Dokumentation](#dokumentation)
- [Mitwirken](#mitwirken)
- [Sicherheit](#sicherheit)
- [Lizenz](#lizenz)

## Funktionen

**Mitglieder**
- Mitgliedschaften mit Zeiträumen und selbst definierten Mitgliedsarten (z. B. „an
  Dachverband melden“, „aktiv“, „zählt für die Mitgliedsdauer“)
- Aufnahme mit Dublettenprüfung im Dachverband, Austritt, Wiedereintritt, Wechsel der
  Untereinheit oder des Vereins, Löschfrist
- Zusatzfelder (auch Jahreszeiträume), Mitgliederfotos mit Einwilligung
- Ehrungen, Mitgliedsdauer, Jubiläen und Geburtstage, Mitgliederentwicklung
- Würden (z. B. Königinnen und Könige) mit Chronik und Excel-Import, Ämter mit Chronik
- Änderungsmeldungen der Mitglieder, die der Vorstand freigibt
- Mitgliedsausweis mit QR-Code
- Import aus Excel, Export als Excel und PDF, Datenübernahme als JSON
- Autospeichern, Rückgängig, Papierkorb und Änderungsprotokoll

**Zugänge und Rechte**
- Anmeldung mit E-Mail und Passwort, Zwei-Faktor-Anmeldung (TOTP), Einladungen statt
  Startpasswörtern
- Rollen mit frei wählbaren Rechten je Einheit; eine Person kann mehrere Rollen haben
- Mitgliederbereich („Mein Bereich“), Bereich für Untereinheiten, Zugänge für Kassierer
  und Kassenprüfer

**Beiträge und Finanzen**
- Beitragssätze je Mitgliedsart und Altersstufe, Beitragslauf mit Rechnungen an Mitglieder
  und Sammelrechnungen an Untereinheiten, Verbandsbeitrag des Dachverbands
- Rechnungen als PDF mit QR-Code, Versand per E-Mail, Mahnstufen
- SEPA-Lastschrift mit Mandaten, Lastschriftdatei (pain.008) und Vorabankündigung
- Kasse mit Konten, Kategorien, Belegen, Projekten und eigenem Geschäftsjahr;
  Kontoauszüge (CAMT.053) werden eingelesen und offenen Posten zugeordnet
- Digitale Quittungen mit Unterschrift auf dem Display, ZIP-Export für die Prüfung nach
  GoBD ([Verfahrensdokumentation](docs/verfahrensdokumentation-kasse.md))
- Zuwendungsbestätigungen nach amtlichem Muster, Kassenbericht, Jahresabschluss mit Sperre

**Termine**
- Kalender für Dachverband, Verein und Untereinheiten mit Serienterminen, Anhängen und
  Sichtbarkeit je Termin
- Zu- und Absagen mit Anmeldeschluss, Höchstzahl und Begleitpersonen, Teilnehmerlisten
- Einladung, Änderung und Erinnerung per E-Mail, Jahresprogramm als PDF, Kalender-Abo (iCal)

**Kommunikation und Dokumente**
- Rundschreiben als E-Mail, Serienbrief, Mitteilung im Mitgliederbereich oder Push in die App
- Mailverteiler, Postausgang mit Versand über SMTP
- Briefbogen und Word-Briefvorlage je Einheit
- Dokumentenablage mit Ordnern und Rechten, Satzung mit allen Fassungen
- Impressum und Datenschutzhinweise je Einheit

**Webseite und App**
- Inhalte der Vereinswebseite (Startseite aus Bausteinen, Texte, Bilder, Chronik, eigene
  Beiträge von Instagram und Facebook) mit Entwurf, Vorschau und Veröffentlichen
- öffentliche, versionierte Schnittstelle für
  [hubiplan-website](https://github.com/DeltaRP/hubiplan-website)
- Schnittstelle für die [Android-App](https://github.com/DeltaRP/hubiplan-android):
  Verbinden per QR-Code, Geräteschlüssel je Gerät, Push über Web-Push/UnifiedPush

**Barrierearm und mit Lernhilfen**: Erklärungen und Glossar direkt in der Oberfläche,
Prüflisten für wiederkehrende Aufgaben ([docs/lernhilfen.md](docs/lernhilfen.md)).

## Aufbau

Eine Installation (Instanz) von HUBIplan ist mandantenfähig: eine Anwendung, eine Datenbank,
viele Organisationen.

| Ebene | Aufgabe |
| --- | --- |
| **Plattform** | die Instanz; legt Dachverbände und Vereine an, schaltet Module frei, sieht im Normalbetrieb keine Mitgliedsdaten |
| **Dachverband** (optional) | eigener Vorstand; sieht Daten seiner Vereine nur, soweit die Plattform das freigibt |
| **Verein** | verwaltet seine Mitglieder selbst, gehört höchstens einem Dachverband an |
| **Untereinheiten** | frei verschachtelbar (Abteilungen, Züge, Gruppen …); die Bezeichnung legt jeder Verein selbst fest |

Alle Einheiten sind vom selben Typ; Schalter legen fest, was eine Einheit kann (eigene
Mitglieder, Kasse, Rechnungen, Zugänge, Webseite). Jede Einheit hat eigene Rollen und ein
eigenes Erscheinungsbild (Farben, Logo oder Wappen). Die Trennung der Mandanten sichert neben
der Anwendung auch PostgreSQL Row-Level Security ab.

**Verbund (optional):** Ein Verein kann auf einer anderen HUBIplan-Instanz laufen als sein
Dachverband. Die Instanzen koppeln sich mit einem Einmalcode und tauschen nur freigegebene
Daten aus, Ende-zu-Ende verschlüsselt und signiert ([docs/verbund.md](docs/verbund.md)).

```text
Browser ──HTTPS──> Caddy ──> Oberfläche (React, statisch)
                        └──> Backend (Django REST) ──> PostgreSQL
                                     └── Celery-Worker und Zeitplan ──> Redis
Vereinswebseite ──> /api/public/site/v1/      Android-App ──> /api/app/v1/
```

Die Oberfläche spricht ausschließlich über die REST-API mit dem Backend.

## Technik

| Teil | Technik |
| --- | --- |
| Backend (`backend/`) | Python 3.13, Django 5.2 LTS, Django REST Framework, drf-spectacular (OpenAPI), django-allauth (Anmeldung, 2FA) |
| Frontend (`frontend/`) | React 19, TypeScript, Vite, Node.js 24 |
| Datenbank | PostgreSQL 18 mit Row-Level Security |
| Hintergrund-Jobs | Celery mit Redis 8 |
| Dateien | openpyxl (Excel), reportlab und pypdfium2 (PDF), Pillow (Bilder) |
| Betrieb | Docker Compose, Caddy (HTTPS), gunicorn |

## Ausprobieren mit Docker

Voraussetzung: Docker mit Compose-Plugin (z. B. [Docker Desktop](https://www.docker.com/products/docker-desktop/)).

```bash
git clone https://github.com/DeltaRP/hubiplan.git
cd hubiplan
docker compose up --build
```

Beim ersten Start werden die Images gebaut und die Datenbank angelegt. In einem zweiten
Terminal Demodaten anlegen (Dachverband und Verein mit 14 Zügen, rund 180 erfundene
Mitglieder, Demo-Webseite):

```bash
docker compose exec backend python manage.py seed_testdata --password <eigenes-Passwort>
```

Danach unter http://localhost:5173 anmelden, z. B. als `vorstand@hubertus-grimlinghausen.test`
mit dem gewählten Passwort. Weitere Demozugänge: [docs/testserver.md](docs/testserver.md#demodaten).
Einen eigenen Administrator legt `docker compose exec backend python manage.py createsuperuser` an.

| Adresse | Inhalt |
| --- | --- |
| http://localhost:5173 | Oberfläche |
| http://localhost:8000/admin/ | Django-Admin |
| http://localhost:8000/api/docs/ | API-Dokumentation (OpenAPI, nur angemeldet; im Serverbetrieb aus) |

Änderungen in `backend/` und `frontend/src/` werden ohne Neustart übernommen. Ohne weitere
Angaben gelten Standardwerte für die Entwicklung; zum Anpassen `.env.example` nach `.env`
kopieren (die `.env` wird nie eingecheckt).

> Das Postgres-Passwort wird nur beim allerersten Start übernommen. Wer es später ändert,
> muss die Datenbank neu anlegen: `docker compose down -v` (löscht alle lokalen Daten).

## Entwicklung

**Backend ohne Docker** (Python 3.12 oder neuer; Datenbank und Redis z. B. mit
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

**Frontend ohne Docker** (Node.js 24):

```bash
cd frontend
npm install
npm run dev          # spricht das Backend auf Port 8000 an (anderes Ziel: BACKEND_URL)
```

**Prüfungen** während der Entwicklung:

```bash
cd backend && ruff check . && ruff format --check .
cd frontend && npm run typecheck && npm run lint && npm run format:check
```

**Vollständiger Test** vor jedem Merge und jedem Ausrollen (Linux oder WSL mit Docker):

```bash
scripts/test.sh <commit>                 # Backend (ruff, pytest gegen PostgreSQL 18) und Frontend (tsc, oxlint, Prettier, Vitest)
BACKUP_TEST=1 scripts/test.sh <commit>   # zusätzlich Backup und Rücksicherung
```

Das Skript prüft nur den eingecheckten Stand (`git archive`) in Wegwerf-Containern und
vermerkt einen grünen Stand als getestet; nur solche Stände rollt `deploy/deploy.sh` aus.
Damit sich mehrere Testläufe auf einem Rechner nicht gegenseitig ausbremsen, holt es sich
über [`scripts/testplatz.sh`](scripts/testplatz.sh) einen von zwei Testplätzen mit je
höchstens 8 Kernen. Tests laufen nie auf einem Server. GitHub Actions gibt es nur zum
Starten von Hand.

## Selbst betreiben

HUBIplan läuft auf jedem Linux-Server mit Docker und Compose-Plugin. Ausgerollt wird von
einem Rechner mit dem Repository per SSH:

```bash
scripts/test.sh <commit>
DEPLOY_HOST=root@hubiplan.example.org SITE_HOST=hubiplan.example.org deploy/deploy.sh <commit>
```

- Das Skript überträgt den eingecheckten Stand, baut die Images auf dem Server und startet
  alles neu. Schlägt der Start fehl, geht es automatisch zur vorigen Fassung zurück.
- Beim ersten Ausrollen entsteht auf dem Server eine `.env` mit zufälligen Geheimnissen
  (Vorlage [.env.server.example](.env.server.example)). Sie verlässt den Server nie;
  Passphrase und Schlüssel für Backups und 2FA unbedingt zusätzlich sicher verwahren.
- Caddy holt das HTTPS-Zertifikat selbst. Läuft auf dem Server schon ein Webserver, startet
  `HUBIPLAN_HINTER_PROXY=1` Caddy nur lokal auf `WEB_PORT` hinter diesem
  ([docs/echtbetrieb.md](docs/echtbetrieb.md), Beispiel mit HestiaCP).
- Mit Anmeldung als normaler Benutzer und `sudo`: `DEPLOY_SUDO=1`.

Im Betrieb laufen die Dienste `web` (Caddy), `backend` (gunicorn), `worker` und `beat`
(Celery), `backup` (tägliches, mit age verschlüsseltes Backup mit Rücksicherungstest),
`postgres` und `redis`. Die Container laufen schreibgeschützt und ohne Zusatzrechte; die
Anwendung nutzt keinen Datenbank-Superuser. Geheimnisse, Backups, Rücksicherung, E-Mail,
Virenprüfung, Alarm-Mails und Updates: [docs/betrieb.md](docs/betrieb.md).

Wer HUBIplan für andere betreibt, beachtet die AGPL: Jede Instanz verlinkt unter „Lizenzen“
(Fußzeile) den Quellcode genau der laufenden Fassung. Wer HUBIplan verändert, muss den
geänderten Quellcode genauso anbieten.

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
  lizenzen/        erzeugt die Lizenzliste der Browser-Bibliotheken
deploy/            Caddy, Ausrollen, Servereinrichtung, Backup, HestiaCP-Vorlagen
scripts/           test.sh (vollständiger Test), testplatz.sh (Testplätze)
docs/              Betrieb und Beschreibungen einzelner Bereiche
```

## Dokumentation

| Datei | Inhalt |
| --- | --- |
| [docs/konzept.md](docs/konzept.md) | Konzept in Kurzfassung: Ebenen, Rollen, Mitgliedschaften |
| [docs/betrieb.md](docs/betrieb.md) | Dienste, Geheimnisse, Backups, Mail, Updates, Notfall |
| [docs/echtbetrieb.md](docs/echtbetrieb.md) | Betrieb hinter einem vorhandenen Webserver (HestiaCP) |
| [docs/testserver.md](docs/testserver.md) | Testserver, Testplätze, Demodaten |
| [docs/sicherheitspruefung.md](docs/sicherheitspruefung.md) | Sicherheitsprüfung |
| [docs/verbund.md](docs/verbund.md) | Verbund mit anderen Instanzen |
| [docs/app.md](docs/app.md) | Schnittstelle für die App, Push |
| [docs/kontoauszug.md](docs/kontoauszug.md) | Kontoauszüge (CAMT.053) einlesen |
| [docs/verfahrensdokumentation-kasse.md](docs/verfahrensdokumentation-kasse.md) | Verfahrensdokumentation Kasse und Quittungen (GoBD) |
| [docs/zuwendungen.md](docs/zuwendungen.md) | Zuwendungsbestätigungen |
| [docs/rueckgaengig.md](docs/rueckgaengig.md) | Autospeichern, Rückgängig, Papierkorb |
| [docs/rundschreiben.md](docs/rundschreiben.md) | Rundschreiben |
| [docs/briefvorlage.md](docs/briefvorlage.md) | Briefbogen und Briefvorlage |
| [docs/dokumente.md](docs/dokumente.md) | Dokumentenablage und Satzung |
| [docs/ehrungen.md](docs/ehrungen.md), [docs/wuerden.md](docs/wuerden.md), [docs/aemter.md](docs/aemter.md) | Ehrungen, Würden, Ämter |
| [docs/impressum.md](docs/impressum.md) | Impressum und Datenschutzhinweise |
| [docs/social-media-beitraege.md](docs/social-media-beitraege.md) | Social-Media-Beiträge auf der Webseite |
| [docs/lernhilfen.md](docs/lernhilfen.md) | Lernhilfen, Glossar, Prüflisten |
| [docs/lizenzen.md](docs/lizenzen.md) | Lizenzen der Abhängigkeiten, Pflichten bei der Weitergabe |

## Mitwirken

Fehlermeldungen, Ideen und Pull Requests sind willkommen. Wie das geht und unter welchen
Bedingungen Beiträge aufgenommen werden, steht in [CONTRIBUTING.md](CONTRIBUTING.md).
Wichtig vorab: nur erfundene Daten in Tests, Beispielen und Fehlerberichten, nie echte
Mitgliederdaten.

## Sicherheit

Sicherheitslücken bitte **nicht** als öffentliches Issue melden, sondern vertraulich über
[GitHub](https://github.com/DeltaRP/hubiplan/security/advisories/new). Einzelheiten:
[SECURITY.md](SECURITY.md).

## Lizenz

Copyright © 2026 Ralf Philipsen (Philipsen EDV)

HUBIplan ist freie Software: Sie dürfen es unter den Bedingungen der **GNU Affero General
Public License**, wie von der Free Software Foundation veröffentlicht, weitergeben und/oder
ändern, entweder gemäß Version 3 der Lizenz oder (nach Ihrer Wahl) jeder späteren Version
(`AGPL-3.0-or-later`).

HUBIplan wird in der Hoffnung verbreitet, dass es nützlich ist, aber **ohne jede
Gewährleistung**, sogar ohne die implizite Gewährleistung der Marktreife oder der Eignung für
einen bestimmten Zweck. Einzelheiten stehen in der Lizenz. Den vollständigen Lizenztext
(englisch, maßgeblich) enthält die Datei [LICENSE](LICENSE).

Kurz gesagt: Jeder darf HUBIplan nutzen, verändern und weitergeben. Wer eine veränderte
Fassung weitergibt **oder als Online-Dienst betreibt**, muss den Quellcode dieser Fassung
unter derselben Lizenz zugänglich machen.

Jede Instanz zeigt unter „Lizenzen“ (Fußzeile) den Lizenztext und die Lizenzen der
enthaltenen Bibliotheken. Lizenzen der Abhängigkeiten und Pflichten bei der Weitergabe von
Images: [docs/lizenzen.md](docs/lizenzen.md). Einzelne Dateien unter anderen freien Lizenzen
(z. B. die HestiaCP-Vorlagen unter GPL-3.0) sind dort aufgeführt.
