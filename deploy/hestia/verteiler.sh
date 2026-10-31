#!/bin/bash
# Mailverteiler auf dem Hestia-Server (Echtserver bei Dogado) einrichten:
# Mail-Domain für die Verteiler-Adressen (z. B. alle@verein.example.org) mit
# einem Sammelpostfach, an das alle Adressen der Domain gehen (Catch-all). HUBIplan
# holt das Postfach jede Minute per IMAP ab (circulars/inbound.py).
#
# Aufruf von Ralfs PC (PowerShell), läuft als root auf dem Server:
#   Get-Content -Raw deploy\hestia\verteiler.sh | ssh administrator@dogado "sudo env DOMAIN=verein.example.org ZONE=example.org bash -s"
#
# Wiederholbar: Was schon da ist, bleibt. Gibt keine Passwörter aus; das Passwort des
# Sammelpostfachs steht nur in /opt/hubiplan/.env.
set -euo pipefail
export PATH=/usr/local/hestia/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

HUSER=${HUSER:-ralf}
DOMAIN=${DOMAIN:?DOMAIN fehlt, z. B. DOMAIN=verein.example.org}
ZONE=${ZONE:?ZONE fehlt, z. B. ZONE=example.org}
KONTO=${KONTO:-eingang}
MAILSERVER=${MAILSERVER:-mail.$ZONE}
# Stundengrenze des Versandpostfachs (Hestia: 100 je Postfach)
RATE=${RATE:-100}
APP=/opt/hubiplan
ENV="$APP/.env"

echo "### Start $(TZ=Europe/Berlin date '+%d.%m.%Y %H:%M')"
[ -f "$ENV" ] || { echo "Abbruch: $ENV fehlt."; exit 1; }

echo "--- 1) Mail-Domain $DOMAIN"
if v-list-mail-domain "$HUSER" "$DOMAIN" >/dev/null 2>&1; then
    echo "gibt es schon"
else
    # Spam- und Virenprüfung an, DKIM aus (von hier wird nichts versendet)
    v-add-mail-domain "$HUSER" "$DOMAIN" yes yes no
fi

echo "--- 2) MX-Eintrag $DOMAIN -> $MAILSERVER"
SUB=${DOMAIN%%.$ZONE}
if v-list-dns-records "$HUSER" "$ZONE" plain | awk -F'\t' -v s="$SUB" '$2==s && $3=="MX" {f=1} END {exit !f}'; then
    echo "gibt es schon"
else
    v-add-dns-record "$HUSER" "$ZONE" "$SUB" MX "$MAILSERVER." 10 '' yes
    echo "angelegt; der Zweit-Nameserver übernimmt ihn innerhalb von 4 Stunden"
fi

echo "--- 3) Sammelpostfach $KONTO@$DOMAIN und Catch-all"
if grep -q '^INBOUND_IMAP_HOST=' "$ENV"; then
    echo "Sammelpostfach steht schon in der .env"
else
    PW=$(openssl rand -base64 30 | tr -d '\n/+=')
    if v-list-mail-account "$HUSER" "$DOMAIN" "$KONTO" >/dev/null 2>&1; then
        v-change-mail-account-password "$HUSER" "$DOMAIN" "$KONTO" "$PW"
    else
        v-add-mail-account "$HUSER" "$DOMAIN" "$KONTO" "$PW"
    fi
    umask 077
    {
        echo "INBOUND_DOMAINS=$DOMAIN"
        echo "INBOUND_IMAP_HOST=$MAILSERVER"
        echo "INBOUND_IMAP_PORT=993"
        echo "INBOUND_IMAP_USER=$KONTO@$DOMAIN"
        echo "INBOUND_IMAP_PASSWORD=$PW"
    } >> "$ENV"
    unset PW
    echo "Postfach angelegt, Zugangsdaten nur in $ENV"
fi
v-change-mail-domain-catchall "$HUSER" "$DOMAIN" "$KONTO@$DOMAIN"
grep -q '^MAIL_RATE_PER_HOUR=' "$ENV" || echo "MAIL_RATE_PER_HOUR=$RATE" >> "$ENV"
chmod 600 "$ENV"

echo "--- 4) Dienste mit neuer .env starten"
cd "$APP" && sh deploy/server-setup.sh >/dev/null && echo "Docker-Verbund läuft"
echo "### Ende $(TZ=Europe/Berlin date '+%d.%m.%Y %H:%M')"
