#!/bin/sh
# Wartet auf die eingestellte Uhrzeit und sichert dann einmal täglich.
# Beim ersten Start ohne vorhandenes Backup wird sofort gesichert.
set -eu

BACKUP_TIME="${BACKUP_TIME:-03:15}"
DIR=/backups

if [ -z "${BACKUP_PUBLIC_KEY:-}" ] && [ -z "${BACKUP_PASSPHRASE:-}" ]; then
    echo "BACKUP_PUBLIC_KEY und BACKUP_PASSPHRASE fehlen – so wird nicht gesichert." >&2
    exit 1
fi
if [ -z "${BACKUP_HMAC_KEY:-}" ]; then
    echo "BACKUP_HMAC_KEY fehlt – ohne Prüfsummen-Schlüssel wird nicht gesichert." >&2
    exit 1
fi

# Stand für die Alarm-Mail des Workers (Volume backup-status, dort nur lesbar):
# state=ok|unvollstaendig|fehler, last_ok=Sekunden seit 1970 des letzten vollständigen
# Backups, text=kurze Beschreibung (Gesamtaudit 31.10.b, INF-F03/F04)
STATUS_DIR="${BACKUP_STATUS_DIR:-/status}"

write_status() {
    [ -d "$STATUS_DIR" ] || return 0
    last_ok=$(sed -n 's/^last_ok=//p' "$STATUS_DIR/status" 2>/dev/null || true)
    [ "$1" = ok ] && last_ok=$(date +%s)
    printf 'state=%s\nlast_ok=%s\ntime=%s\ntext=%s\n' "$1" "${last_ok:-0}" "$(date +%s)" "$2" \
        > "$STATUS_DIR/status.tmp"
    chmod 644 "$STATUS_DIR/status.tmp"
    mv "$STATUS_DIR/status.tmp" "$STATUS_DIR/status"
}

run_once() {
    # backup.sh prüft die Rücksicherung selbst, bevor es alte Backups löscht
    if backup.sh; then
        date +%F > "$DIR/.last-run"
        if [ -f "$DIR/.unvollstaendig" ]; then
            write_status unvollstaendig "$(cat "$DIR/.unvollstaendig")"
        else
            write_status ok ""
        fi
    else
        echo "$(date '+%F %T') FEHLER beim Backup oder Rücksicherungstest" >> "$DIR/backup.log"
        write_status fehler "$(grep FEHLER "$DIR/backup.log" | tail -n 1 | cut -c 1-200)"
    fi
}

# Irgendein Datenbank-Backup (age oder alte Form) genügt (Gesamtaudit 30.10., I-F03)
if [ -z "$(find "$DIR" -maxdepth 1 \( -name 'db_*.sql.gz.enc' -o -name 'db_*.sql.gz.age' \) -print 2>/dev/null | head -n 1)" ]; then
    run_once
fi

while true; do
    now=$(date +%H:%M)
    today=$(date +%F)
    last=$(cat "$DIR/.last-run" 2>/dev/null || true)
    if [ "$now" = "$BACKUP_TIME" ] && [ "$last" != "$today" ]; then
        run_once
    fi
    sleep 30
done
