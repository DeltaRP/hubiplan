#!/bin/sh
# HMAC-SHA256 einer Datei mit BACKUP_HMAC_KEY (hex, eine Zeile).
#
# Gleiches Ergebnis wie `openssl dgst -sha256 -mac HMAC -macopt key:SCHLÜSSEL`, aber
# der Schlüssel steht nie in der Befehlszeile eines Programms (sonst sähe ihn jeder
# Prozess über ps oder /proc, Audit 29.10. I-V01). Er geht nur über die Standard-
# eingabe an od/awk und über das eingebaute printf der Shell. Ablauf nach RFC 2104:
# H((K xor opad) || H((K xor ipad) || Datei)).
set -eu
: "${BACKUP_HMAC_KEY:?BACKUP_HMAC_KEY fehlt}"
[ -r "$1" ] || { echo "FEHLER: $1 nicht lesbar" >&2; exit 1; }

hex() { od -An -v -tx1 | tr -d ' \n'; }

# Schlüssel als Hex; länger als ein Block (64 Byte): erst hashen (wie openssl)
key=$(printf '%s' "$BACKUP_HMAC_KEY" | hex)
if [ "${#key}" -gt 128 ]; then
    key=$(printf '%s' "$BACKUP_HMAC_KEY" | sha256sum | cut -c1-64)
fi

# Hex (Standardeingabe) auf 64 Byte auffüllen, mit $1 verknüpfen (xor) und als
# Oktal-Escapes für printf ausgeben; ohne $1 nur umwandeln, ohne Auffüllen.
octal() {
    awk -v pad="${1:-}" '
    function val(c) { return index("0123456789abcdef", c) - 1 }
    # Eigener Name: BusyBox-awk kennt xor() schon und meldet sonst einen Syntaxfehler
    function bxor(a, b,   r, i) {
        r = 0
        for (i = 1; i < 256; i *= 2) {
            if ((int(a / i) % 2) != (int(b / i) % 2)) r += i
        }
        return r
    }
    {
        s = tolower($0)
        n = length(s) / 2
        if (pad != "") while (n < 64) { s = s "00"; n++ }
        out = ""
        for (j = 0; j < n; j++) {
            b = val(substr(s, 2 * j + 1, 1)) * 16 + val(substr(s, 2 * j + 2, 1))
            if (pad != "") b = bxor(b, pad + 0)
            out = out sprintf("\\%03o", b)
        }
        printf "%s", out
    }'
}

ipad=$(printf '%s\n' "$key" | octal 54)
opad=$(printf '%s\n' "$key" | octal 92)
# shellcheck disable=SC2059 # Formatstring sind die Oktal-Escapes
inner=$({ printf "$ipad"; cat "$1"; } | sha256sum | cut -c1-64)
inner_bin=$(printf '%s\n' "$inner" | octal)
# shellcheck disable=SC2059
{ printf "$opad"; printf "$inner_bin"; } | sha256sum | cut -c1-64
