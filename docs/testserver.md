# Testserver

Der Testserver ist ein Hostinger-VPS (Ubuntu 24.04, Docker). In dieser Anleitung steht
`test.example.org` für seine Adresse; die echte steht nur auf Ralfs Rechner, für
`deploy/deploy.sh` als SSH-Ziel in `~/.config/hubiplan/testserver` (eine Zeile, z. B.
`root@test.example.org`). Er ist zum Ausprobieren gedacht und enthält **nur erfundene Testdaten**.

## Aufbau

`docker-compose.server.yml` startet:

| Dienst | Aufgabe |
| --- | --- |
| `web` | Caddy: HTTPS mit Let's-Encrypt-Zertifikat (automatisch), liefert das gebaute Frontend aus und leitet `/api`, `/_allauth`, `/admin`, `/static` ans Backend weiter |
| `backend` | Django mit gunicorn (`DJANGO_DEBUG=false`), führt beim Start die Migrationen aus |
| `worker` | Celery-Worker (Import, Export) |
| `beat` | Zeitplan (Löschfrist täglich) |
| `backup` | tägliches verschlüsseltes Backup mit Rücksicherungstest, siehe [betrieb.md](betrieb.md) |
| `postgres`, `redis` | Datenbank und Nachrichtenvermittlung, von außen nicht erreichbar |

Von außen offen sind nur die Ports 22 (SSH), 80 und 443 (Hostinger-Firewall).

Die Geheimnisse (`DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`) stehen nur in
`/opt/hubiplan/.env` auf dem Server. Beim ersten Ausrollen erzeugt
`deploy/server-setup.sh` sie zufällig. Vorlage: `.env.server.example`.

## Ausrollen

Feste Regeln:

- **Tests laufen nie auf dem Testserver.** Erst lokal testen, dann ausrollen.
- **Höchstens zwei Testläufe gleichzeitig, jeder höchstens 8 Kerne**, projektübergreifend
  für alle Projekte auf Ralfs PC (siehe „Testplätze“ unten). Tests nur über
  `scripts/test.sh` starten.

Ausgerollt wird aus WSL (Distribution `Debian` mit Docker), im Klon `~/hubiplan`.
Von Windows aus: `wsl -d Debian -- bash -lc 'cd ~/hubiplan && scripts/test.sh <commit>'`.
Er holt sich die Commits aus dem Windows-Checkout (`origin` zeigt auf
`/mnt/e/Softwareentwicklung/hubiplan`). Der Schlüssel liegt in WSL unter
`~/.ssh/hubiplan_dev` (Rechte 600).

```bash
cd ~/hubiplan && git fetch origin && git checkout --detach origin/main
scripts/test.sh                                   # Backend, Frontend; BACKUP_TEST=1 für Backup
DEPLOY_KEY=~/.ssh/hubiplan_dev deploy/deploy.sh        # nur nach grünem scripts/test.sh
```

`scripts/test.sh` vermerkt den getesteten Stand (Git-Tree) in
`~/.local/state/hubiplan/tested-trees`. `deploy/deploy.sh` bricht ab, wenn der Stand dort
fehlt. Ein Merge-Commit mit unverändertem Inhalt gilt als getestet.

Fehlt der angegebene Commit im Klon, holt `scripts/test.sh` erst von allen Remotes
(`git fetch --all`). Ist er dann immer noch nicht da, bricht es mit Exit 2 ab. Jeder
Fehlschlag endet mit der Zeile `FEHLGESCHLAGEN (Exit …)`, nur ein vollständiger Lauf mit
`Alles grün: …`. Der WSL-Klon holt vom Windows-Checkout, dort also vorher `git fetch origin`.

Das Skript überträgt den eingecheckten Stand (`git archive`), baut die Images auf dem
Server und startet alles neu. Datenbank und `.env` bleiben erhalten.

## Testplätze

Auf Ralfs PC laufen höchstens zwei Testläufe gleichzeitig, jeder mit höchstens 8 Kernen,
für alle Projekte zusammen. Das regelt `scripts/testplatz.sh`:

```bash
testplatz [--kerne N] <befehl …>   # wartet auf einen freien Platz, dann läuft der Befehl
```

- Zwei Plätze (`~/.testplaetze/platz-1.lock`, `platz-2.lock` in WSL). Wer keinen freien
  Platz findet, wartet. Bricht ein Lauf ab, gibt das System den Platz von selbst frei.
- Der Befehl ist an die Kerne seines Platzes gebunden (WSL: `taskset`; Windows:
  Prozessor-Affinität, Platz 1 = Kerne 0–7, Platz 2 = Kerne 8–15) und bekommt
  `TEST_KERNE` (Anzahl), `TESTPLATZ_CPUS` (für `docker run --cpuset-cpus`) und
  `TESTPLATZ` (Nummer). Docker-Container erben die Bindung nicht, deshalb setzen die
  Testskripte `--cpuset-cpus` selbst.
- Es läuft in WSL und in Git Bash unter Windows; unter Windows holt es den Platz über
  WSL (Distribution `Debian`).
- Ältere Testskripte mit der exklusiven Sperre `~/.hubiplan-tests.lock` belegen beide
  Plätze, bis sie umgestellt sind. Startet man ein solches Skript selbst mit `testplatz`, bekommt es
  über `HUBIPLAN_TEST_LOCK` eine eigene Sperrdatei und belegt nur diesen einen Platz.
- In WSL stehen 12 Prozessoren zur Verfügung (`%USERPROFILE%\.wslconfig`); zwei Läufe
  in WSL teilen sich also 12 Kerne (Platz 1: 0–7, Platz 2: 4–11).

Installation (einmal und nach Änderungen an `scripts/testplatz.sh`):

```bash
install -m 755 scripts/testplatz.sh ~/.local/bin/testplatz   # in WSL
install -m 755 scripts/testplatz.sh ~/bin/testplatz          # in Git Bash unter Windows
```

`scripts/test.sh` von hubiplan holt sich den Platz selbst (über die Kopie im Repo),
ebenso `scripts/test.sh` in `hubiplan-website` und `hubiplan-android` (über das
installierte `testplatz`). Andere Projekte: Testbefehl mit `testplatz` starten und
`TEST_KERNE` als Anzahl der Worker nehmen.

### Wo welche Tests laufen (gemessen am 30.10.2026, je 8 Kerne)

| Suite | WSL | Windows | läuft in |
|---|---|---|---|
| hubiplan Backend (ruff, pytest gegen PostgreSQL) | 114 s | – (braucht Docker) | WSL |
| hubiplan Frontend (npm ci, Typen, Lint, Format, Vitest) | 25 s | 81 s | WSL |
| Webseite (ruff, pytest) | 4 s | 4 s | WSL (wie auf dem Server) |
| Android (Unit-Tests, Lint, APKs; voller Bau ohne Cache) | 251 s | 132 s | Windows (Git Bash) |

Gemessen bei laufenden Tests anderer Threads, also nur als grober Vergleich. Android in WSL
lief mit Klon und SDK auf E: (`/mnt/e/…`), weil temporäre Dateien auf E: liegen sollen;
der Dateizugriff von WSL auf Windows-Laufwerke ist langsam.
Innerhalb eines hubiplan-Laufs laufen die Frontend-Prüfungen ohne Tests (npm ci,
Typen, Lint, Format) gleichzeitig mit dem Backend; die Vitest-Tests laufen danach
allein, weil ihre Wartezeiten (`findBy…`) neben den Backend-Tests auf denselben Kernen
zu knapp werden. Ein kompletter Lauf dauerte so 139 s (vorher 124 s mit 12 Kernen,
aber nur ein Lauf zur Zeit).

### Was die Tests schnell hält

- **Testdatenbank als Vorlage:** `scripts/test.sh` migriert einmal und kopiert die
  Datenbank je Worker (`CREATE DATABASE … TEMPLATE`), statt in jedem Worker alle
  Migrationen laufen zu lassen (je ~40 s Rechenzeit). Die migrierte Datenbank liegt als
  `pg_dump` in `/mnt/e/tmp/hubiplan-tests/db-vorlagen/` (zehn neueste). Der Dateiname ist
  ein Schlüssel über Migrationen, die von ihnen eingebundenen Module, Modelle, `apps.py`,
  Einstellungen, Abhängigkeiten und das Datenbank-Image; ändert sich davon etwas, wird neu
  migriert. `TEST_DB_CACHE=0` schaltet die Vorlage ab, `TEST_DB_CACHE=<ordner>` legt sie
  woanders ab.
- **Schneller Passwort-Hasher in Tests** (`tests/conftest.py`): PBKDF2 kostet je Passwort
  ~0,2 s. Im Betrieb bleibt PBKDF2.
- **Langsame Tests zuerst:** Tests mit `@pytest.mark.langsam` (Migrationstest, Demodaten)
  sammelt pytest zuerst; mit `--maxschedchunk=2` verteilt xdist sie auf verschiedene Worker,
  statt dass einer am Ende allein läuft.
- **Tests mit `transaction=True`** leeren am Ende alle Tabellen. `tests/conftest.py` legt
  danach die Zeilen aus Datenmigrationen (z. B. die Plattform-Organisation) wieder an,
  damit nachfolgende Tests nicht von der Reihenfolge abhängen.
- **Frontend:** Vitest läuft mit `pool: 'vmThreads'` (jsdom einmal je Worker statt je
  Datei, etwa halbe Laufzeit). `window.location` lässt sich darin nicht ersetzen;
  Weiterleitungen laufen über `leaveTo.go` (`api/peering.ts`), Tests ersetzen diese.

## Nützliche Befehle auf dem Server

```bash
cd /opt/hubiplan
docker compose -f docker-compose.server.yml ps          # Status
docker compose -f docker-compose.server.yml logs -f web backend
docker compose -f docker-compose.server.yml exec backend python manage.py createsuperuser
```

## Demodaten

Pilotorganisationen mit erfundenen Mitgliedern (Adressen auf `.test`):
Dachverband „Bürger-Schützenverein Neuss-Grimlinghausen von 1855 e.V.“ mit dem Verein
„Hubertus-Schützenverein Neuss-Grimlinghausen von 1920“ und seinen 14 Zügen.

```bash
docker compose -f docker-compose.server.yml exec backend python manage.py seed_testdata
```

Ohne `--password` wird ein zufälliges Passwort für alle Testzugänge erzeugt und einmal
ausgegeben. Testzugänge: `plattform@hubiplan.test` (Plattform),
`vorstand@bsv-grimlinghausen.test` (Vorstand Dachverband),
`vorstand@hubertus-grimlinghausen.test` (Vorstand Verein),
`kasse@hubertus-grimlinghausen.test` (Kassierer, eingeschränkte Rechte).

Frühere Demo-Organisationen samt Zugängen, Mitgliedern, Fotos und Dateien entfernen
(erst mit `--dry-run` prüfen):

```bash
docker compose -f docker-compose.server.yml exec backend python manage.py seed_testdata --remove-legacy-demo --dry-run
docker compose -f docker-compose.server.yml exec backend python manage.py seed_testdata --remove-legacy-demo
```

## Tests gegen PostgreSQL

Nur lokal, siehe „Ausrollen“: `scripts/test.sh` (mit `BACKUP_TEST=1` auch Backup
und Rücksicherung). Auf dem Server laufen keine Tests.

## Vereinswebseite (hubiplan-website)

Die Vereinsseite aus dem Repository `hubiplan-website` läuft auf dem Testserver als eigener
Container `website` im Docker-Netz `hubiplan_web`. Caddy leitet
`https://test.example.org/webseite/` dorthin weiter; läuft der Container nicht, antwortet
nur dieser Pfad mit einem Fehler.

In `/opt/hubiplan/.env`:

```bash
WEBSITE_PREVIEW_ONLY=true          # alle Webseiten nur in der Vorschau (erfundene Daten)
WEBSITE_PUBLIC_URL=https://test.example.org/webseite/
```

`seed_testdata` richtet die Webseite des Demovereins mit erfundenen Inhalten ein
(Domain `www.hubertus-grimlinghausen.test`, Wartungsmodus). Ansehen: in HUBIplan unter
Webseite › Einstellungen „Vorschau öffnen“.
