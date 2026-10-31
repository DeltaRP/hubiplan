#!/bin/bash
# Richtet HUBIplan auf einem Server mit HestiaCP ein (Echtserver bei Dogado).
# Voraussetzung: deploy/deploy.sh ist einmal mit HUBIPLAN_HINTER_PROXY=1 gelaufen,
# der Docker-Verbund läuft also unter /opt/hubiplan und lauscht auf 127.0.0.1:8110.
#
# Aufruf von Ralfs PC (PowerShell), läuft als root auf dem Server:
#   Get-Content -Raw deploy\hestia\einrichten.sh | ssh administrator@dogado "sudo env DOMAIN=verein.example.org MAILDOMAIN=example.org ALARM_MAIL=adresse@example.org bash -s"
#
# Wiederholbar: Was schon da ist, bleibt. Hestia lädt nginx dabei nur neu (reload),
# andere Websites laufen weiter. Gibt keine Passwörter aus.
set -euo pipefail
export PATH=/usr/local/hestia/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

HUSER=${HUSER:-ralf}
DOMAIN=${DOMAIN:?DOMAIN fehlt, z. B. DOMAIN=verein.example.org}
MAILDOMAIN=${MAILDOMAIN:?MAILDOMAIN fehlt, z. B. MAILDOMAIN=example.org}
MAILKONTO=${MAILKONTO:-verein}
VORLAGE=app-8110
APP=/opt/hubiplan
TPL=/usr/local/hestia/data/templates/web/nginx

echo "### Start $(TZ=Europe/Berlin date '+%d.%m.%Y %H:%M')"
[ -f "$APP/.env" ] || { echo "Abbruch: $APP/.env fehlt, erst deploy/deploy.sh ausführen."; exit 1; }
grep -q '^HUBIPLAN_HINTER_PROXY=1' "$APP/.env" || { echo "Abbruch: HUBIPLAN_HINTER_PROXY=1 fehlt in $APP/.env."; exit 1; }
curl -fsS -o /dev/null http://127.0.0.1:8110/ || { echo "Abbruch: HUBIplan antwortet nicht auf 127.0.0.1:8110."; exit 1; }

echo "--- 1) nginx-Vorlage $VORLAGE"
install -m 644 -o root -g root "$APP/deploy/hestia/$VORLAGE.tpl" "$APP/deploy/hestia/$VORLAGE.stpl" "$TPL/"

echo "--- 2) Web-Domain $DOMAIN (ohne www-Alias) und DNS-A-Eintrag"
if v-list-web-domain "$HUSER" "$DOMAIN" >/dev/null 2>&1; then
    echo "gibt es schon"
else
    v-add-web-domain "$HUSER" "$DOMAIN" '' yes none
fi
# Hestia legt den A-Eintrag für eine Subdomain nicht immer mit an (28.10.2026)
SUB=${DOMAIN%%.$MAILDOMAIN}
IP=$(v-list-web-domain "$HUSER" "$DOMAIN" json | sed -n 's/.*"IP": *"\([0-9.]*\)".*/\1/p' | head -1)
if v-list-dns-records "$HUSER" "$MAILDOMAIN" plain | awk -F'\t' -v s="$SUB" '$2==s && $3=="A" {f=1} END {exit !f}'; then
    echo "DNS-A-Eintrag $SUB gibt es schon"
else
    [ -n "$IP" ] || { echo "Abbruch: IP der Web-Domain nicht gefunden."; exit 1; }
    v-add-dns-record "$HUSER" "$MAILDOMAIN" "$SUB" A "$IP" '' '' yes
    echo "DNS-A-Eintrag $SUB -> $IP angelegt; Let's Encrypt braucht, bis alle Nameserver ihn kennen"
fi
v-change-web-domain-proxy-tpl "$HUSER" "$DOMAIN" "$VORLAGE" '' yes

echo "--- 3) Zertifikat (Let's Encrypt)"
# OHNE_ZERTIFIKAT=1: überspringen, solange noch nicht alle Nameserver den DNS-Eintrag kennen
# (Fehlversuche zählen bei Let's Encrypt gegen ein Limit)
if [ -n "${OHNE_ZERTIFIKAT:-}" ]; then
    echo "übersprungen (OHNE_ZERTIFIKAT)"
elif v-list-web-domain "$HUSER" "$DOMAIN" json | grep -q '"SSL": *"yes"'; then
    echo "SSL ist schon eingerichtet"
else
    sleep 5   # DNS-Reload abwarten
    v-add-letsencrypt-domain "$HUSER" "$DOMAIN"
fi
[ -n "${OHNE_ZERTIFIKAT:-}" ] || v-add-web-domain-ssl-force "$HUSER" "$DOMAIN" yes 2>/dev/null || true

echo "--- 4) Postfach $MAILKONTO@$MAILDOMAIN für den Mailversand"
ENV="$APP/.env"
if grep -q '^EMAIL_HOST=' "$ENV"; then
    echo "SMTP steht schon in der .env"
else
    PW=$(openssl rand -base64 30 | tr -d '\n/+=')
    if v-list-mail-account "$HUSER" "$MAILDOMAIN" "$MAILKONTO" >/dev/null 2>&1; then
        v-change-mail-account-password "$HUSER" "$MAILDOMAIN" "$MAILKONTO" "$PW"
    else
        v-add-mail-account "$HUSER" "$MAILDOMAIN" "$MAILKONTO" "$PW"
    fi
    umask 077
    {
        echo "EMAIL_HOST=mail.$MAILDOMAIN"
        echo "EMAIL_PORT=587"
        echo "EMAIL_USE_TLS=true"
        echo "EMAIL_HOST_USER=$MAILKONTO@$MAILDOMAIN"
        echo "EMAIL_HOST_PASSWORD=$PW"
    } >> "$ENV"
    unset PW
    echo "Postfach angelegt, Zugangsdaten nur in $ENV"
fi
grep -q '^DEFAULT_FROM_EMAIL=' "$ENV" || echo "DEFAULT_FROM_EMAIL=HUBIplan <$MAILKONTO@$MAILDOMAIN>" >> "$ENV"
grep -q '^MFA_TOTP_ISSUER=' "$ENV" || echo "MFA_TOTP_ISSUER=HUBIplan" >> "$ENV"
if [ -n "${ALARM_MAIL:-}" ] && ! grep -q '^SECURITY_ALERT_EMAIL=' "$ENV"; then
    echo "SECURITY_ALERT_EMAIL=$ALARM_MAIL" >> "$ENV"
fi
chmod 600 "$ENV"

echo "--- 5) Dienste mit neuer .env starten"
cd "$APP" && sh deploy/server-setup.sh >/dev/null && echo "Docker-Verbund läuft"

echo "--- 6) Prüfung von außen"
sleep 3
curl -sS -o /dev/null -w "http  -> %{http_code} %{redirect_url}\n" "http://$DOMAIN/" || true
curl -sS -o /dev/null -w "https -> %{http_code}\n" "https://$DOMAIN/" || true
curl -sS "https://$DOMAIN/api/health/" || true; echo
echo "### Ende $(TZ=Europe/Berlin date '+%d.%m.%Y %H:%M')"
