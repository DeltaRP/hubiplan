#!/bin/bash
# Spielt die nginx-Vorlagen von HUBIplan (app-8110) und der Vereinswebseite
# (webseite-8111) nach einer Änderung neu ein, z. B. die Seite „Wird gerade
# aktualisiert“ statt „502 Bad Gateway“ beim Ausrollen. Erst HUBIplan und die
# Webseite ausrollen (die Vorlagen kommen aus /opt/hubiplan und /opt/hubiplan-website).
#
# Aufruf von Ralfs PC (PowerShell), läuft als root auf dem Server:
#   Get-Content -Raw deploy\hestia\vorlagen-erneuern.sh | ssh administrator@dogado "sudo bash -s"
#
# Nur Domains, die die Vorlage schon nutzen, werden neu aufgebaut. Hestia lädt nginx
# nur neu (reload), andere Websites laufen weiter. Besteht die neue Konfiguration
# „nginx -t“ nicht, kommen die vorigen Vorlagen zurück.
set -euo pipefail
export PATH=/usr/local/hestia/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

HUSER=${HUSER:-ralf}
TPL=/usr/local/hestia/data/templates/web/nginx
SICHERUNG=/root/sicherung-nginx-vorlagen/$(date +%Y-%m-%d_%H%M)

echo "### Start $(TZ=Europe/Berlin date '+%d.%m.%Y %H:%M')"
umask 077
mkdir -p "$SICHERUNG"

# Vorlage → Quelle
declare -A QUELLE=(
    [app-8110]=/opt/hubiplan/deploy/hestia
    [webseite-8111]=/opt/hubiplan-website/deploy/hestia
)

DOMAINS=()
for vorlage in "${!QUELLE[@]}"; do
    quelle=${QUELLE[$vorlage]}
    if [ ! -f "$quelle/$vorlage.stpl" ]; then
        echo "$vorlage: keine Vorlage in $quelle, übersprungen"
        continue
    fi
    for endung in tpl stpl; do
        [ -f "$TPL/$vorlage.$endung" ] && cp -p "$TPL/$vorlage.$endung" "$SICHERUNG/"
    done
    install -m 644 -o root -g root "$quelle/$vorlage.tpl" "$quelle/$vorlage.stpl" "$TPL/"
    echo "$vorlage: eingespielt"
    for domain in $(v-list-web-domains "$HUSER" plain | cut -f1); do
        proxy=$(v-list-web-domain "$HUSER" "$domain" json | sed -n 's/.*"PROXY": *"\([^"]*\)".*/\1/p' | head -1)
        [ "$proxy" = "$vorlage" ] && DOMAINS+=("$domain:$vorlage")
    done
done

neu_aufbauen() {
    for eintrag in "${DOMAINS[@]}"; do
        v-change-web-domain-proxy-tpl "$HUSER" "${eintrag%%:*}" "${eintrag##*:}" '' yes
    done
}

if [ "${#DOMAINS[@]}" -eq 0 ]; then
    echo "Keine Domain nutzt die Vorlagen, nichts neu aufgebaut."
    exit 0
fi
echo "Neu aufbauen: ${DOMAINS[*]}"
if neu_aufbauen && nginx -t 2> /dev/null; then
    echo "Fertig. Sicherung der vorigen Vorlagen: $SICHERUNG"
else
    echo "FEHLER: nginx-Konfiguration ungültig, vorige Vorlagen kommen zurück." >&2
    install -m 644 -o root -g root "$SICHERUNG"/* "$TPL/"
    neu_aufbauen || true
    nginx -t
    exit 1
fi
