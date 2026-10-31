#!/usr/bin/env bash
# Rollt den aktuellen Stand (oder eine angegebene Git-Referenz) auf einen Server aus,
# ohne weitere Angaben auf den Testserver. Dessen SSH-Ziel (z. B. root@test.example.org)
# steht nur lokal in ~/.config/hubiplan/testserver, nicht im Repository.
#
#   deploy/deploy.sh               # aktueller Commit (HEAD)
#   deploy/deploy.sh origin/main   # bestimmter Branch/Commit
#
# Echtserver (Dogado, HestiaCP davor; siehe docs/echtbetrieb.md):
#   SSH=/mnt/c/Windows/System32/OpenSSH/ssh.exe DEPLOY_HOST=administrator@dogado DEPLOY_SUDO=1 \
#   SITE_HOST=verein.example.org HUBIPLAN_HINTER_PROXY=1 deploy/deploy.sh
# SITE_HOST, HUBIPLAN_HINTER_PROXY und WEB_PORT wirken nur beim allerersten
# Ausrollen (sie landen dann in der .env auf dem Server).
# BACKUP_PUBLIC_KEY=age1… setzt (oder ersetzt) den öffentlichen Backup-Schlüssel.
#
# Übertragen wird nur, was eingecheckt ist (git archive). Die .env auf dem
# Server bleibt erhalten. SSH-Zugang siehe docs/testserver.md.
#
# Ausgerollt wird nur ein Stand, der vorher lokal mit scripts/test.sh
# erfolgreich getestet wurde (gleicher Git-Tree). Tests laufen nie auf dem Server.
set -euo pipefail

TESTSERVER_DATEI="${HUBIPLAN_TESTSERVER_FILE:-$HOME/.config/hubiplan/testserver}"
HOST="${DEPLOY_HOST:-$(head -n1 "$TESTSERVER_DATEI" 2>/dev/null || true)}"
if [ -z "$HOST" ]; then
    echo "Abbruch: Kein Ziel. DEPLOY_HOST=benutzer@server setzen oder das SSH-Ziel des" >&2
    echo "Testservers in $TESTSERVER_DATEI eintragen." >&2
    exit 1
fi
DIR="${DEPLOY_DIR:-/opt/hubiplan}"
SSH="${SSH:-ssh}"
# Optional: Pfad zum privaten Schlüssel, z. B. DEPLOY_KEY=~/.ssh/hubiplan_dev
if [ -n "${DEPLOY_KEY:-}" ]; then
    SSH_ARGS=(-i "$DEPLOY_KEY" -o IdentitiesOnly=yes)
else
    SSH_ARGS=()
fi
# Als normaler Benutzer anmelden und mit sudo arbeiten (DEPLOY_SUDO=1)
SUDO=""
[ -n "${DEPLOY_SUDO:-}" ] && SUDO="sudo "
# Angaben für eine neue .env (nur beim ersten Ausrollen genutzt)
SETUP_ENV=""
for v in SITE_HOST HUBIPLAN_HINTER_PROXY WEB_PORT BACKUP_PUBLIC_KEY; do
    if [ -n "${!v:-}" ]; then
        case "${!v}" in
            *[!A-Za-z0-9.-]*) echo "Abbruch: $v enthält unerlaubte Zeichen." >&2; exit 1 ;;
        esac
        SETUP_ENV="$SETUP_ENV $v=${!v}"
    fi
done
REF="${1:-HEAD}"
# Einmal auf den Commit festlegen: Geprüft, übertragen und vermerkt wird genau dieser
# Stand, auch wenn sich HEAD oder ein Branch inzwischen ändert (Gesamtaudit 31.10.b, INF-F05)
REF=$(git rev-parse --verify "$REF^{commit}")

TREE=$(git rev-parse "$REF^{tree}")
STATE="${HUBIPLAN_TESTED_FILE:-$HOME/.local/state/hubiplan/tested-trees}"
if ! grep -q "^$TREE " "$STATE" 2>/dev/null; then
    echo "Abbruch: $(git rev-parse --short "$REF") ist nicht lokal getestet." >&2
    echo "Erst scripts/test.sh $REF ausführen (in WSL), dann ausrollen." >&2
    exit 1
fi

echo "Rolle $(git rev-parse --short "$REF") nach $HOST:$DIR aus …"

# Neue Fassung in einen eigenen Ordner neben der laufenden entpacken (mit deren .env).
# Die laufende Fassung bleibt unberührt, bis die neue gebaut ist; server-setup.sh tauscht
# dann die Ordner und geht bei einem Fehler automatisch zurück (Gesamtaudit 30.10.a, I-R01).
NEU="$DIR.neu"
"$SSH" "${SSH_ARGS[@]}" "$HOST" "${SUDO}rm -rf '$NEU' && ${SUDO}mkdir -p '$NEU' && ${SUDO}chmod 755 '$NEU' && if [ -f '$DIR/.env' ]; then ${SUDO}cp -p '$DIR/.env' '$NEU/.env'; fi"
git archive --format=tar "$REF" | "$SSH" "${SSH_ARGS[@]}" "$HOST" "${SUDO}tar -x --no-same-owner -C '$NEU'"
# Welche Fassung läuft (für deploy/zurueck.sh und zur Anzeige)
git rev-parse "$REF" | "$SSH" "${SSH_ARGS[@]}" "$HOST" "${SUDO}tee '$NEU/.fassung' > /dev/null"

"$SSH" "${SSH_ARGS[@]}" "$HOST" "cd '$NEU' && ${SUDO}env$SETUP_ENV ZIEL='$DIR' sh deploy/server-setup.sh"
