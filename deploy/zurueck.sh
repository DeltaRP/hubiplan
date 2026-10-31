#!/bin/sh
# Zurück zur vorigen Fassung (Ordner ZIEL.vorher und Images „:vorher“), z. B. wenn die
# neue Fassung zwar startet, aber fehlerhaft ist. Läuft auf dem Server:
#   ssh root@testserver "cd /opt/hubiplan && sh deploy/zurueck.sh"
#   ssh administrator@dogado "cd /opt/hubiplan && sudo sh deploy/zurueck.sh"
# Ein zweiter Aufruf geht wieder vor (die Fassungen tauschen jeweils die Plätze).
# Datenbank-Migrationen der neueren Fassung bleiben angewendet.
set -eu

ZIEL="$(pwd)"
if [ ! -d "$ZIEL.vorher" ]; then
    echo "Keine vorige Fassung vorhanden ($ZIEL.vorher fehlt)." >&2
    exit 1
fi
PROJEKT=$(grep '^COMPOSE_PROJECT_NAME=' .env | cut -d= -f2 || true)
PROJEKT=${PROJEKT:-$(basename "$ZIEL")}
DATEIEN="-f docker-compose.server.yml"
if grep -q '^HUBIPLAN_HINTER_PROXY=1' .env; then
    DATEIEN="$DATEIEN -f docker-compose.proxy.yml"
fi
if grep -q '^CLAMD_SOCKET_DIR=.' .env; then
    DATEIEN="$DATEIEN -f docker-compose.clamav.yml"
fi
COMPOSE="docker compose -p $PROJEKT $DATEIEN"
EIGENE=$($COMPOSE config --images | grep -v '@sha256:' | sort -u)

echo "Jetzt: $(cat .fassung 2>/dev/null || echo unbekannt)"
echo "Zurück zu: $(cat "$ZIEL.vorher/.fassung" 2>/dev/null || echo unbekannt)"

# Images tauschen: aktuelle <-> :vorher
for img in $EIGENE; do
    basis="${img%%:*}"
    if docker image inspect "$basis:vorher" > /dev/null 2>&1; then
        docker tag "$img" "$basis:tausch" 2> /dev/null || true
        docker tag "$basis:vorher" "$img"
        if docker image inspect "$basis:tausch" > /dev/null 2>&1; then
            docker tag "$basis:tausch" "$basis:vorher"
            docker rmi "$basis:tausch" > /dev/null
        fi
    fi
done

# Ordner tauschen; die .env bleibt die aktuelle (sie enthält höchstens neue Einträge)
cp -p "$ZIEL/.env" "$ZIEL.vorher/.env"
mv "$ZIEL" "$ZIEL.tausch"
mv "$ZIEL.vorher" "$ZIEL"
mv "$ZIEL.tausch" "$ZIEL.vorher"
cd "$ZIEL"

$COMPOSE up -d --remove-orphans --force-recreate --wait --wait-timeout 300
$COMPOSE ps
echo "Läuft jetzt: $(cat .fassung 2>/dev/null || echo unbekannt)"
