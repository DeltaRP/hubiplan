#!/usr/bin/env bash
# Zentrales Test-Skript: prüft einen Commit lokal in WSL (Docker), bevor er
# ausgerollt wird. Alle Sitzungen nutzen nur dieses Skript.
#
#   scripts/test.sh [Git-Referenz] [pytest-Argumente]
#
# - Backend: ruff und pytest gegen PostgreSQL 18 in Wegwerf-Containern
# - Frontend: Typprüfung, Lint, Formatierung und Tests im Node-Container
# - BACKUP_TEST=1: zusätzlich Backup und Rücksicherung mit Demodaten
#
# Es läuft nur, was eingecheckt ist (git archive). Nach Erfolg wird der Stand
# (Git-Tree) als getestet vermerkt; deploy/deploy.sh rollt nur solche Stände aus.
#
# Die Frontend-Prüfungen ohne Tests (Typen, Lint, Format) laufen gleichzeitig mit dem
# Backend (TEST_PARALLEL=0: alles nacheinander).
#
# Regeln: Tests laufen nie auf dem Testserver. Höchstens zwei Testläufe gleichzeitig
# (alle Projekte), jeder höchstens 8 Kerne: das Skript holt sich einen Platz über
# scripts/testplatz.sh und bindet alle Container an dessen Kerne.
set -euo pipefail

if [ -z "${TESTPLATZ:-}" ]; then
    exec "$(dirname "$0")/testplatz.sh" "$0" "$@"
fi

REF="${1:-HEAD}"
shift || true

# Ergebnis immer eindeutig melden, auch wenn ein Aufrufer den Exit-Code nicht sieht
RESULT_OK=0
WORK=""
on_exit() {
    local rc=$?
    [ -n "$WORK" ] && cleanup
    if [ "$RESULT_OK" != 1 ]; then
        [ "$rc" -eq 0 ] && rc=1
        echo "FEHLGESCHLAGEN (Exit $rc): ${SHA:-$REF} ist nicht getestet." >&2
        exit "$rc"
    fi
}
trap on_exit EXIT

# Den Commit sicher auflösen. Eine volle SHA löst git rev-parse auch dann auf,
# wenn der Commit im Klon fehlt; deshalb mit --verify gegen ^{commit} prüfen.
resolve() { git rev-parse --verify --quiet "$REF^{commit}" 2> /dev/null || true; }
COMMIT=$(resolve)
if [ -z "$COMMIT" ]; then
    echo "$REF fehlt im Klon, hole von allen Remotes …"
    git fetch --all --quiet || echo "Warnung: git fetch ist fehlgeschlagen." >&2
    COMMIT=$(resolve)
fi
if [ -z "$COMMIT" ]; then
    echo "Abbruch: $REF ist auch nach git fetch nicht im Klon $(pwd)." >&2
    echo "In WSL holt der Klon vom Windows-Checkout: dort erst git fetch origin, dann erneut testen." >&2
    exit 2
fi
REF="$COMMIT"
SHA=$(git rev-parse --short "$COMMIT")
TREE=$(git rev-parse "$COMMIT^{tree}")

# Kerne vom Testplatz (höchstens 8); alle Container laufen nur auf dessen Kernen
WORKERS="$TEST_KERNE"
CPUS="--cpuset-cpus=$TESTPLATZ_CPUS"
PYTEST_ARGS="${*:--q}"

ID="hubiplan-test-$(date +%s)-$$"
# Eigene Image-Namen je Lauf: zwei gleichzeitige Läufe dürfen sich nicht überschreiben
BACKEND_IMG="hubiplan-test-backend:$ID"
BACKUP_IMG="hubiplan-test-backup:$ID"
FE_PID=""
WORK=$(mktemp -d)
cleanup() {
    [ -n "$FE_PID" ] && kill "$FE_PID" 2> /dev/null && wait "$FE_PID" 2> /dev/null
    docker rm -f "$ID-fe" > /dev/null 2>&1 || true
    docker rm -f "$ID-db" > /dev/null 2>&1 || true
    docker network rm "$ID" > /dev/null 2>&1 || true
    docker volume rm "$ID-backups" > /dev/null 2>&1 || true
    docker volume rm "$ID-data" > /dev/null 2>&1 || true
    # Dateien aus Containern ggf. mit deren Rechten entfernen
    rm -rf "$WORK" 2> /dev/null         || docker run --rm -v "$WORK:/w" node:24-alpine rm -rf /w/backend /w/frontend /w/deploy /w/scripts
    rm -rf "$WORK"
    docker image rm "$BACKEND_IMG" "$BACKUP_IMG" > /dev/null 2>&1 || true
}

echo "Teste $SHA ($(git log -1 --format=%s "$COMMIT")) lokal mit $WORKERS Kernen …"
git archive --format=tar "$REF" backend frontend deploy/backup | tar -x -C "$WORK"
start=$(date +%s)

# --- Frontend, Teil 1 (im Hintergrund, während das Backend testet) ---
# Installieren, Typprüfung, Lint und Formatierung hängen nicht an Zeitlimits. Die
# Vitest-Tests laufen erst danach allein: mit dem Backend zusammen auf denselben
# Kernen werden ihre Wartezeiten (findBy…) zu knapp.
fe_run() {
    docker run --rm --name "$ID-fe" "$CPUS" -v "$WORK/frontend:/app" -v "$WORK/backend:/backend:ro" \
        -v hubiplan-npm-cache:/root/.npm -w /app node:24-alpine sh -c "$1"
}
fe_checks() {
    fe_run "npm ci --no-audit --no-fund --loglevel=error > /dev/null \
        && npm run -s typecheck && npm run -s lint > /dev/null && npm run -s format:check > /dev/null \
        && npm run -s i18n:check"
    echo "Frontend: Typprüfung, Lint, Format ok"
}
if [ "${TEST_PARALLEL:-1}" = 1 ]; then
    fe_checks > "$WORK/frontend.log" 2>&1 &
    FE_PID=$!
fi

# --- Backend ---
# Die Schichten mit den Abhängigkeiten nutzt Docker über die Läufe hinweg wieder
docker build -q --build-arg REQUIREMENTS=requirements-dev.txt -t "$BACKEND_IMG" "$WORK/backend" > /dev/null
docker network create "$ID" > /dev/null
# Dasselbe festgeschriebene Datenbank-Image wie auf dem Server (docker-compose.server.yml)
PG_IMAGE=$(git show "$REF:docker-compose.server.yml" | grep -m1 -oE 'image: postgres:[0-9][^ ]*' | cut -d' ' -f2)
docker run -d --name "$ID-db" --network "$ID" "$CPUS" --tmpfs /var/lib/postgresql \
    -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=test \
    "$PG_IMAGE" -c max_connections=200 > /dev/null
until docker exec "$ID-db" pg_isready -U test > /dev/null 2>&1; do sleep 1; done
# App-Rolle vorab anlegen, damit parallele Test-Datenbanken nicht darum konkurrieren
docker exec "$ID-db" psql -q -U test -d test -c \
    "CREATE ROLE hubiplan_app NOLOGIN NOSUPERUSER NOBYPASSRLS" > /dev/null

docker run --rm "$CPUS" --entrypoint sh "$BACKEND_IMG" \
    -c "ruff check . && ruff format --check . > /dev/null"
echo "Backend: ruff ok"
# Übersetzung (konzepte/englisch.md): bis zur Abnahme nur Bericht, danach --streng
docker run --rm "$CPUS" -e DJANGO_DEBUG=true -e DJANGO_SECRET_KEY=nur-test --entrypoint sh \
    "$BACKEND_IMG" -c "python manage.py uebersetzung_pruefen"

# Webserver-Konfiguration (Caddy, nginx-Vorlagen für HestiaCP), aus dem geprüften Stand
if git cat-file -e "$REF:scripts/pruefe-proxy.sh" 2> /dev/null; then
    git archive --format=tar "$REF" scripts/pruefe-proxy.sh deploy/web.Dockerfile deploy/Caddyfile \
        deploy/Caddyfile.proxy deploy/caddy deploy/hestia | tar -x -C "$WORK"
    "$WORK/scripts/pruefe-proxy.sh" "$WORK" "$CPUS"
fi

# Testdatenbank: einmal migrieren und je Worker kopieren (CREATE DATABASE … TEMPLATE, 0,2 s)
# statt in jedem Worker alle Migrationen (je ~40 s Rechenzeit). Die migrierte Datenbank
# wird als Vorlage zwischengespeichert. Ihr Schlüssel umfasst alles, was den Stand nach
# migrate bestimmt: Migrationen, die von ihnen eingebundenen Module, Modelle, apps.py,
# Einstellungen, Abhängigkeiten und das Datenbank-Image. TEST_DB_CACHE=0: ohne Vorlage.
db_key() {
    local mods files
    # Module, die Migrationen einbinden (z. B. core.rls, exchange.models)
    mods=$(git grep -h -E '^(from|import) [a-z_]+\.[a-z_.]+' "$REF" -- 'backend/*/migrations/*.py' \
        | sed -E 's/^(from|import) ([a-z_.]+).*/\2/' | sort -u | sed 's#\.#/#g; s#^#backend/#; s#$#.py#')
    files=$(git ls-tree -r --name-only "$REF" -- backend \
        | grep -E '/migrations/|/models/|models[a-z_]*\.py$|/apps\.py$|^backend/config/settings\.py$|^backend/requirements' || true)
    { printf '%s\n' "$PG_IMAGE"; printf '%s\n' $mods $files | sort -u \
        | xargs git ls-tree "$REF" -- 2> /dev/null; } | sha256sum | cut -c1-16
}
if [ -d /mnt/e/tmp ]; then DB_CACHE_DEFAULT=/mnt/e/tmp/hubiplan-tests/db-vorlagen
else DB_CACHE_DEFAULT="$HOME/.cache/hubiplan-test-db"; fi
DB_CACHE="${TEST_DB_CACHE:-$DB_CACHE_DEFAULT}"
TEST_DB=test_test   # so nennt pytest-django die Testdatenbank zu „test“, mit -n dann test_test_gwN
docker exec "$ID-db" createdb -U test "$TEST_DB"
dbstart=$(date +%s)
DUMP=""
if [ "$DB_CACHE" != 0 ]; then
    mkdir -p "$DB_CACHE"
    DUMP="$DB_CACHE/$(db_key).dump"
fi
if [ -n "$DUMP" ] && [ -s "$DUMP" ] && docker exec -i "$ID-db" pg_restore -U test -d "$TEST_DB" -1 < "$DUMP"; then
    echo "Backend: Testdatenbank aus der Vorlage ($(($(date +%s) - dbstart)) s)"
else
    if [ -n "$DUMP" ] && [ -s "$DUMP" ]; then
        echo "Warnung: Vorlage $DUMP ließ sich nicht einspielen, migriere neu." >&2
        docker exec "$ID-db" dropdb -U test "$TEST_DB"
        docker exec "$ID-db" createdb -U test "$TEST_DB"
    fi
    docker run --rm --network "$ID" "$CPUS" \
        -e DJANGO_DEBUG=true -e DJANGO_SECRET_KEY=nur-test \
        -e DATABASE_URL="postgres://test:test@$ID-db:5432/$TEST_DB" \
        --entrypoint python "$BACKEND_IMG" manage.py migrate -v0
    if [ -n "$DUMP" ]; then
        # Erst fertig schreiben, dann umbenennen: ein paralleler Lauf liest nie eine halbe Datei
        docker exec "$ID-db" pg_dump -U test -Fc "$TEST_DB" > "$DUMP.$ID" && mv "$DUMP.$ID" "$DUMP"
        rm -f "$DUMP.$ID"
        # Nur die zehn neuesten Vorlagen behalten
        ls -1t "$DB_CACHE"/*.dump 2> /dev/null | tail -n +11 | xargs -r rm -f
    fi
    echo "Backend: Testdatenbank migriert ($(($(date +%s) - dbstart)) s)"
fi
for i in $(seq 0 $((WORKERS - 1))); do
    docker exec "$ID-db" psql -q -U test -d test -c \
        "CREATE DATABASE ${TEST_DB}_gw$i TEMPLATE $TEST_DB" > /dev/null
done

# --reuse-db: die Kopien nehmen (migrate prüft nur noch, dass nichts fehlt).
# --maxschedchunk=2: kleine Pakete, damit die langsamen Tests (zuerst gesammelt, siehe
# tests/conftest.py) auf verschiedene Worker verteilt werden.
docker run --rm --network "$ID" "$CPUS" \
    -e DJANGO_DEBUG=true -e DJANGO_SECRET_KEY=nur-test \
    -e DATABASE_URL="postgres://test:test@$ID-db:5432/test" \
    -v "$WORK/deploy/backup/dateifelder.txt:/deploy/backup/dateifelder.txt:ro" \
    --entrypoint pytest "$BACKEND_IMG" -n "$WORKERS" --reuse-db --maxschedchunk=2 $PYTEST_ARGS
echo "Backend: Tests ok ($(($(date +%s) - start)) s)"

# --- Frontend, Teil 2 ---
fstart=$(date +%s)
if [ -n "$FE_PID" ]; then
    rc=0
    wait "$FE_PID" || rc=$?
    FE_PID=""
    cat "$WORK/frontend.log"
    [ "$rc" -eq 0 ] || exit "$rc"
else
    fe_checks
fi
fe_run "npx vitest run --maxWorkers=$WORKERS --reporter=dot"
echo "Frontend: ok ($(($(date +%s) - fstart)) s nach dem Backend)"

# --- Backup und Rücksicherung (optional) ---
if [ "${BACKUP_TEST:-0}" = "1" ]; then
    docker build -q -t "$BACKUP_IMG" "$WORK/deploy/backup" > /dev/null
    docker exec "$ID-db" psql -q -U test -d test -c "CREATE DATABASE hubiplan" > /dev/null
    docker run --rm --network "$ID" "$CPUS" -e DJANGO_DEBUG=true \
        -e DJANGO_SECRET_KEY=nur-test -e DATABASE_URL="postgres://test:test@$ID-db:5432/hubiplan" \
        --entrypoint sh "$BACKEND_IMG" \
        -c "python manage.py migrate -v0 && python manage.py seed_testdata --password Test-123456 > /dev/null"
    docker volume create "$ID-backups" > /dev/null
    # Der Backup-Dienst läuft als Benutzer postgres (70)
    docker run --rm --user 0 -v "$ID-backups:/backups" --entrypoint chown         "$BACKUP_IMG" 70:70 /backups
    docker run --rm --network "$ID" "$CPUS" -v "$ID-backups:/backups" \
        -e PGHOST="$ID-db" -e PGUSER=test -e PGPASSWORD=test -e PGDATABASE=hubiplan \
        -e BACKUP_PASSPHRASE=nur-ein-test -e BACKUP_HMAC_KEY=nur-ein-test --entrypoint sh "$BACKUP_IMG" \
        -c "backup.sh > /dev/null && tail -1 /backups/restore-test.log"
    # hmac.sh rechnet ohne Schlüssel in der Befehlszeile, muss aber wie openssl rechnen
    docker run --rm "$CPUS" --tmpfs /tmp --entrypoint sh "$BACKUP_IMG" \
        -c 'set -e
            head -c 200000 /dev/urandom > /tmp/datei; : > /tmp/leer
            for key in nur-ein-test "$(head -c 32 /dev/urandom | od -An -tx1 | tr -d " \n")" \
                       "$(head -c 70 /dev/urandom | od -An -tx1 | tr -d " \n")"; do
                for f in /tmp/datei /tmp/leer; do
                    a=$(openssl dgst -sha256 -mac HMAC -macopt "key:$key" -r "$f" | cut -d" " -f1)
                    b=$(BACKUP_HMAC_KEY="$key" hmac.sh "$f")
                    [ "$a" = "$b" ] || { echo "hmac.sh weicht von openssl ab" >&2; exit 1; }
                done
            done'
    echo "Backup: hmac.sh stimmt mit openssl überein"
    # Ein abgebrochener Dump darf kein Backup hinterlassen und muss fehlschlagen
    docker run --rm --network "$ID" "$CPUS" -v "$ID-backups:/backups" \
        -e PGHOST="$ID-db" -e PGUSER=test -e PGPASSWORD=test -e PGDATABASE=gibt_es_nicht \
        -e BACKUP_PASSPHRASE=nur-ein-test -e BACKUP_HMAC_KEY=nur-ein-test --entrypoint sh "$BACKUP_IMG" \
        -c 'n=$(ls /backups/db_*.enc | wc -l)
            if backup.sh > /dev/null 2>&1; then echo "Backup trotz Fehler gemeldet" >&2; exit 1; fi
            [ "$(ls /backups/db_*.enc | wc -l)" = "$n" ] && ! ls /backups/*.tmp > /dev/null 2>&1'
    echo "Backup: abgebrochener Dump wird erkannt"
    # Eine veränderte Backup-Datei darf nicht eingespielt werden
    docker run --rm --network "$ID" "$CPUS" -v "$ID-backups:/backups" \
        -e BACKUP_PASSPHRASE=nur-ein-test -e BACKUP_HMAC_KEY=nur-ein-test \
        --entrypoint sh "$BACKUP_IMG" \
        -c 'f=$(ls -1t /backups/db_*.enc | head -1); printf x >> "$f"
            if restore-test.sh > /dev/null 2>&1; then echo "Verändertes Backup eingespielt" >&2; exit 1; fi'
    echo "Backup: veränderte Datei wird abgewiesen"
    # Mit öffentlichem Schlüssel: Server kann verschlüsseln, aber nicht lesen
    docker run --rm --network "$ID" "$CPUS" -v "$ID-backups:/backups" --tmpfs /tmp \
        -e PGHOST="$ID-db" -e PGUSER=test -e PGPASSWORD=test -e PGDATABASE=hubiplan \
        -e BACKUP_HMAC_KEY=nur-ein-test --entrypoint sh "$BACKUP_IMG" \
        -c 'set -e
            age-keygen -o /tmp/schluessel 2> /dev/null
            BACKUP_PUBLIC_KEY=$(age-keygen -y /tmp/schluessel) backup.sh > /dev/null
            f=$(ls -1t /backups/db_*.sql.gz.age | head -1)
            verify.sh "$f"
            tail -1 /backups/restore-test.log | grep -q "$(basename "$f")"
            age -d -i /tmp/schluessel "$f" | gunzip | tail -n 5 | grep -q "dump complete"
            age-keygen -o /tmp/fremd 2> /dev/null
            if age -d -i /tmp/fremd "$f" > /dev/null 2>&1; then echo "Fremder Schlüssel entschlüsselt" >&2; exit 1; fi
            if ls /backups/*.tmp /backups/*.sql.gz > /dev/null 2>&1; then echo "Klartext liegt herum" >&2; exit 1; fi'
    echo "Backup: öffentlicher Schlüssel, Rücksicherung vor dem Verschlüsseln"
    # Dateiliste: jede Datei, auf die die Datenbank zeigt, muss im Backup stehen
    docker volume create "$ID-data" > /dev/null
    docker run --rm --user 0 -v "$ID-data:/data" --entrypoint sh "$BACKUP_IMG" \
        -c 'mkdir -p /data/media/logos /data/private && printf logo > /data/media/logos/da.png
            chmod -R a+rX /data'
    docker exec "$ID-db" psql -q -U test -d hubiplan -c \
        "UPDATE organizations_organization SET logo = CASE
             WHEN id = (SELECT min(id) FROM organizations_organization) THEN 'logos/da.png'
             WHEN id = (SELECT id FROM organizations_organization ORDER BY id OFFSET 1 LIMIT 1) THEN 'logos/fehlt.png'
             ELSE '' END" > /dev/null
    for mode in age enc; do
        docker run --rm --network "$ID" "$CPUS" -v "$ID-backups:/backups" --tmpfs /tmp \
            -v "$ID-data:/data:ro" -e MODE="$mode" \
            -e PGHOST="$ID-db" -e PGUSER=test -e PGPASSWORD=test -e PGDATABASE=hubiplan \
            -e BACKUP_PASSPHRASE=nur-ein-test -e BACKUP_HMAC_KEY=nur-ein-test --entrypoint sh "$BACKUP_IMG" \
            -c 'set -e
                fail() { echo "Dateiliste ($MODE): $1" >&2; tail -5 /backups/restore-test.log >&2; exit 1; }
                if [ "$MODE" = age ]; then
                    age-keygen -o /tmp/schluessel 2> /dev/null
                    BACKUP_PUBLIC_KEY=$(age-keygen -y /tmp/schluessel) backup.sh > /dev/null
                    l=$(ls -1t /backups/dateien_*.sha256.age | head -1)
                    verify.sh "$l"
                    age -d -i /tmp/schluessel "$l" > /tmp/liste
                else
                    backup.sh > /dev/null && restore-test.sh > /dev/null
                    l=$(ls -1t /backups/dateien_*.sha256.enc | head -1)
                    verify.sh "$l"
                    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE -in "$l" > /tmp/liste
                fi
                grep -q "  ./media/logos/da.png$" /tmp/liste || fail "da.png fehlt in der Liste"
                (cd /data && sha256sum -c /tmp/liste > /dev/null) || fail "Prüfsummen passen nicht"
                # Letzter Lauf: Zeile „Rücksicherung ok … Dateien: …“ und davor seine Warnung
                tail -1 /backups/restore-test.log | grep -q "Dateien: 1 gesichert, .* Verweise" \
                    || fail "Zählung fehlt"
                block=$(awk "/WARNUNG: db_/ {b=\"\"} {b=b \$0 \"\n\"} END {printf \"%s\", b}" \
                    /backups/restore-test.log)
                echo "$block" | grep -q "^    ./media/logos/fehlt.png$" || fail "fehlt.png nicht gemeldet"
                if echo "$block" | grep -q "logos/da.png"; then fail "da.png fälschlich gemeldet"; fi
                grep -q "WARNUNG: .* Dateien fehlen" /backups/backup.log || fail "keine Warnung in backup.log"
                # Unvollständig: Merker für die Alarm-Mail, alte Backups bleiben (INF-F03)
                test -f /backups/.unvollstaendig || fail "Merker .unvollstaendig fehlt"
                grep -q "unvollständig, alte Backups bleiben" /backups/backup.log \
                    || fail "unvollständiges Backup hat alte Backups gelöscht"'
    done
    docker volume rm "$ID-data" > /dev/null
    echo "Backup: Dateiliste mit Prüfsummen, fehlende Dateien werden gemeldet"
fi

if [ "$#" -gt 0 ]; then
    # Teil-Läufe (eigene pytest-Argumente) zählen nicht als Freigabe zum Ausrollen
    echo "Grün (Teil-Lauf, nicht als getestet vermerkt): $SHA"
    RESULT_OK=1
    exit 0
fi
STATE="${HUBIPLAN_TESTED_FILE:-$HOME/.local/state/hubiplan/tested-trees}"
mkdir -p "$(dirname "$STATE")"
echo "$TREE $SHA $(date -Iseconds)" >> "$STATE"
echo "Alles grün: $SHA ist als getestet vermerkt ($(($(date +%s) - start)) s gesamt)."
RESULT_OK=1
