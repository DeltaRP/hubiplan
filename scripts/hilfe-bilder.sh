#!/usr/bin/env bash
# Bildschirmfotos der Hilfe neu erzeugen (docs/hilfe.md).
#
#   scripts/hilfe-bilder.sh [Bildname …]
#
# Startet in Wegwerf-Containern PostgreSQL, Redis, das Backend mit den erfundenen
# Demodaten (seed_testdata) und die Oberfläche aus dem Arbeitsstand, fotografiert jede
# Stelle aus frontend/src/help/bilder.json mit Playwright auf Deutsch und Englisch und
# legt die Bilder unter frontend/public/hilfe-bilder/<sprache>/ ab. Danach die Bilder
# ansehen und einchecken.
#
# Läuft nur lokal auf Ralfs PC (nie auf einem Server) und belegt dafür einen Testplatz
# (höchstens zwei gleichzeitig, je höchstens 8 Kerne; scripts/testplatz.sh).
set -euo pipefail

if [ -z "${TESTPLATZ:-}" ]; then
    exec "$(dirname "$0")/testplatz.sh" "$0" "$@"
fi

ROOT=$(cd "$(dirname "$0")/.." && pwd)
CPUS="--cpuset-cpus=$TESTPLATZ_CPUS"
# Gleiche Hauptversion wie das Playwright-Image; bei einem Wechsel beide anpassen
PLAYWRIGHT_VERSION="${PLAYWRIGHT_VERSION:-1.55.0}"
PW_IMAGE="mcr.microsoft.com/playwright:v$PLAYWRIGHT_VERSION-noble"
PG_IMAGE=$(grep -m1 -oE 'image: postgres:[0-9][^ ]*' "$ROOT/docker-compose.server.yml" | cut -d' ' -f2)
REDIS_IMAGE=$(grep -m1 -oE 'image: redis:[0-9][^ ]*' "$ROOT/docker-compose.yml" | cut -d' ' -f2)
# Nur für diesen Lauf; die Demozugänge verschwinden mit den Containern
PASSWORD="Bilder-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"

ID="hubiplan-bilder-$(date +%s)-$$"
IMG="hubiplan-bilder-backend:$ID"
if [ -d /mnt/e/tmp ]; then mkdir -p /mnt/e/tmp/hubiplan-bilder; WORK=$(mktemp -d -p /mnt/e/tmp/hubiplan-bilder)
else WORK=$(mktemp -d); fi
cleanup() {
    for c in pw web backend redis db; do docker rm -f "$ID-$c" > /dev/null 2>&1 || true; done
    docker network rm "$ID" > /dev/null 2>&1 || true
    docker image rm "$IMG" > /dev/null 2>&1 || true
    rm -rf "$WORK" 2> /dev/null || docker run --rm -v "$WORK:/w" node:24-alpine rm -rf /w/frontend
    rm -rf "$WORK"
}
trap cleanup EXIT

echo "Bildschirmfotos der Hilfe aus dem Arbeitsstand mit $TEST_KERNE Kernen …"
# Kopie ohne node_modules, damit nichts mit Root-Rechten im Klon landet
tar -C "$ROOT" --exclude=node_modules --exclude=dist -cf - frontend | tar -C "$WORK" -xf -

docker build -q -t "$IMG" "$ROOT/backend" > /dev/null
docker network create "$ID" > /dev/null
docker run -d --name "$ID-db" --network "$ID" --network-alias db "$CPUS" --tmpfs /var/lib/postgresql \
    -e POSTGRES_USER=hubiplan -e POSTGRES_PASSWORD=hubiplan -e POSTGRES_DB=hubiplan "$PG_IMAGE" > /dev/null
docker run -d --name "$ID-redis" --network "$ID" --network-alias redis "$CPUS" "$REDIS_IMAGE" > /dev/null
until docker exec "$ID-db" pg_isready -U hubiplan > /dev/null 2>&1; do sleep 1; done

docker run -d --name "$ID-backend" --network "$ID" --network-alias backend "$CPUS" \
    -e DJANGO_DEBUG=true -e DJANGO_SECRET_KEY=nur-fuer-bilder \
    -e DJANGO_ALLOWED_HOSTS=localhost,backend,web \
    -e DJANGO_CSRF_TRUSTED_ORIGINS=http://web:5173 -e FRONTEND_URL=http://web:5173 \
    -e DATABASE_URL=postgres://hubiplan:hubiplan@db:5432/hubiplan -e DATABASE_APP_ROLE=hubiplan_app \
    -e REDIS_URL=redis://redis:6379/0 -e CACHE_URL=redis://redis:6379/1 \
    -e HUBIPLAN_LANGUAGES=de,en -e RUN_MIGRATIONS=1 -e MIGRATE_VERBOSITY=0 \
    "$IMG" python manage.py runserver 0.0.0.0:8000 > /dev/null
until docker exec "$ID-backend" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/public/languages/')" > /dev/null 2>&1; do
    docker inspect -f '{{.State.Running}}' "$ID-backend" | grep -q true || { docker logs "$ID-backend" | tail -30; exit 1; }
    sleep 2
done
docker exec "$ID-backend" python manage.py seed_testdata --password "$PASSWORD" > /dev/null
# Für die Bilder auch die Module, die neue Vereine erst einschalten (nur in diesem Wegwerf-Stand)
docker exec -e DATABASE_APP_ROLE= "$ID-backend" python manage.py shell -c "
from organizations.models import Organization
for o in Organization.objects.filter(type='club'):
    o.enabled_modules = sorted(set(o.enabled_modules or []) | {'competitions', 'entries', 'website'})
    o.cash_counts_enabled = True
    o.save(update_fields=['enabled_modules', 'cash_counts_enabled'])
# Lastschrift (Beispiel-Gläubiger-ID der Bundesbank) und eine Mahnstufe
from billing.models import BillingSettings, DunningLevel
from finance.models import Account
for o in Organization.objects.filter(type='club'):
    # Bankkonto mit einer bekannten Test-IBAN, sonst fehlt der Lastschrift das Konto
    bank = Account.objects.filter(organization=o, kind='bank').order_by('pk').first()
    if bank and not bank.iban:
        bank.iban = 'DE02120300000000202051'
        bank.save(update_fields=['iban'])
    BillingSettings.objects.update_or_create(organization=o, defaults={'sepa_enabled': True, 'creditor_id': 'DE98ZZZ09999999999', 'account': bank})
    DunningLevel.objects.get_or_create(organization=o, level=1, defaults={'name': 'Zahlungserinnerung', 'days': 14})
# Erfundener Mitgliedszugang mit Mitgliederbereich (Meine Daten, App verbinden)
from django.contrib.auth import get_user_model
from access.models import RoleAssignment
from members.models import Membership
from portal.models import PortalAccess
club = RoleAssignment.objects.get(user__email='vorstand@hubertus-grimlinghausen.test').organization
club.member_portal_enabled = True
club.save(update_fields=['member_portal_enabled'])
membership = next(m for m in Membership.objects.filter(organization=club).select_related('person').order_by('pk') if m.current_period())
user, _ = get_user_model().objects.get_or_create(email='mitglied@hubertus-grimlinghausen.test',
    defaults={'first_name': membership.person.first_name, 'last_name': membership.person.last_name})
user.set_password('$PASSWORD')
user.save()
PortalAccess.objects.get_or_create(membership=membership, defaults={'organization': club, 'user': user})
" > /dev/null
echo "Backend mit Demodaten bereit"

docker run -d --name "$ID-web" --network "$ID" --network-alias web "$CPUS" \
    -v "$WORK/frontend:/app" -v hubiplan-npm-cache:/root/.npm -w /app \
    -e BACKEND_URL=http://backend:8000 -e __VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS=web \
    node:24-alpine sh -c "npm ci --no-audit --no-fund --loglevel=error > /dev/null && npx vite --host 0.0.0.0 --port 5173" > /dev/null
until docker run --rm --network "$ID" node:24-alpine wget -q -O /dev/null http://web:5173/ 2> /dev/null; do
    docker inspect -f '{{.State.Running}}' "$ID-web" | grep -q true || { docker logs "$ID-web" | tail -30; exit 1; }
    sleep 3
done
echo "Oberfläche bereit"

mkdir -p "$ROOT/frontend/public/hilfe-bilder"
docker run --rm --name "$ID-pw" --network "$ID" "$CPUS" --ipc=host \
    -v "$WORK/frontend:/app" -v "$ROOT/frontend/public/hilfe-bilder:/out" -v hubiplan-npm-cache:/root/.npm \
    -e BASE_URL=http://web:5173 -e DEMO_PASSWORD="$PASSWORD" -e OUT=/out -w /app/scripts \
    --user "$(id -u):$(id -g)" -e HOME=/tmp -e npm_config_cache=/tmp/.npm \
    "$PW_IMAGE" sh -c "npm i --no-save --no-audit --no-fund --loglevel=error --prefix /app/scripts playwright@$PLAYWRIGHT_VERSION > /dev/null && node hilfe-bilder.mjs $*"
echo "Fertig: frontend/public/hilfe-bilder/ (Bilder ansehen, dann einchecken)"
