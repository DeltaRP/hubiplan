# Betrieb

Gilt für den Testserver (`docker-compose.server.yml`) und den Echtbetrieb. Ausrollen
siehe [testserver.md](testserver.md) und [echtbetrieb.md](echtbetrieb.md). Auf dem
Echtserver gehört zu jedem `docker compose`-Befehl zusätzlich `-f docker-compose.proxy.yml`.

## Dienste

| Dienst | Aufgabe |
| --- | --- |
| `web` | Caddy: HTTPS (Let's Encrypt), Oberfläche, Weiterleitung an das Backend, Sicherheits-Header |
| `backend` | Django mit gunicorn, führt beim Start die Migrationen aus |
| `worker` | Celery: Import, Export und andere Hintergrund-Jobs |
| `beat` | Zeitplan für wiederkehrende Jobs (Löschfrist täglich) |
| `backup` | tägliches verschlüsseltes Backup mit Rücksicherungstest |
| `postgres`, `redis` | Datenbank und Warteschlange, von außen nicht erreichbar |

Die Anwendung arbeitet in der Datenbank mit der eingeschränkten Rolle `hubiplan_app`
(kein Superuser, kein BYPASSRLS). So greift der Zeilenschutz (Row-Level Security) auch,
falls in der Anwendung ein Filter fehlt.

Backend, Worker und Beat **melden sich direkt als `hubiplan_app` an** (Passwort
`APP_DB_PASSWORD`). Den Zugang des Datenbank-Superusers (`POSTGRES_PASSWORD`) nutzen nur
die Migrationen beim Start des Backends und das Backup; das Startskript entfernt ihn,
bevor gunicorn startet. Selbst Schadcode in der Anwendung kann die Rolle deshalb nicht
verlassen: kein `RESET ROLE` zum Superuser, keine Shell-Befehle über die Datenbank, kein
Abschalten von RLS. Nach einer Rücksicherung setzt der nächste Start Rechte und Passwort
der Rolle neu.

**Abschottung der Container** (`docker-compose.server.yml`):

- Backend, Worker und Beat laufen mit **schreibgeschütztem Dateisystem**: Schadcode kann
  den Programmcode nicht verändern. Schreibbar sind nur `/tmp` (Arbeitsspeicher) und die
  Daten-Volumes. Statische Dateien werden deshalb schon beim Bauen eingesammelt.
- Alle Container ohne Linux-Sonderrechte (`cap_drop: ALL`, Caddy nur mit dem Recht für
  Port 80/443) und ohne Rechteausweitung (`no-new-privileges`). Postgres braucht für
  den Start den Benutzerwechsel und behält seine Standardrechte.
- Drei Netze: `intern` (Postgres, Redis; ohne Weg ins Internet, für Caddy
  unerreichbar), `web` (Caddy ↔ Backend), `ausgang` (Mailversand, Backup-Zweitort).

## Geheimnisse

Alle Geheimnisse stehen nur in `/opt/hubiplan/.env` auf dem Server (Rechte 600), nie im
Repository. Beim ersten Ausrollen erzeugt `deploy/server-setup.sh` zufällige Werte für
`DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`, `REDIS_PASSWORD`, `BACKUP_PASSPHRASE`, `BACKUP_HMAC_KEY`
(Prüfsummen der Backups) und `MFA_ENCRYPTION_KEY` (verschlüsselt die 2FA-Geheimnisse in
der Datenbank). Fehlende Einträge ergänzt es bei jedem Ausrollen, vorhandene bleiben.

> **Wichtig:** `BACKUP_PASSPHRASE`, `BACKUP_HMAC_KEY` und `MFA_ENCRYPTION_KEY`
> zusätzlich sicher verwahren (z. B. KeePassXC), ebenso den privaten Backup-Schlüssel
> (siehe Backups). Ohne ihn bzw. die Passphrase lassen sich die Backups nicht
> entschlüsseln. Der `MFA_ENCRYPTION_KEY` liegt bewusst nicht im Backup:
> fehlt er nach einer Rücksicherung, müssen alle Benutzer ihre 2FA neu einrichten.
>
> Schlüsselwechsel für 2FA: In der `.env` `MFA_ENCRYPTION_KEYS=neuer,alter` setzen
> (hat Vorrang vor `MFA_ENCRYPTION_KEY`; Backend, Worker und Beat bekommen ihn über die
> gemeinsame Umgebung), `docker compose -f docker-compose.server.yml up -d`, dann
> `docker compose -f docker-compose.server.yml exec backend python manage.py
> mfa_schluessel_wechseln`. Danach `MFA_ENCRYPTION_KEY=neuer` setzen,
> `MFA_ENCRYPTION_KEYS` leeren und erneut `up -d`. Den alten Schlüssel erst löschen,
> wenn kein Backup mit Datenbankstand vor dem Wechsel mehr gebraucht wird.

## Verschlüsselung der Daten

Private Dateien (Mitgliederfotos, Dokumente, Belege, Rundschreiben-Anhänge, Importe,
Exporte, Bilder der Webseite) liegen verschlüsselt im Volume `private-data`
(`core/crypto.py`, `core/privatefiles.py`). Logos und Wappen (`media-data`) sind
öffentlich und bleiben unverschlüsselt.

- **Schlüssel je Verein:** Jeder Verein (bzw. Dachverband, Plattform) hat einen eigenen
  Datenschlüssel (AES-256-GCM). Untereinheiten nutzen den ihres Vereins. Die
  Datenschlüssel liegen in der Tabelle `core_datakey`, verpackt mit dem Hauptschlüssel.
  Wird ein Verein gelöscht, fällt sein Datenschlüssel weg und seine Dateien sind nicht
  mehr lesbar (in Backups erst, wenn die Backups mit dem Schlüssel abgelaufen sind).
- **Hauptschlüssel:** Datei `DATA_KEY_FILE` (Standard `/opt/hubiplan-geheim/datenschluessel`,
  UID 1000, Gruppe 70, Rechte 0440), als Docker-Secret nur in Backend, Worker, Beat und
  Backup. Er steht nicht in der `.env`. `deploy/server-setup.sh` legt ihn beim ersten
  Ausrollen an und überschreibt ihn nie.
- **Kopie des Hauptschlüssels:** Das Backup legt bei jedem Lauf `datenschluessel.age`
  neben die Backups, verschlüsselt mit dem öffentlichen Backup-Schlüssel. Sie geht mit
  restic an den zweiten Ort. Lesen kann sie nur, wer den privaten Backup-Schlüssel hat:
  `age -d -i hubiplan-backup.key datenschluessel.age`. Zusätzlich den Hauptschlüssel im
  Passwortmanager ablegen.
  > **Wichtig:** Ohne Hauptschlüssel sind die verschlüsselten Dateien auf dem Server und
  > in allen Backups verloren.
- **Austauschbare Quelle:** `DATA_KEY_PROVIDERS` (Standard `file`). Ein externer
  Schlüsseldienst kommt als weitere Quelle dazu; danach verpackt
  `manage.py datenschluessel_umverpacken` alle Datenschlüssel neu, die Daten bleiben
  unverändert (Konzept „Externer Schlüsselspeicher“). Ist die Quelle nicht erreichbar,
  antwortet die API mit 503.
- **Hauptschlüssel wechseln:** neue Zeile oben in die Schlüsseldatei (alte darunter
  lassen), `up -d`, `exec backend python manage.py datenschluessel_umverpacken`, danach die
  alte Zeile löschen und erneut `up -d`.
- **Bestand verschlüsseln:** Nach dem ersten Ausrollen mit Verschlüsselung (vorher ein
  frisches Backup) `exec backend python manage.py dateien_verschluesseln`. Wiederholbar;
  `--probe` zählt nur. Bis dahin liest HUBIplan alte Klartextdateien weiter.
- **Rückweg:** `dateien_verschluesseln --entschluesseln` legt alle Dateien wieder im
  Klartext ab. `deploy/zurueck.sh` macht das selbst, wenn die vorige Fassung die
  Verschlüsselung noch nicht kennt.

## Backups

- **Wann:** täglich um `BACKUP_TIME` (Standard 03:15); beim allerersten Start sofort.
- **Was:** die Datenbank (`pg_dump`) und die Dateien (Logos, Mitgliederfotos,
  Import-/Exportdateien, Mails, Kassenbelege).
- **Wie:** gzip-komprimiert und mit dem **öffentlichen Schlüssel** des Betreibers
  verschlüsselt (`age`, Dateien `….age`). Der Server kann Backups damit erzeugen, aber
  nicht lesen: Wer den Server oder den Backup-Ort hackt, bekommt nur unlesbare Dateien.
  Den privaten Schlüssel hat nur der Betreiber. Ohne `BACKUP_PUBLIC_KEY` gilt noch die
  alte Form mit Passphrase aus der `.env` (`….enc`, `openssl enc -aes-256-cbc -pbkdf2`).
- **Wo:** `/opt/hubiplan-backups` auf dem Server, außerhalb der Docker-Volumes;
  Aufbewahrung `BACKUP_KEEP_DAYS` Tage (Standard 30).
- **Prüfsumme:** Zu jeder Datei gehört `….enc.hmac` (HMAC-SHA256 mit dem eigenen
  Schlüssel `BACKUP_HMAC_KEY` aus der `.env`; er steht dabei in keiner Befehlszeile).
  Eine veränderte oder untergeschobene
  Datei wird vor dem Entschlüsseln abgewiesen. Backups von vor der Einführung haben
  keine Prüfsumme und lassen sich mit `verify.sh --ohne-pruefsumme` weiter nutzen.
- **Rücksicherungstest:** Jedes Backup wird in eine leere Wegwerf-Datenbank
  eingespielt; mit öffentlichem Schlüssel direkt vor dem Verschlüsseln (der Klartext
  liegt dabei nur im Arbeitsspeicher des Backup-Containers), mit Passphrase direkt nach
  dem Verschlüsseln. In beiden Fällen läuft er, bevor alte Backups gelöscht werden und
  bevor die Kopie an den zweiten Ort geht. Das Ergebnis steht in `restore-test.log`, z. B.
  `Rücksicherung ok: db_…enc – 5 Organisationen, 208 Mitgliedschaften, Dateien: 40 gesichert, 38 Verweise, 0 fehlen`.
- **Dateiliste:** Datenbank und Dateien werden nacheinander gesichert. Zu jedem
  Dateiarchiv gehört deshalb `dateien_….sha256.age` (bzw. `.enc`): die Liste aller
  gesicherten Dateien mit SHA-256, im selben Moment wie das Archiv erstellt. Der
  Rücksicherungstest vergleicht sie mit den Dateiverweisen in der Datenbank (welche
  Spalten auf Dateien zeigen, steht in `deploy/backup/dateifelder.txt`; ein Test prüft
  die Liste gegen die Modelle). Fehlt eine Datei, steht sie als `WARNUNG` in
  `restore-test.log` und `backup.log`. Das Backup gilt dann als **unvollständig**: Es
  bleibt liegen, aber alte Backups werden nicht gelöscht und die Kopie an den zweiten Ort
  läuft ohne Löschen (`unvollständig, alte Backups bleiben` im Log).
- **Backup-Stand:** Der Backup-Container schreibt nach jedem Lauf `state`, `last_ok` und
  `text` in das Volume `backup-status`. Der Worker prüft stündlich: Bei Fehler, unvollständigem
  Backup oder wenn das letzte gelungene Backup älter als `BACKUP_MAX_AGE_HOURS` (Standard 26)
  ist, kommt höchstens einmal am Tag die Alarm-Mail „Backup prüfen“.
- **Zweiter Ort (vorbereitet):** `BACKUP_REMOTE=benutzer@host:/pfad/` in der `.env`
  setzen. Auf dem Server einen Ordner (Standard `/opt/hubiplan-backup-ssh`, sonst
  `BACKUP_SSH_DIR` in der `.env`) mit `id_ed25519` (privater Schlüssel nur für die
  Kopie) und `known_hosts` (Rechnerschlüssel des Ziels, z. B. `ssh-keyscan -t ed25519
  host`, Fingerabdruck vorher abgleichen) anlegen, beides `chown 70:70` und `chmod 600`
  (UID 70 = postgres im Backup-Container). Der Ordner wird schreibgeschützt nach
  `/run/backup-ssh` eingebunden und übersteht jedes Neuanlegen des Containers. Fehlt
  Schlüssel oder `known_hosts`, bricht das Backup mit `FEHLER` in `backup.log` ab,
  bevor alte Sicherungen aufgeräumt werden; eine gescheiterte Kopie steht ebenfalls als
  `FEHLER` im Log (das lokale Backup bleibt gültig). Ein geänderter Rechnerschlüssel des
  Ziels lässt die Kopie scheitern (kein „beim ersten Mal vertrauen“).

### Backup-Ziele

Festgelegt am 31.10.2026 (Gesamtaudit 31.10.b, Fachfrage 12):

- **Höchstens 24 Stunden Datenverlust:** Das tägliche Backup reicht dafür. Bleibt es aus,
  meldet die Alarm-Mail „Backup prüfen“ das nach `BACKUP_MAX_AGE_HOURS` (26) Stunden.
- **Wiederanlauf innerhalb eines Tages** nach Totalausfall des Servers: neuer Server,
  HUBIplan ausrollen, letztes Backup einspielen (siehe Wiederherstellen).
- **Zweiter Ort:** Hetzner Storage Box mit restic (siehe [echtbetrieb.md](echtbetrieb.md)),
  mit Snapshots der Storage Box, die ein Angreifer mit root auf dem Server nicht löschen
  kann.
- **Schlüssel für den Notfall:** Für eine Wiederherstellung ohne Server und ohne Ralfs PC
  braucht es den privaten age-Schlüssel und das restic-Passwort (plus die Zugangsdaten der
  Storage Box). Alle drei liegen im Passwortmanager und zusätzlich offline (Ausdruck oder
  USB-Stick an einem sicheren Ort). Eine Vertretung (z. B. ein zweites Vorstandsmitglied)
  bekommt einen versiegelten Ausdruck.
- **Unvollständige Backups** (fehlende Dateien) gelten nicht als gelungen: eigener Zustand,
  Alarm-Mail, alte vollständige Backups bleiben erhalten.
- Eine Wiederherstellungsübung auf einem leeren Rechner ist vorerst zurückgestellt
  (Ralf, 31.10.2026).

### Backup-Schlüssel einrichten (einmalig, auf Ralfs PC)

In WSL (`sudo apt install age`) oder mit Docker:

```bash
age-keygen -o hubiplan-backup.key          # privater Schlüssel, NICHT auf den Server
# Ausgabe „Public key: age1…“ ist der öffentliche Schlüssel
```

`hubiplan-backup.key` in den Passwortmanager und ausgedruckt an einen sicheren Ort
(Vertretung regeln). Geht er verloren, sind alle damit verschlüsselten Backups verloren.
Den öffentlichen Schlüssel beim nächsten Ausrollen mitgeben (je Server ein eigenes
Schlüsselpaar):

```bash
BACKUP_PUBLIC_KEY=age1… deploy/deploy.sh
```

Ab dem nächsten Backup entstehen `….age`-Dateien. Ältere `….enc`-Backups bleiben mit der
Passphrase lesbar und laufen nach `BACKUP_KEEP_DAYS` Tagen aus.

Protokolle prüfen:

```bash
tail /opt/hubiplan-backups/backup.log /opt/hubiplan-backups/restore-test.log
```

### Wiederherstellen (Notfall)

```bash
cd /opt/hubiplan
set -a; . ./.env; set +a
DATEI=/opt/hubiplan-backups/db_JJJJ-MM-TT_HHMM.sql.gz.enc

# Erst die Prüfsumme prüfen (bricht bei veränderter Datei ab)
docker compose -f docker-compose.server.yml run --rm --no-deps --entrypoint verify.sh \
    backup "/backups/$(basename "$DATEI")"
docker compose -f docker-compose.server.yml stop backend worker beat
docker compose -f docker-compose.server.yml exec -T postgres \
    psql -U hubiplan -d postgres -c "DROP DATABASE hubiplan" -c "CREATE DATABASE hubiplan"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE -in "$DATEI" \
    | gunzip \
    | docker compose -f docker-compose.server.yml exec -T postgres psql -U hubiplan -d hubiplan
docker compose -f docker-compose.server.yml up -d   # vergibt die Rechte für hubiplan_app neu
```

Dateien entsprechend aus `files_….tar.gz.enc` in die Volumes `media-data` und
`private-data` zurückspielen. Danach im Zielordner (der `media/` und `private/` enthält)
mit der entschlüsselten Dateiliste prüfen, ob alles vollständig und unverändert ist:

```bash
sha256sum -c dateien_JJJJ-MM-TT_HHMM.sha256
```

**Backups mit öffentlichem Schlüssel (`….age`)** werden auf Ralfs PC entschlüsselt; der
private Schlüssel kommt nie auf den Server. Prüfsumme wie oben prüfen, Dienste stoppen
und Datenbank leeren, dann in WSL:

```bash
scp administrator@SERVER:/opt/hubiplan-backups/db_JJJJ-MM-TT_HHMM.sql.gz.age .
age -d -i hubiplan-backup.key db_JJJJ-MM-TT_HHMM.sql.gz.age | gunzip \
    | ssh administrator@SERVER "cd /opt/hubiplan && sudo docker compose -f docker-compose.server.yml exec -T postgres psql -U hubiplan -d hubiplan"
```

Danach `docker compose … up -d` wie oben.

**Löschliste:** Jede erledigte Löschung (Löschfrist, Löschen auf Verlangen, Verbund-Widerruf)
steht zusätzlich im Volume `loeschliste` (nur Kennungen und Zeitpunkte, keine Namen). Beim Start
des Backends und täglich wird sie erneut angewendet; so sind gelöschte Daten auch nach dem
Einspielen eines älteren Backups wieder weg (Alarm-Mail, wenn das passiert). Das Volume beim
Wiederherstellen **nicht** zurücksetzen. Auf einem neuen Server vor dem ersten Start die
neueste `loeschliste.jsonl` aus dem Backup-Ordner hineinkopieren (das Backup legt sie täglich
dorthin und kopiert sie an den zweiten Ort). Von Hand: `python manage.py loeschliste_anwenden`.

**Kettenköpfe:** Das Backup hängt täglich je Organisation Nummer und Prüfsumme des letzten
geprüften Eintrags im Änderungsprotokoll an `kettenkoepfe.log` im Backup-Ordner an (keine
Inhalte). Die Datei geht mit an den zweiten Ort und mit restic nach Hetzner; ältere Stände
bleiben in den Schnappschüssen. Abgleich mit der Datenbank:
`python manage.py kettenkoepfe_pruefen /pfad/kettenkoepfe.log`. Das macht Löschen oder
Neuberechnen der Kette sichtbar, solange die Hetzner-Kopie unberührt ist; gegen jemanden mit
vollem Zugriff auf Server und Hetzner schützt es nicht.

**Alte Startpasswörter:** `python manage.py startpasswoerter` zeigt nur die Anzahl der Konten,
die noch ein Startpasswort haben; mit `--umstellen` wird es unbrauchbar und die Person bekommt
einen Link zum Festlegen des Passworts.

## E-Mail

Jede Mail landet im **Postausgang** der Datenbank:

- Vereine und Dachverbände sehen ihre Mails unter Einstellungen → Postausgang.
- Plattform-Admins sehen alle Mails unter Plattform → Postfach (Test-Postfach).

Kontomails (Passwort geändert, Bestätigungslink für eine neue Anmelde-E-Mail) gehören
keiner Organisation und stehen nur im Plattform-Postfach. Solange SMTP fehlt, findet man
dort auch den Bestätigungslink, wenn jemand seine Anmelde-E-Mail ändert.

Rechnungen aus Beitragsläufen gehen mit PDF-Anhang an die Mitglieder bzw. an den
Kassierer der Abteilung (Abteilungsrolle mit dem Recht „Sammelrechnungen der Abteilung
sehen“). Ohne SMTP stehen sie im Postausgang des Vereins (Art „rechnung“).
Verbandsrechnungen des Dachverbands gehen an die Kontaktadresse des Vereins,
Mahnungen tragen die Art „mahnung“.
Vor jedem Lastschrifteinzug gehen Vorabankündigungen an die Zahler (Art
„vorabankuendigung“); wer ein Mandat im Mitgliederbereich erteilt, bekommt eine Bestätigung
(Art „mandat“). Die Lastschriftdatei (SEPA-XML, pain.008.001.08) lädt der Kassierer
herunter und reicht sie selbst im Online-Banking ein; die Software spricht nicht mit der Bank.

Solange kein SMTP-Zugang hinterlegt ist, wird nichts zugestellt. Für echten Versand in
der `.env` setzen und neu starten (die Mails bleiben zusätzlich im Postausgang):

```text
EMAIL_HOST=smtp.example.org
EMAIL_PORT=587
EMAIL_HOST_USER=…
EMAIL_HOST_PASSWORD=…
DEFAULT_FROM_EMAIL=hubiplan <noreply@example.org>
```

`DJANGO_EMAIL_BACKEND` nicht setzen, sonst fällt der Postausgang weg.

**Aufbewahrung:** Bei zugestellten Mails leert ein täglicher Job nach
`OUTBOX_RETENTION_DAYS` Tagen (Standard 30) Text und Anhänge. Empfänger, Betreff, Art und
Datum bleiben als Nachweis. Nicht zugestellte Mails bleiben vollständig.

## Grenzen der Container

Backend und Worker haben feste Grenzen für Arbeitsspeicher und `/tmp`, damit ein großer
Upload oder Import nicht den ganzen Server lahmlegt. Anpassbar in der `.env`:
`BACKEND_MEM_LIMIT` (Standard `1536m`), `BACKEND_TMP_SIZE` (Standard `768m`),
`WORKER_MEM_LIMIT` (Standard `2g`). Der Worker läuft mit zwei parallelen Aufgaben. Caddy
nimmt höchstens 520 MB je Anfrage an.

## Einladungen statt Startpasswort

Neue Konten (Rollen, Plattform-Vorstand) bekommen kein Startpasswort mehr, sondern eine
Einladung per Mail mit einem Link zum Festlegen des Passworts, 7 Tage gültig („Passwort
vergessen“ bleibt bei 3 Tagen). Alte Startpasswörter gelten wie bisher höchstens 7 Tage und
müssen bei der ersten Anmeldung ersetzt werden; ein stündlicher Job macht abgelaufene
unbrauchbar und meldet App-Geräte und Verbund-Anmeldungen des Kontos ab.

## Pflicht-2FA

Wer Rollen verwaltet, vollständige Exporte erstellt, in der Kasse bucht oder die Plattform
verwaltet, braucht die Zwei-Faktor-Anmeldung. Beim ersten Bedarf beginnen 14 Tage Übergang
(Hinweis oben auf jeder Seite); danach ruhen genau diese Rechte, bis 2FA eingerichtet ist
(für Plattform-Zugänge alle Plattformrechte). Handy verloren: mit einem
Wiederherstellungscode anmelden, oder eine zweite Person mit Rollenverwaltung und eigener
2FA setzt unter Rollen „2FA zurücksetzen“ (Mail an die Person, Alarm-Mail, Geräte werden
abgemeldet).

## Virenprüfung

Ist in der `.env` `CLAMD_SOCKET_DIR` gesetzt (Ordner mit dem Socket des clamd auf dem
Rechner, z. B. `/run/clamav`; Dateiname mit `CLAMD_SOCKET_NAME`, Standard `clamd.ctl`),
hängt `docker-compose.clamav.yml` den Ordner schreibgeschützt in Backend und Worker ein. Jede
hochgeladene Datei läuft dann während des Hochladens durch clamd:

- Fund: Upload abgelehnt, Alarm-Mail „Schadsoftware beim Hochladen abgelehnt“.
- clamd nicht erreichbar: Upload abgelehnt (Meldung „später noch einmal“), Alarm-Mail
  höchstens einmal je Stunde. Nach einem Neustart oder Update des clamd ggf. `backend` und
  `worker` neu starten, falls der Socket-Ordner neu angelegt wurde.
- Dateien über `CLAMD_MAX_BYTES` (Standard knapp 25 MB, die Grenze `StreamMaxLength` des
  clamd) bleiben ungeprüft und stehen im Log. Die Einstellungen des clamd (HestiaCP) bleiben
  unverändert.

Ohne `CLAMD_SOCKET_DIR` (Testserver, Entwicklung) gibt es keine Prüfung.

## Alarm-Mails und Notfall

HUBIplan schickt sofort eine Mail „[HUBIplan-Sicherheit] …“ bei:

- einem Export ab `ALERT_EXPORT_ROWS` Zeilen (Standard 200) und jedem vollständigen
  Datenexport einer Einheit,
- einem neuen Zugang zur Plattform-Organisation,
- einem neu angelegten Superuser,
- im Verbund: Schlüsselwechsel (eigener und der Gegenstellen), Umzug einer Gegenstelle,
  gehäuft ungültige Unterschriften, eine Gegenstelle mit unerwartetem Schlüssel,
- in der App: ab 3 fehlgeschlagenen Freischaltungen der Verwaltung in einer Stunde.
- Backup fehlgeschlagen, unvollständig oder zu alt (siehe Backups; einmal am Tag).

Empfänger: `SECURITY_ALERT_EMAIL` in der `.env` (Komma-Liste), sonst alle Superuser.

**Wenn eine Meldung nicht erwartet war:**

1. Betroffenen Zugang sperren (Benutzer deaktivieren), Sitzungen enden damit.
2. Protokoll der Einheit prüfen: Wer hat was exportiert oder geändert?
3. Bei Verdacht auf einen Einbruch in den Server: Server vom Netz nehmen
   (`docker compose … down`), alle Schlüssel in der `.env` erneuern, Passwörter aller
   Plattform-Zugänge zurücksetzen.
4. Datenpanne melden: binnen 72 Stunden an die Datenschutzaufsicht (NRW: LDI NRW), bei
   hohem Risiko auch die betroffenen Vereine/Mitglieder informieren.

### Instanz vermutlich gehackt: Verbund und App

Wer auf dem Server war, kann die Schlüssel im privaten Speicher kopiert haben. Nach dem
Säubern des Servers (oben, Schritt 3) und vor dem Wiederanschalten:

1. **Verbund-Schlüssel im Notfall wechseln:**
   `docker compose exec backend python manage.py verbund_schluessel_wechseln --notfall`
   (oder Plattform › Einstellungen › Verbund › Notfallwechsel). Der Befehl zeigt den neuen
   Fingerabdruck und welche Partner die Ankündigung bekommen haben.
2. **Partner informieren**, am besten telefonisch: neuen Fingerabdruck vorlesen. Bei
   ihnen bestätigt die Plattformverwaltung den neuen Schlüssel (Plattform › Verbund);
   alle betroffenen Einheiten bekommen eine Mitteilung. Bis dahin ruht der Austausch.
3. **App-Geräte abmelden und Push-Schlüssel erneuern:**
   `docker compose exec backend python manage.py geraete_abmelden --push-schluessel`,
   danach Backend und Worker neu starten. Alle Mitglieder verbinden die App neu (QR-Code),
   die Verwaltung in der App ist damit für alle gesperrt.
4. **Vorstandszugänge:** Passwörter der Plattform- und Vorstandskonten zurücksetzen lassen;
   das meldet auch die Geräte dieser Konten ab.
5. Wer sich über eine andere Instanz anmeldet, braucht danach keine neue Verknüpfung; die
   Anmeldebestätigungen gelten mit dem neuen Schlüssel, sobald der Partner ihn bestätigt hat.

**Django-Admin** (`/admin/`) ist im Server-Betrieb aus. Bei Bedarf in der `.env`
`DJANGO_ADMIN_ENABLED=true` setzen und neu ausrollen, danach wieder entfernen.

Mails gibt es für:

- „Passwort vergessen“ (Link 3 Tage gültig) und Einladungen für neue Konten (Link zum
  Festlegen des Passworts, 7 Tage gültig),
- Zugänge für Mitglieder: Anmeldelink (7 Tage gültig, nur einmal nutzbar). Konten mit
  Vorstandsrollen oder 2FA bekommen statt dessen einen Link zum Festlegen des Passworts.

## Löschfrist

Der Job `members.tasks.purge_expired_members` läuft täglich. Nach Ablauf der in der
Plattform eingestellten Löschfrist bleiben von ehemaligen Mitgliedern nur Name, Vorname,
Geburtsjahr und die Mitgliedszeiträume; die Verbandsnummer wird gelöscht, sobald die Person
nirgends mehr Mitglied ist. Verlangt ein ehemaliges Mitglied die Löschung vorher, gibt es in
der Akte unter „Abläufe“ den Knopf „Daten auf Verlangen löschen“ (gleiches Ergebnis).
Rechnungen und Buchungen bleiben wegen der Aufbewahrungspflicht. Jede Löschung steht auf der
Löschliste (siehe Wiederherstellen).

**Auskunft (Art. 15 DSGVO):** In der Akte unter „Abläufe“ › „Auskunft für dieses Mitglied
(ZIP)“ (Recht „Vollständigen Datenexport erstellen“): Akte, Zusatzfelder, Rechnungen mit PDF,
Mandate, Zuwendungen, versandte Mails, Zugang und Geräte der App, Termin-Rückmeldungen,
Verbund-Meldungen und das Protokoll, ohne Daten anderer Personen.

## Updates

- Dependabot meldet wöchentlich Updates; Django bleibt auf der LTS-Version.
- Kritische Sicherheitslücken innerhalb weniger Tage einspielen, sonst monatlich.
- Vor dem Ausrollen lokal testen: `BACKUP_TEST=1 scripts/test.sh` (in WSL).
  Tests laufen nie auf dem Server; höchstens zwei Testläufe
  gleichzeitig, jeder höchstens 8 Kerne (`scripts/testplatz.sh`).

## Ausrollen mit Rückweg

`deploy/deploy.sh` entpackt die neue Fassung nach `/opt/hubiplan.neu` (mit der
vorhandenen `.env`) und baut dort die Images, während die laufende Fassung weiterläuft.
Scheitert das Bauen, bleibt der Server unverändert. Danach tauscht `server-setup.sh` die
Ordner (`/opt/hubiplan` → `/opt/hubiplan.vorher`) und startet.

Vor dem Tausch laufen die Migrationen als eigener Schritt (Ausgabe mit `-v 2`, höchstens
`MIGRATE_TIMEOUT` Sekunden, Standard 3600, änderbar in der `.env`). Dafür halten Backend,
Worker, Beat und Backup der bisherigen Fassung an, damit keine laufende Abfrage eine
Tabellensperre hält (am 31.10.2026 hing so `ALTER TABLE` auf dem Echtserver); Datenbank und
Redis laufen weiter. Stehen keine Migrationen an (`migrate --check`), entfällt das Anhalten. Hinter nginx hält auch Caddy an, und nginx zeigt solange die Seite
„HUBIplan wird gerade aktualisiert“, die sich alle 5 Sekunden neu lädt
(`deploy/hestia/app-8110.stpl`). Mit eigenem HTTPS wartet Caddy bis zu 30 Sekunden auf das
Backend und zeigt danach dieselbe Seite. Die Oberfläche wiederholt Anfragen bei 502/503/504
von selbst. Schlagen die Migrationen fehl, startet die bisherige Fassung wieder. Wird ein Dienst nicht
„healthy“, geht es automatisch zur vorigen Fassung zurück (Ordner und Images
`…:vorher`); die fehlerhafte bleibt zur Ansicht in `/opt/hubiplan.fehler`.

Läuft die neue Fassung, ist aber fachlich fehlerhaft, von Hand zurück:

```bash
ssh root@<testserver> "cd /opt/hubiplan && sh deploy/zurueck.sh"
ssh administrator@dogado "cd /opt/hubiplan && sudo sh deploy/zurueck.sh"
```

Ein zweiter Aufruf geht wieder vor. Welche Fassung läuft, steht in `/opt/hubiplan/.fassung`.
Datenbank-Migrationen der neueren Fassung bleiben dabei angewendet; Migrationen deshalb
so schreiben, dass die vorige Fassung damit weiterläuft (Spalten erst eine Fassung später
entfernen).
