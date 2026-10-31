#!/bin/bash
# Zweiter Backup-Ort für HUBIplan auf dem Echtserver (Dogado): kopiert die täglichen,
# schon mit age verschlüsselten HUBIplan-Backups und die .env per restic in die
# Hetzner Storage Box. Gebaut wie /usr/local/sbin/nextcloud-restic-backup.sh
# (gleiche Storage Box, gleicher SSH-Zugang „storagebox“, eigenes Repository).
#
# Einrichten (einmal, von Ralfs PC in PowerShell):
#   Get-Content -Raw deploy\hestia\hubiplan-restic-backup.sh | ssh administrator@dogado "sudo tee /usr/local/sbin/hubiplan-restic-backup.sh >/dev/null && sudo chmod 700 /usr/local/sbin/hubiplan-restic-backup.sh && sudo /usr/local/sbin/hubiplan-restic-backup.sh einrichten"
#
# „einrichten“ legt bei Bedarf ein eigenes restic-Passwort an (nur auf dem Server, Datei
# siehe PASSDATEI), legt das Repository an, schreibt /etc/cron.d/hubiplan-restic und
# macht eine erste Sicherung. Das Passwort danach zusätzlich im Passwortmanager ablegen,
# sonst ist die Kopie bei einem Totalausfall des Servers nicht lesbar.
#
# Fehlermeldungen gehen an die Adresse in /root/.config/restic/hubiplan.mailto (sonst root):
#   echo adresse@example.org | ssh administrator@dogado "sudo tee /root/.config/restic/hubiplan.mailto"
#
# Ohne Argument: Sicherung (so ruft cron es täglich auf). Gibt keine Passwörter aus.
set -u
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

export RESTIC_REPOSITORY=${RESTIC_REPOSITORY:-sftp:storagebox:restic-hubiplan}
export RESTIC_CACHE_DIR=/root/.cache/restic
PASSDATEI=/root/.config/restic/hubiplan.pass
export RESTIC_PASSWORD_FILE=$PASSDATEI
# Empfänger der Fehlermeldungen: eine Adresse in MAILDATEI (nur auf dem Server), sonst root
MAILDATEI=/root/.config/restic/hubiplan.mailto
MAILTO=${MAILTO:-$(head -n1 "$MAILDATEI" 2>/dev/null || echo root)}
LOG=/var/log/hubiplan-restic.log
BACKUPS=/opt/hubiplan-backups
ENVDATEI=/opt/hubiplan/.env
CRON=/etc/cron.d/hubiplan-restic

einrichten() {
    command -v restic >/dev/null || { echo "restic fehlt (apt install restic)"; exit 1; }
    if [ ! -s "$PASSDATEI" ]; then
        install -d -m 700 "$(dirname "$PASSDATEI")"
        (umask 077 && openssl rand -base64 33 | tr -d '\n' > "$PASSDATEI")
        echo "Neues restic-Passwort angelegt: $PASSDATEI"
        echo "  -> bitte in den Passwortmanager übernehmen (sudo cat $PASSDATEI)"
    fi
    chmod 600 "$PASSDATEI"
    if restic cat config >/dev/null 2>&1; then
        echo "Repository $RESTIC_REPOSITORY gibt es schon."
    else
        restic init || { echo "FEHLER: restic init"; exit 1; }
    fi
    # Das HUBIplan-Backup läuft um 03:15 (Europe/Berlin) samt Rücksicherungstest;
    # die Kopie danach um 04:30 deutscher Zeit (cron läuft auf UTC, daher die Prüfung)
    cat > "$CRON" <<'EOF'
# HUBIplan-Backups (restic -> Hetzner Storage Box) täglich 04:30 deutscher Zeit
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=root
30 2,3 * * * root [ "$(TZ=Europe/Berlin date +\%H)" = "04" ] && /usr/local/sbin/hubiplan-restic-backup.sh >/dev/null 2>&1
EOF
    chmod 644 "$CRON"
    echo "Zeitplan: $CRON"
    sichern
    echo "Ergebnis: $(tail -n 1 "$LOG")"
}

# Monatliche Probe (Fachfrage 15, Audit 31.10.): das neueste Datenbank-Backup und seine
# Dateiliste aus Hetzner zurückholen und Byte für Byte mit dem Original vergleichen.
# Zeigt, dass die Kopie vollständig übertragen und mit dem restic-Passwort lesbar ist.
# (Entschlüsseln geht nur mit dem age-Schlüssel auf Ralfs PC; das prüft der tägliche
# Rücksicherungstest vor dem Verschlüsseln.)
probe() {
    local neu ziel name ok=0
    neu=$(ls -1t "$BACKUPS"/db_*.sql.gz.age 2>/dev/null | head -n 1)
    [ -n "$neu" ] || { log "FEHLER: Probe: kein Datenbank-Backup gefunden"; return 1; }
    name=$(basename "$neu")
    ziel=$(mktemp -d)
    if restic restore latest --tag hubiplan --target "$ziel" \
        --include "$BACKUPS/$name" --include "$BACKUPS/$name.hmac" \
        --include "$BACKUPS/dateien_*.sha256.age" -q >> "$LOG" 2>&1; then
        for f in "$neu" "$neu.hmac"; do
            [ -e "$f" ] || continue
            cmp -s "$f" "$ziel$f" || { log "FEHLER: Probe: $(basename "$f") weicht ab"; ok=1; }
        done
        listen=$(find "$ziel$BACKUPS" -name 'dateien_*.sha256.age' 2>/dev/null | wc -l)
        [ "$ok" = 0 ] && log "Probe ok: $name aus Hetzner zurückgeholt und gleich ($listen Dateilisten)"
    else
        log "FEHLER: Probe: restic restore"
        ok=1
    fi
    rm -rf "$ziel"
    return $ok
}

sichern() {
    exec 9>/run/hubiplan-restic.lock
    flock -n 9 || { echo "$(date -Is) läuft bereits" >> "$LOG"; exit 1; }
    REP=$(mktemp)
    FEHLER=0
    log() { echo "$(date '+%F %T') $*" | tee -a "$LOG" >> "$REP"; }
    log "=== Start HUBIplan-Sicherung"
    # Ist das heutige HUBIplan-Backup da? Sonst trotzdem kopieren, aber melden
    if [ "$(cat "$BACKUPS/.last-run" 2>/dev/null)" != "$(TZ=Europe/Berlin date +%F)" ]; then
        log "WARNUNG: HUBIplan-Backup von heute fehlt (siehe $BACKUPS/backup.log)"
        FEHLER=1
    fi
    nice -n 10 ionice -c3 restic backup --host "$(hostname -f)" --tag hubiplan -q \
        "$BACKUPS" "$ENVDATEI" >> "$LOG" 2>&1 \
        && log "restic backup ok" || { log "FEHLER: restic backup (Exit $?)"; FEHLER=1; }
    restic forget --tag hubiplan --keep-daily 14 --keep-weekly 8 --keep-monthly 12 \
        --group-by host,tags --prune -q >> "$LOG" 2>&1 \
        && log "Aufbewahrung/prune ok" || { log "FEHLER: forget/prune"; FEHLER=1; }
    if [ "$(date +%d)" = "01" ]; then
        restic check --read-data-subset=10% >> "$LOG" 2>&1 \
            && log "check ok" || { log "FEHLER: check"; FEHLER=1; }
        probe || FEHLER=1
    fi
    touch /var/lib/hubiplan-restic.last-run
    [ $FEHLER = 0 ] && touch /var/lib/hubiplan-restic.last-ok
    log "=== Ende (Fehler: $FEHLER)"
    # Mail nur bei Fehlern und am Monatsersten, damit das Postfach ruhig bleibt
    if [ $FEHLER != 0 ] || [ "$(date +%d)" = "01" ]; then
        S="HUBIplan-Sicherung $( [ $FEHLER = 0 ] && echo OK || echo FEHLER ) $(hostname -s) $(date +%F)"
        mail -s "$S" "$MAILTO" < "$REP" || true
    fi
    rm -f "$REP"
    return $FEHLER
}

case "${1:-}" in
    einrichten) einrichten ;;
    "") sichern; exit $? ;;
    *) echo "Aufruf: $0 [einrichten]"; exit 2 ;;
esac
