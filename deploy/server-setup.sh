#!/bin/sh
# Läuft auf dem Server (wird von deploy.sh aufgerufen), und zwar im Ordner mit der neuen
# Fassung (ZIEL.neu). Ablauf mit Rückweg (Gesamtaudit 30.10.a, I-R01):
#   1. Images der neuen Fassung bauen; die laufende Fassung bleibt unberührt.
#      Schlägt das fehl, ändert sich am Server nichts.
#   1b. Bisherige Fassung anhalten (Datenbank läuft weiter), Migrationen als eigener
#       Schritt; schlägt das fehl, startet die bisherige Fassung wieder.
#   2. Ordner tauschen: ZIEL -> ZIEL.vorher, ZIEL.neu -> ZIEL; Images der bisherigen
#      Fassung bleiben als „:vorher“ erhalten.
#   3. Starten und auf „healthy“ warten. Klappt das nicht, automatisch zurück zur
#      vorigen Fassung (Ordner und Images).
# Von Hand zurück zur vorigen Fassung: deploy/zurueck.sh (siehe docs/betrieb.md).
# Hinweis: Datenbank-Migrationen der neuen Fassung bleiben beim Rückweg angewendet;
# HUBIplan-Migrationen sind so gebaut, dass die vorige Fassung damit weiterläuft.
set -eu

ZIEL="${ZIEL:-$(pwd)}"
NEU="$(pwd)"

# Beim ersten Mal: .env mit zufälligen Geheimnissen anlegen (nur auf dem Server)
if [ ! -f .env ]; then
    echo "Lege .env mit neuen Geheimnissen an …"
    umask 077
    cat > .env <<EOF
SITE_HOST=${SITE_HOST:-$(hostname -f)}
${HUBIPLAN_HINTER_PROXY:+HUBIPLAN_HINTER_PROXY=$HUBIPLAN_HINTER_PROXY}
${WEB_PORT:+WEB_PORT=$WEB_PORT}
DJANGO_SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n/+=')
POSTGRES_PASSWORD=$(openssl rand -base64 32 | tr -d '\n/+=')
EOF
fi
# Neue Einträge späterer Versionen ergänzen, ohne vorhandene zu ändern
if ! grep -q '^BACKUP_PASSPHRASE=' .env; then
    echo "Erzeuge Passphrase für die Backups …"
    echo "BACKUP_PASSPHRASE=$(openssl rand -base64 48 | tr -d '\n/+=')" >> .env
fi
if ! grep -q '^BACKUP_HMAC_KEY=' .env; then
    echo "Erzeuge Schlüssel für die Backup-Prüfsummen …"
    echo "BACKUP_HMAC_KEY=$(openssl rand -base64 48 | tr -d '\n/+=')" >> .env
fi
if ! grep -q '^MFA_ENCRYPTION_KEY=' .env; then
    echo "Erzeuge Schlüssel für die 2FA-Geheimnisse …"
    # Fernet-Schlüssel: 32 Byte, URL-sicheres Base64
    echo "MFA_ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '+/' '-_')" >> .env
fi
if ! grep -q '^REDIS_PASSWORD=' .env; then
    echo "Erzeuge Passwort für Redis …"
    echo "REDIS_PASSWORD=$(openssl rand -base64 32 | tr -d '\n/+=')" >> .env
fi
if ! grep -q '^APP_DB_PASSWORD=' .env; then
    echo "Erzeuge Passwort für die Datenbankrolle der Anwendung …"
    echo "APP_DB_PASSWORD=$(openssl rand -base64 32 | tr -d '\n/+=')" >> .env
fi
# Öffentlicher Backup-Schlüssel (age1…), mitgegeben von deploy.sh
if [ -n "${BACKUP_PUBLIC_KEY:-}" ]; then
    case "$BACKUP_PUBLIC_KEY" in
        age1*) ;;
        *) echo "Abbruch: BACKUP_PUBLIC_KEY ist kein age-Schlüssel (age1…)." >&2; exit 1 ;;
    esac
    umask 077
    grep -v '^BACKUP_PUBLIC_KEY=' .env > .env.neu || true
    echo "BACKUP_PUBLIC_KEY=$BACKUP_PUBLIC_KEY" >> .env.neu
    mv .env.neu .env
    echo "Öffentlicher Backup-Schlüssel gesetzt."
fi
chmod 600 .env
if ! grep -q '^BACKUP_PUBLIC_KEY=age1' .env; then
    echo "HINWEIS: Kein öffentlicher Backup-Schlüssel. Backups nutzen noch die Passphrase"
    echo "         aus der .env, die auch ein Angreifer auf dem Server lesen könnte."
    echo "         Einrichten: siehe docs/betrieb.md, Abschnitt Backups."
fi

# Compose-Projekt wie bisher nach dem Zielordner benennen (Volumes hubiplan_…)
PROJEKT=$(grep '^COMPOSE_PROJECT_NAME=' .env | cut -d= -f2 || true)
PROJEKT=${PROJEKT:-$(basename "$ZIEL")}
DATEIEN="-f docker-compose.server.yml"
# Hinter einem vorhandenen Webserver (Echtserver mit HestiaCP): Caddy nur auf
# 127.0.0.1:WEB_PORT, HTTPS macht der vorgeschaltete Webserver.
if grep -q '^HUBIPLAN_HINTER_PROXY=1' .env; then
    DATEIEN="$DATEIEN -f docker-compose.proxy.yml"
fi
# Virenprüfung mit dem clamd des Rechners (Socket-Ordner in der .env, z. B. /run/clamav)
if grep -q '^CLAMD_SOCKET_DIR=.' .env; then
    DATEIEN="$DATEIEN -f docker-compose.clamav.yml"
fi
COMPOSE="docker compose -p $PROJEKT $DATEIEN"

# Backup-Verzeichnis außerhalb der Docker-Volumes (gehört dem postgres-Benutzer, UID 70)
BACKUP_DIR=$(grep '^BACKUP_DIR=' .env | cut -d= -f2)
BACKUP_DIR=${BACKUP_DIR:-/opt/hubiplan-backups}
mkdir -p "$BACKUP_DIR"
chown 70:70 "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# Selbst gebaute Images (nicht die per Digest festgelegten Postgres/Redis)
EIGENE=$($COMPOSE config --images | grep -v '@sha256:' | sort -u)

images_sichern() {
    # Laufende Fassung als „:vorher“ merken (vor dem Bauen, das die Namen neu vergibt)
    for img in $EIGENE; do
        if docker image inspect "$img" > /dev/null 2>&1; then
            docker tag "$img" "${img%%:*}:vorher"
        fi
    done
}

images_zurueck() {
    for img in $EIGENE; do
        if docker image inspect "${img%%:*}:vorher" > /dev/null 2>&1; then
            docker tag "${img%%:*}:vorher" "$img"
        fi
    done
}

starten() {
    $COMPOSE up -d --remove-orphans --wait --wait-timeout 300 || return 1
    # Compose ersetzt einen Container nicht immer, obwohl sein Image neu gebaut wurde
    # (auf dem Echtserver beobachtet). Container, die noch ein älteres Image nutzen als
    # ihr Tag, gezielt neu erstellen. Sonst käme z. B. ein neues Frontend nicht an.
    VERALTET=""
    for service in $($COMPOSE config --services); do
        container=$($COMPOSE ps -q "$service" | head -n1)
        [ -n "$container" ] || continue
        name=$(docker inspect -f '{{.Config.Image}}' "$container")
        laeuft=$(docker inspect -f '{{.Image}}' "$container")
        aktuell=$(docker image inspect -f '{{.Id}}' "$name" 2>/dev/null || true)
        if [ -n "$aktuell" ] && [ "$laeuft" != "$aktuell" ]; then
            VERALTET="$VERALTET $service"
        fi
    done
    if [ -n "$VERALTET" ]; then
        echo "Neu erstellen (altes Image):$VERALTET"
        # shellcheck disable=SC2086
        $COMPOSE up -d --no-deps --force-recreate --wait --wait-timeout 300 $VERALTET || return 1
    fi
}

# Commit der Fassung für den Quellcode-Link auf /lizenz (AGPL § 13), aus deploy.sh
if [ -f .fassung ]; then
    mkdir -p frontend/public/lizenzen
    cp .fassung frontend/public/lizenzen/fassung.txt
fi

# 1. Bauen, während die bisherige Fassung weiterläuft
images_sichern
if ! $COMPOSE build; then
    echo "FEHLER: Bauen fehlgeschlagen. Die laufende Fassung bleibt unverändert." >&2
    images_zurueck
    exit 1
fi

# 1b. Migrationen als eigener Schritt, bevor die neue Fassung startet. Vorher halten
#     Backend, Worker, Beat und Backup der bisherigen Fassung an: Laufende Abfragen (z. B. der
#     minütliche Mailabruf im Worker) halten sonst Tabellensperren, und ALTER TABLE wartet
#     endlos (Dogado 31.10.2026). Hinter nginx hält auch Caddy an, damit nginx die Seite
#     „Wird gerade aktualisiert“ zeigt (deploy/hestia/app-8110.stpl); mit eigenem HTTPS
#     wartet Caddy auf das Backend. Datenbank und Redis laufen weiter.
#     Stehen keine Migrationen an, entfällt das Anhalten.
#     Schlägt das Migrieren fehl, startet die bisherige Fassung wieder (Migrationen sind
#     so geschrieben, dass sie mit schon angewendeten weiterläuft, siehe docs/betrieb.md).
MIGRATE_TIMEOUT=$(grep '^MIGRATE_TIMEOUT=' .env | cut -d= -f2 || true)
MIGRATE_TIMEOUT=${MIGRATE_TIMEOUT:-3600}
ANHALTEN="backend worker beat backup"
if grep -q '^HUBIPLAN_HINTER_PROXY=1' .env; then
    ANHALTEN="web $ANHALTEN"
fi
# Laufen Datenbank und Redis schon, nicht anfassen (--no-deps)
OHNE_ABH=""
if [ -n "$($COMPOSE ps -q --status running postgres)" ] \
    && [ -n "$($COMPOSE ps -q --status running redis)" ]; then
    OHNE_ABH="--no-deps"
fi
# Stehen keine Migrationen an, läuft die bisherige Fassung bis zum Austausch weiter
# (die Prüfung liest nur). Im Zweifel (Fehler bei der Prüfung) wird angehalten.
# shellcheck disable=SC2086,SC2016
if [ -n "$OHNE_ABH" ] && $COMPOSE run -T --rm --no-deps --entrypoint sh backend -c \
    'DATABASE_URL="${MIGRATE_DATABASE_URL:-$DATABASE_URL}" DATABASE_APP_ROLE= python manage.py migrate --check --noinput > /dev/null 2>&1'; then
    echo "Keine offenen Migrationen, die bisherige Fassung läuft bis zum Austausch weiter."
    ANHALTEN=""
fi
ANGEHALTEN=""
for service in $ANHALTEN; do
    ANGEHALTEN="$ANGEHALTEN $($COMPOSE ps -q --status running "$service" 2> /dev/null || true)"
done
ANGEHALTEN=$(echo $ANGEHALTEN)

wieder_starten() {
    if [ -n "$ANGEHALTEN" ]; then
        echo "Starte die bisherige Fassung wieder …" >&2
        # shellcheck disable=SC2086
        docker start $ANGEHALTEN > /dev/null || true
    fi
}

if [ -n "$ANGEHALTEN" ]; then
    echo "Halte die bisherige Fassung an ($ANHALTEN) …"
    # Der Worker darf laufende Aufträge beenden
    # shellcheck disable=SC2086
    if ! docker stop -t 60 $ANGEHALTEN > /dev/null; then
        echo "FEHLER: Anhalten fehlgeschlagen." >&2
        images_zurueck
        wieder_starten
        exit 1
    fi
fi
echo "Migrationen (höchstens $MIGRATE_TIMEOUT s) …"
# shellcheck disable=SC2086
if ! timeout "$MIGRATE_TIMEOUT" $COMPOSE run -T --rm $OHNE_ABH --name "$PROJEKT-migration" \
    -e MIGRATE_VERBOSITY=2 backend true; then
    docker rm -f "$PROJEKT-migration" > /dev/null 2>&1 || true
    echo "FEHLER: Migrationen fehlgeschlagen. Die bisherige Fassung läuft weiter." >&2
    images_zurueck
    wieder_starten
    exit 1
fi

# 2. Ordner tauschen (bei einem Ausrollen in denselben Ordner entfällt das)
if [ "$NEU" != "$ZIEL" ]; then
    rm -rf "$ZIEL.vorher"
    if [ -d "$ZIEL" ]; then
        mv "$ZIEL" "$ZIEL.vorher"
    fi
    mv "$NEU" "$ZIEL"
    cd "$ZIEL"
fi

# 3. Starten; bei Fehler zurück zur vorigen Fassung
if ! starten; then
    echo "FEHLER: Die neue Fassung startet nicht. Zurück zur vorigen Fassung …" >&2
    $COMPOSE logs --tail 40 backend >&2 || true
    if [ -d "$ZIEL.vorher" ]; then
        rm -rf "$ZIEL.fehler"
        mv "$ZIEL" "$ZIEL.fehler"
        mv "$ZIEL.vorher" "$ZIEL"
        # .env der neuen Fassung behalten: sie enthält höchstens neue Einträge
        cp -p "$ZIEL.fehler/.env" "$ZIEL/.env"
        cd "$ZIEL"
        images_zurueck
        if starten; then
            echo "Vorige Fassung läuft wieder. Die fehlerhafte liegt in $ZIEL.fehler." >&2
        else
            echo "FEHLER: Auch die vorige Fassung startet nicht – bitte von Hand prüfen." >&2
        fi
    fi
    exit 1
fi

# Unbenannte alte Images löschen; die „:vorher“-Fassung bleibt für den Rückweg
docker image prune -f > /dev/null
rm -rf "$ZIEL.fehler"
$COMPOSE ps
