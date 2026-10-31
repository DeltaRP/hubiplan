#!/bin/sh
set -e

# Migrationen nur im Web-Container ausführen, nicht im Worker.
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    # Migrationen laufen als Tabelleneigentümer, nicht in der RLS-Rolle. Auf dem
    # Server steht dessen Zugang nur in MIGRATE_DATABASE_URL; die laufende
    # Anwendung meldet sich danach als hubiplan_app an (DATABASE_URL).
    OWNER_URL="${MIGRATE_DATABASE_URL:-${DATABASE_URL:-}}"
    DATABASE_URL="$OWNER_URL" DATABASE_APP_ROLE= python manage.py migrate --noinput -v "${MIGRATE_VERBOSITY:-1}"
    DATABASE_URL="$OWNER_URL" DATABASE_APP_ROLE= python manage.py ensure_app_role
    # Erledigte Löschungen erneut anwenden (nach dem Einspielen eines älteren Backups)
    if [ -n "${LOESCHLISTE_PATH:-}" ]; then
        DATABASE_URL="$OWNER_URL" DATABASE_APP_ROLE= python manage.py loeschliste_anwenden
    fi
    unset OWNER_URL
fi
# Der Zugang des Tabelleneigentümers gelangt nicht in den laufenden Prozess
unset MIGRATE_DATABASE_URL APP_DB_PASSWORD

# Statische Dateien (Admin, API-Doku) für den Betrieb mit gunicorn einsammeln.
if [ "${COLLECT_STATIC:-0}" = "1" ]; then
    python manage.py collectstatic --noinput
fi

exec "$@"
