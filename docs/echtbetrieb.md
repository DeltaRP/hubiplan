# Echtbetrieb (Dogado)

HUBIplan läuft im Echtbetrieb auf Ralfs Dogado-VPS (Debian 13 mit HestiaCP). In dieser
Anleitung steht `verein.example.org` für die Adresse von HUBIplan und `example.org` für die
Domain des Vereins; die echten Werte stehen nur in Ralfs Unterlagen. Der
Hostinger-Server bleibt [Testserver](testserver.md) mit erfundenen Daten. Neue Stände
gehen erst auf den Test-, dann auf den Echtserver.

Auf dem Dogado-Server laufen viele andere Websites, Mail und Nextcloud. Deshalb belegt
HUBIplan dort weder Port 80 noch 443:

```
Browser ──HTTPS──> nginx (HestiaCP, Let's Encrypt, Vorlage app-8110)
                     └─HTTP──> 127.0.0.1:8110  Caddy (Caddyfile.proxy) ──> backend:8000
```

- `docker-compose.proxy.yml` bindet Caddy nur an `127.0.0.1:${WEB_PORT}` (Standard 8110)
  und startet es mit `deploy/Caddyfile.proxy` (nur HTTP). Aktiv, sobald in der `.env`
  `HUBIPLAN_HINTER_PROXY=1` steht; `deploy/server-setup.sh` hängt die Datei dann an.
- nginx setzt `X-Real-IP` auf die Adresse des Aufrufers; Caddy macht daraus genau einen
  `X-Forwarded-For`-Eintrag. So zählen die Aufrufbremsen je Besucher und nicht für alle
  zusammen.
- Belegte interne Ports auf dem Server (nicht nehmen): 8081, 8084, 8090, 8101, 8102,
  9000, 5432, 6379.

## Erstes Einrichten

Alles von Ralfs PC aus. Anmeldung als `administrator`, gearbeitet wird mit `sudo`.
SSH geht nur mit Schlüssel. Der Schlüssel liegt im Windows-ssh-agent, `~\.ssh\config`
kennt den Alias `dogado`. Aus WSL deshalb das Windows-ssh nehmen
(`SSH=/mnt/c/Windows/System32/OpenSSH/ssh.exe`), aus PowerShell einfach `ssh`.

1. **Lokal testen** wie immer in WSL (`scripts/test.sh`), siehe [testserver.md](testserver.md).
2. **Backup-Schlüsselpaar** auf Ralfs PC erzeugen (`age-keygen`, siehe
   [betrieb.md](betrieb.md), Abschnitt Backups). Der private Schlüssel bleibt auf dem PC
   und im Passwortmanager, auf den Server kommt nur der öffentliche (`age1…`).
3. **Ausrollen** (legt `/opt/hubiplan/.env` mit neuen Schlüsseln an):

   ```bash
   SSH=/mnt/c/Windows/System32/OpenSSH/ssh.exe DEPLOY_HOST=administrator@dogado DEPLOY_SUDO=1 \
   SITE_HOST=verein.example.org HUBIPLAN_HINTER_PROXY=1 \
   BACKUP_PUBLIC_KEY=age1… deploy/deploy.sh
   ```

   `SITE_HOST`, `HUBIPLAN_HINTER_PROXY` und `WEB_PORT` wirken nur beim ersten Mal; danach
   gilt die `.env` auf dem Server. `BACKUP_PUBLIC_KEY` lässt sich jederzeit neu mitgeben.
4. **Hestia einrichten** (nginx-Vorlage, Web-Domain, DNS-A-Eintrag, Let's Encrypt,
   Postfach `verein@example.org` für den Mailversand):

   ```powershell
   Get-Content -Raw deploy\hestia\einrichten.sh | ssh administrator@dogado "sudo env DOMAIN=verein.example.org MAILDOMAIN=example.org ALARM_MAIL=adresse@example.org bash -s"
   ```

   Kennen noch nicht alle Nameserver den neuen DNS-Eintrag (der Zweit-Nameserver holt
   die Zone nur alle 4 Stunden), erst mit `sudo env OHNE_ZERTIFIKAT=1 bash -s` laufen
   lassen und später ohne. Das Skript ist wiederholbar, lädt nginx nur neu und gibt keine Passwörter aus. Das
   Postfach-Passwort steht nur in der `.env`. `ALARM_MAIL` wird zu
   `SECURITY_ALERT_EMAIL` (Sicherheitsalarme, siehe [betrieb.md](betrieb.md)).
5. **Schlüssel sichern:** `MFA_ENCRYPTION_KEY` und `BACKUP_HMAC_KEY` aus
   `/opt/hubiplan/.env` in den Passwortmanager übernehmen, dazu den privaten
   Backup-Schlüssel (siehe [betrieb.md](betrieb.md)). Es sind andere als auf dem Testserver.
6. **Ersten Plattform-Zugang anlegen** (fragt das Passwort ab):

   ```bash
   ssh -t administrator@dogado \
     "cd /opt/hubiplan && sudo docker compose -f docker-compose.server.yml -f docker-compose.proxy.yml exec backend python manage.py createsuperuser"
   ```

   Danach anmelden, 2FA einrichten, Impressum und Datenschutzhinweise der Plattform
   ausfüllen (Hosting-Anbieter: dogado GmbH; Standort des Rechenzentrums laut Vertrag).
7. **Keine Demodaten:** `seed_testdata` auf dem Echtserver nie ausführen.

Echte Mitgliederdaten erst nach der Härtung des Servers
(Skript `deploy/hestia/haerten.sh`).

## Später ausrollen

```bash
SSH=/mnt/c/Windows/System32/OpenSSH/ssh.exe DEPLOY_HOST=administrator@dogado DEPLOY_SUDO=1 deploy/deploy.sh
```

Während des Ausrollens zeigt nginx statt „502 Bad Gateway“ die Seite „Wird gerade
aktualisiert“ (siehe [betrieb.md](betrieb.md), Ausrollen mit Rückweg). Ändern sich die
nginx-Vorlagen (`deploy/hestia/app-8110.*` oder `webseite-8111.*` der Webseite), nach dem
Ausrollen beider einmal einspielen (prüft mit `nginx -t`, sonst zurück):

```powershell
Get-Content -Raw deploy\hestia\vorlagen-erneuern.sh | ssh administrator@dogado "sudo bash -s"
```

Befehle auf dem Server immer mit beiden Compose-Dateien:

```bash
cd /opt/hubiplan
sudo docker compose -f docker-compose.server.yml -f docker-compose.proxy.yml ps
sudo docker compose -f docker-compose.server.yml -f docker-compose.proxy.yml logs -f web backend
```

## Mailversand

HUBIplan verschickt über das Hestia-Postfach `verein@example.org`
(`mail.example.org:587`, STARTTLS). Hestia begrenzt jedes Postfach auf
**100 Mails pro Stunde**. Mit `MAIL_RATE_PER_HOUR=100` in der `.env` drosselt HUBIplan
Rundschreiben selbst (90 je Stunde, der Rest folgt automatisch). Wer schneller versenden
will, hebt das Limit des Postfachs an
(`v-change-mail-account-rate-limit ralf example.org verein 500`) und setzt
`MAIL_RATE_PER_HOUR` auf denselben Wert.

## Mailverteiler

Verteiler-Adressen wie `alle@verein.example.org` (siehe
[rundschreiben.md](rundschreiben.md#mailverteiler-aus-dem-eigenen-mailprogramm)).
Einmalig einrichten:

```powershell
Get-Content -Raw deploy\hestia\verteiler.sh | ssh administrator@dogado "sudo env DOMAIN=verein.example.org ZONE=example.org bash -s"
```

Das Skript legt in Hestia die Mail-Domain `verein.example.org` an (Webseite
bleibt unberührt), den MX-Eintrag in der Zone `example.org`, das
Sammelpostfach `eingang@verein.example.org` mit Catch-all für alle anderen
Adressen der Domain, trägt `INBOUND_*` und `MAIL_RATE_PER_HOUR=100` in die `.env` ein
und startet die Dienste neu. Wiederholbar, gibt keine Passwörter aus. Der
Zweit-Nameserver übernimmt den MX-Eintrag erst innerhalb von 4 Stunden.

## Backups

Wie auf dem Testserver täglich verschlüsselt nach `/opt/hubiplan-backups` mit
Rücksicherungstest (siehe [betrieb.md](betrieb.md)), um 03:15 deutscher Zeit.

Die Server-Sicherungen nach Hetzner (restic, Storage Box) erfassen HUBIplan nicht:
`v-backup-users-restic` sichert nur die Hestia-Benutzer, `nextcloud-restic-backup.sh` nur
Nextcloud. Den zweiten Ort übernimmt `deploy/hestia/hubiplan-restic-backup.sh`: täglich
um 04:30 deutscher Zeit `/opt/hubiplan-backups` und `/opt/hubiplan/.env` in das eigene
Repository `restic-hubiplan` derselben Storage Box (Aufbewahrung 14 Tage, 8 Wochen,
12 Monate; am Monatsersten Stichprobenprüfung und **Probe-Wiederherstellung**: das
neueste Datenbank-Backup samt Prüfsumme und Dateilisten wird aus Hetzner zurückgeholt und mit
dem Original verglichen). Mail an Ralf bei Fehlern und am Monatsersten, Protokoll
`/var/log/hubiplan-restic.log`.

Ziele (Fachfrage 15, Audit 31.10.2026): höchstens **24 Stunden Datenverlust** (tägliches
Backup um 03:15, Kopie nach Hetzner um 04:30) und **Wiederanlauf innerhalb eines Tages**
(neuen Server aufsetzen, Backup aus Hetzner holen, mit dem age-Schlüssel von Ralfs PC
einspielen wie in [betrieb.md](betrieb.md)). Einrichten (einmal):

```powershell
Get-Content -Raw deploy\hestia\hubiplan-restic-backup.sh | ssh administrator@dogado "sudo tee /usr/local/sbin/hubiplan-restic-backup.sh >/dev/null && sudo chmod 700 /usr/local/sbin/hubiplan-restic-backup.sh && sudo /usr/local/sbin/hubiplan-restic-backup.sh einrichten"
```

Fehlermeldungen gehen an die Adresse in `/root/.config/restic/hubiplan.mailto` (sonst an
`root`); einmal anlegen:
`echo adresse@example.org | ssh administrator@dogado "sudo tee /root/.config/restic/hubiplan.mailto"`.

Das restic-Passwort liegt in `/root/.config/restic/hubiplan.pass` und gehört zusätzlich in
den Passwortmanager, ebenso der private age-Schlüssel (nur auf Ralfs PC). Rücksicherung:
`restic restore latest --tag hubiplan --target /tmp/rueck` mit denselben Umgebungsvariablen
wie im Skript, danach wie in [betrieb.md](betrieb.md). `BACKUP_REMOTE` (rsync) bleibt für
Server ohne restic.

**Schutz gegen Löschen:** Wer root auf dem Server hat, kann mit dem SSH-Schlüssel auch das
restic-Repository in der Storage Box löschen. Dagegen helfen die Snapshots der Storage Box:
In der Hetzner Console unter Storage Box › Snapshots einen automatischen Snapshot-Plan
anlegen (z. B. täglich um 06:00, 14 Stück behalten). Snapshots lassen sich nur über die
Hetzner Console bzw. deren API löschen, nicht über den SSH-Zugang des Servers. Sie zählen
zum Speicherplatz der Storage Box. Der Zugang zur Hetzner Console braucht 2FA und gehört
nicht auf den Server.

## Server härten

Der Dogado-Server trägt viele andere Websites. Damit ein Einbruch dort nicht bis zu den
Mitgliederdaten reicht, prüft `deploy/hestia/haerten.sh` die wichtigsten Punkte (ohne
etwas zu ändern) und setzt sie auf Wunsch einzeln um:

```powershell
# nur prüfen
Get-Content -Raw deploy\hestia\haerten.sh | ssh administrator@dogado "sudo bash -s"
# einen Punkt umsetzen: ssh, api, panel, aide
Get-Content -Raw deploy\hestia\haerten.sh | ssh administrator@dogado "sudo PUNKT=ssh bash -s"
```

Nach `PUNKT=ssh` sofort in einem zweiten Fenster prüfen, ob die Anmeldung noch geht.
2FA für die Panel-Konten richtet Ralf selbst im Hestia-Panel ein. Hintergrund und
Befunde: Konzept „Schutz bei Serverhack“ (`konzepte/serverhack-schutz.md` im Projekt).
