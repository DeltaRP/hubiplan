#!/usr/bin/env bash
# Prüft die Webserver-Konfiguration (Teil von scripts/test.sh; gleiche Datei in
# hubiplan und hubiplan-website):
# - beide Caddyfiles mit dem Caddy-Image aus deploy/web.Dockerfile (caddy validate), falls da
# - die nginx-Vorlagen für HestiaCP (deploy/hestia/*.tpl, *.stpl) mit nginx -t,
#   Hestia-Platzhalter durch Beispielwerte ersetzt, ohne Zertifikate
#
#   scripts/pruefe-proxy.sh <Ordner mit deploy/> [docker-run-Optionen, z. B. --cpuset-cpus=…]
set -euo pipefail

SRC="$1"
shift || true
NGINX_IMAGE=nginx:stable-alpine

# Caddy nur in HUBIplan (die Vereinswebseite hat keinen eigenen)
CADDY_IMAGE=""
if [ -f "$SRC/deploy/web.Dockerfile" ]; then
    CADDY_IMAGE=$(grep -m1 -oE '^FROM caddy:[^ ]+' "$SRC/deploy/web.Dockerfile" | cut -d' ' -f2)
fi
for datei in ${CADDY_IMAGE:+Caddyfile Caddyfile.proxy}; do
    docker run --rm "$@" -e SITE_HOST=hubiplan.example.org -v "$SRC/deploy:/etc/caddy:ro" \
        "$CADDY_IMAGE" caddy validate --config "/etc/caddy/$datei" --adapter caddyfile > /dev/null 2>&1 \
        || { docker run --rm "$@" -e SITE_HOST=hubiplan.example.org -v "$SRC/deploy:/etc/caddy:ro" \
            "$CADDY_IMAGE" caddy validate --config "/etc/caddy/$datei" --adapter caddyfile; exit 1; }
done
[ -z "$CADDY_IMAGE" ] || echo "Proxy: Caddyfiles ok"

NG=$(mktemp -d)
trap 'rm -rf "$NG"' EXIT
mkdir -p "$NG/conf"
for vorlage in "$SRC"/deploy/hestia/*.tpl "$SRC"/deploy/hestia/*.stpl; do
    [ -f "$vorlage" ] || continue
    sed -e 's/%ip%/127.0.0.1/g; s/%proxy_ssl_port%/8443/g; s/%proxy_port%/8080/g' \
        -e 's/%domain_idn%/example.org/g; s/%alias_idn%/www.example.org/g; s/%domain%/example.org/g' \
        -e 's/%web_system%/nginx/g; s#%home%#/nicht-da#g; s/%user%/test/g' \
        -e 's/ ssl;/;/; /ssl_certificate\|ssl_stapling/d' \
        "$vorlage" > "$NG/conf/$(basename "$vorlage").conf"
    if grep -q '%[a-z_]*%' "$NG/conf/$(basename "$vorlage").conf"; then
        echo "Unbekannter Hestia-Platzhalter in $(basename "$vorlage"):" >&2
        grep -o '%[a-z_]*%' "$NG/conf/$(basename "$vorlage").conf" | sort -u >&2
        exit 1
    fi
done
cat > "$NG/nginx.conf" << 'CONF'
events {}
http {
    include /etc/nginx/mime.types;
    include /pruefung/conf/*.conf;
}
CONF
docker run --rm "$@" -v "$NG:/pruefung:ro" "$NGINX_IMAGE" \
    sh -c 'mkdir -p /var/log/nginx/domains && nginx -t -q -c /pruefung/nginx.conf'
echo "Proxy: nginx-Vorlagen ok"
