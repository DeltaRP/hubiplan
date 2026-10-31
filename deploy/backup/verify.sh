#!/bin/sh
# Prüfsumme eines Backups prüfen, bevor es entschlüsselt oder eingespielt wird.
#   verify.sh DATEI                        # DATEI.hmac muss passen
#   verify.sh --ohne-pruefsumme DATEI      # nur für alte Backups ohne .hmac
# Die Prüfsumme (HMAC-SHA256) nutzt einen eigenen Schlüssel BACKUP_HMAC_KEY. Wer nur
# den Backup-Ordner verändern kann, kann damit keine Datei unterschieben.
set -eu

ALLOW_UNSIGNED=0
if [ "${1:-}" = "--ohne-pruefsumme" ]; then
    ALLOW_UNSIGNED=1
    shift
fi
FILE="${1:?Datei fehlt}"

if [ ! -f "$FILE.hmac" ]; then
    if [ "$ALLOW_UNSIGNED" = "1" ]; then
        echo "WARNUNG: $(basename "$FILE") hat keine Prüfsumme (altes Backup)." >&2
        exit 0
    fi
    echo "FEHLER: $(basename "$FILE").hmac fehlt. Alte Backups nur mit --ohne-pruefsumme." >&2
    exit 1
fi
if [ -z "${BACKUP_HMAC_KEY:-}" ]; then
    echo "FEHLER: BACKUP_HMAC_KEY fehlt, die Prüfsumme kann nicht geprüft werden." >&2
    exit 1
fi
expected=$(tr -d ' \n' < "$FILE.hmac")
actual=$(hmac.sh "$FILE")
if [ "$expected" != "$actual" ]; then
    echo "FEHLER: Prüfsumme von $(basename "$FILE") passt nicht – Datei verändert?" >&2
    exit 1
fi
