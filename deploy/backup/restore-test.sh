#!/bin/sh
# Rücksicherungstest: ein Datenbank-Backup in eine leere Wegwerf-Datenbank einspielen.
# Die laufende Datenbank bleibt unberührt.
#
#   restore-test.sh                          # neuestes Backup mit Passphrase (alte Form)
#   restore-test.sh --klartext DATEI NAME [DATEILISTE]
#                                            # Klartext-Dump (gzip) vor dem Verschlüsseln
#                                            # mit öffentlichem Schlüssel (siehe backup.sh)
# Gibt es zum Backup eine Dateiliste (dateien_STAMP.sha256), prüft der Test außerdem,
# ob jede Datei, auf die die Datenbank zeigt, darin steht (Felder: dateifelder.txt).
set -eu
set -o pipefail

DIR="${BACKUP_DIR:-/backups}"
if [ "${1:-}" = "--klartext" ]; then
    SOURCE="${2:?Datei fehlt}"
    NAME="${3:-$(basename "$SOURCE")}"
    LIST="${4:-}"
    read_dump() { gunzip -c "$SOURCE"; }
else
    if [ -n "${BACKUP_PUBLIC_KEY:-}" ]; then
        echo "Mit BACKUP_PUBLIC_KEY prüft backup.sh die Rücksicherung selbst." >&2
        exit 0
    fi
    SOURCE=$(ls -1t "$DIR"/db_*.sql.gz.enc | head -1)
    NAME=$(basename "$SOURCE")
    # Zuerst die Prüfsumme: eine veränderte Datei wird gar nicht erst entschlüsselt
    verify.sh "$SOURCE"
    read_dump() {
        openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE -in "$SOURCE" \
            | gunzip
    }
    # Dateiliste mit demselben Zeitstempel (db_STAMP.sql.gz.enc -> dateien_STAMP.sha256.enc)
    STAMP=${NAME#db_}
    STAMP=${STAMP%.sql.gz.enc}
    LIST_ENC="$DIR/dateien_$STAMP.sha256.enc"
    LIST=""
fi
TMP=$(mktemp -d)
trap 'pg_ctl -D "$TMP/data" -m immediate stop > /dev/null 2>&1 || true; rm -rf "$TMP"' EXIT

if [ -n "${LIST_ENC:-}" ] && [ -f "$LIST_ENC" ]; then
    verify.sh "$LIST_ENC"
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE \
        -in "$LIST_ENC" -out "$TMP/dateien.sha256"
    LIST="$TMP/dateien.sha256"
fi

initdb -D "$TMP/data" -U restoretest --auth=trust --no-locale --encoding=UTF8 > /dev/null
pg_ctl -D "$TMP/data" -o "-c listen_addresses='' -k $TMP" -w start > /dev/null
createdb -h "$TMP" -U restoretest restore

read_dump | psql -h "$TMP" -U restoretest -d restore -v ON_ERROR_STOP=1 -q > /dev/null

ORGS=$(psql -h "$TMP" -U restoretest -d restore -tAc "SELECT count(*) FROM organizations_organization")
MEMBERS=$(psql -h "$TMP" -U restoretest -d restore -tAc "SELECT count(*) FROM members_membership")

FILES=""
rm -f "$DIR/.unvollstaendig"
FIELDS="${BACKUP_FILE_FIELDS:-/usr/local/share/hubiplan/dateifelder.txt}"
if [ -n "$LIST" ] && [ -f "$FIELDS" ]; then
    # Verweise aus der Datenbank, als Pfad wie in der Dateiliste (./media/…, ./private/…)
    grep -v '^#' "$FIELDS" | while read -r table column root; do
        [ -n "$table" ] || continue
        psql -h "$TMP" -U restoretest -d restore -tA -v ON_ERROR_STOP=1 -c \
            "SELECT './$root/' || \"$column\" FROM \"$table\" WHERE \"$column\" <> ''"
    done | sort -u > "$TMP/verweise"
    # sha256sum schreibt 64 Zeichen Prüfsumme und zwei Leerzeichen vor den Pfad
    cut -c 67- "$LIST" | sort -u > "$TMP/gesichert"
    comm -23 "$TMP/verweise" "$TMP/gesichert" > "$TMP/fehlen"
    MISSING=$(wc -l < "$TMP/fehlen" | tr -d ' ')
    FILES=", Dateien: $(wc -l < "$TMP/gesichert" | tr -d ' ') gesichert, $(wc -l < "$TMP/verweise" | tr -d ' ') Verweise, $MISSING fehlen"
    # Merker für backup.sh/run.sh: Dieses Backup ist unvollständig (Gesamtaudit 31.10.b,
    # INF-F03). Alte Backups bleiben dann liegen, und eine Alarm-Mail geht raus.
    if [ "$MISSING" != "0" ]; then
        echo "$MISSING Dateien fehlen im Backup $NAME" > "$DIR/.unvollstaendig"
        {
            echo "$(date '+%F %T') WARNUNG: $NAME zeigt auf $MISSING Dateien, die nicht im Backup stehen:"
            head -n 20 "$TMP/fehlen" | sed 's/^/    /'
        } >> "$DIR/restore-test.log"
        echo "$(date '+%F %T') WARNUNG: $MISSING Dateien fehlen im Backup $NAME (siehe restore-test.log)" \
            >> "$DIR/backup.log"
    fi
fi

echo "$(date '+%F %T') Rücksicherung ok: $NAME – $ORGS Organisationen, $MEMBERS Mitgliedschaften$FILES" \
    >> "$DIR/restore-test.log"
