#!/usr/bin/env bash
# testplatz: gemeinsame Testplätze für alle Projekte auf Ralfs PC.
#
#   testplatz [--kerne N] [--] Befehl [Argumente …]
#
# Regel: höchstens zwei Testläufe gleichzeitig, jeder höchstens 8 Kerne, egal aus
# welchem Projekt. testplatz wartet auf einen freien Platz, bindet den Befehl an
# dessen Kerne und gibt ihm die Umgebungsvariablen
#   TESTPLATZ=1|2        belegter Platz
#   TEST_KERNE=N         so viele Kerne darf der Lauf nutzen (Worker, -n, --cpus …)
#   TESTPLATZ_CPUS=a-b   die Kerne des Platzes (für docker run --cpuset-cpus)
#
# In WSL (Debian) hält es die Sperre selbst. Unter Windows (Git Bash) holt es den Platz
# über WSL und lässt den Befehl unter Windows laufen, mit Prozessor-Affinität auf 8 Kerne.
# Ist TESTPLATZ schon gesetzt, läuft der Befehl direkt (verschachtelte Aufrufe).
#
# Sperren: ~/.testplaetze/platz-1.lock und platz-2.lock (in WSL). Ältere Skripte mit
# der exklusiven Sperre ~/.hubiplan-tests.lock belegen beide Plätze: testplatz hält diese
# Datei geteilt.
#
# Installation (einmal, und nach Änderungen):
#   WSL:      install -m 755 scripts/testplatz.sh ~/.local/bin/testplatz
#   Git Bash: install -m 755 scripts/testplatz.sh ~/bin/testplatz
set -euo pipefail

MAX_KERNE=8
PLAETZE=2
WSL_DISTRO="${TESTPLATZ_DISTRO:-Debian}"

KERNE=$MAX_KERNE
WIN_DIR=""
while [ $# -gt 0 ]; do
    case "$1" in
        --kerne) KERNE="$2"; shift 2 ;;
        --windows) WIN_DIR="$2"; shift 2 ;;  # intern: vom Windows-Aufruf
        --) shift; break ;;
        *) break ;;
    esac
done
if [ $# -eq 0 ] && [ -z "$WIN_DIR" ]; then
    sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi
[ "$KERNE" -gt "$MAX_KERNE" ] && KERNE=$MAX_KERNE
[ "$KERNE" -lt 1 ] && KERNE=1

# Schon in einem Platz: nicht noch einen belegen
if [ -n "${TESTPLATZ:-}" ]; then
    [ "$KERNE" -gt "${TEST_KERNE:-$KERNE}" ] && KERNE=$TEST_KERNE
    export TEST_KERNE=$KERNE
    exec "$@"
fi

# --- Windows (Git Bash): Platz über WSL holen, Befehl unter Windows ausführen ---
if [ "$(uname -o 2> /dev/null)" = "Msys" ]; then
    TMPD="${TESTPLATZ_TMP:-/e/temp/testplatz}"
    mkdir -p "$TMPD"
    SKRIPT="$TMPD/lauf-$$.sh"
    {
        echo 'set -e'
        # Affinität auf die Kerne des Platzes, Kindprozesse erben sie
        echo 'powershell.exe -NoProfile -Command "(Get-Process -Id $(cat /proc/$$/winpid)).ProcessorAffinity = $TESTPLATZ_MASKE" > /dev/null'
        printf 'cd %q\n' "$(pwd)"
        printf 'exec'; printf ' %q' "$@"; echo
    } > "$SKRIPT"
    rc=0
    MSYS_NO_PATHCONV=1 wsl.exe -d "$WSL_DISTRO" -e bash -lc \
        'exec testplatz --kerne "$1" --windows "$2"' _ "$KERNE" "$(cygpath -w "$SKRIPT")" || rc=$?
    rm -f "$SKRIPT"
    exit $rc
fi

# --- WSL/Linux: Platz belegen ---
DIR="${TESTPLATZ_DIR:-$HOME/.testplaetze}"
mkdir -p "$DIR"
ALT="${HUBIPLAN_TEST_LOCK:-$HOME/.hubiplan-tests.lock}"
exec {alt_fd}> "$ALT"
if ! flock -n -s "$alt_fd"; then
    # Blockierend warten, sonst kommt man zwischen alten Läufen nie dran
    echo "testplatz: ein älteres Testskript belegt alle Plätze, warte …" >&2
    flock -s "$alt_fd"
fi
gewartet=0
while :; do
    for p in $(seq 1 $PLAETZE); do
        exec {fd}> "$DIR/platz-$p.lock"
        if flock -n "$fd"; then
            PLATZ=$p
            break 2
        fi
        exec {fd}>&-
    done
    if [ "$gewartet" = 0 ]; then
        echo "testplatz: beide Plätze belegt, warte …" >&2
        gewartet=1
    fi
    sleep 3
done

# Kerne des Platzes: Platz 1 von vorn, Platz 2 von hinten (bei 16+ Kernen ohne Überlappung)
N=$(nproc --all)
[ "$KERNE" -gt "$N" ] && KERNE=$N
if [ "$PLATZ" = 1 ]; then
    CPUS="0-$((KERNE - 1))"
else
    CPUS="$((N - KERNE))-$((N - 1))"
fi
export TESTPLATZ=$PLATZ TEST_KERNE=$KERNE TESTPLATZ_CPUS=$CPUS
# Ein älteres Testskript im Platz würde ~/.hubiplan-tests.lock exklusiv sperren wollen,
# das testplatz selbst geteilt hält, und auf sich selbst warten. Es bekommt deshalb
# eine eigene Sperrdatei für diesen Platz.
export HUBIPLAN_TEST_LOCK="$DIR/innen-$PLATZ.lock"
echo "testplatz: Platz $PLATZ, $KERNE Kerne ($CPUS)" >&2

if [ -n "$WIN_DIR" ]; then
    # Windows-Kerne: Platz 1 ab Kern 0, Platz 2 ab Kern 8 (der PC hat 24)
    start=$(( (PLATZ - 1) * MAX_KERNE ))
    export TESTPLATZ_MASKE=$(( ((1 << KERNE) - 1) << start ))
    export WSLENV="TESTPLATZ:TEST_KERNE:TESTPLATZ_CPUS:TESTPLATZ_MASKE${WSLENV:+:$WSLENV}"
    exec "/mnt/c/Program Files/Git/bin/bash.exe" "$WIN_DIR"
fi
exec taskset -c "$CPUS" "$@"
