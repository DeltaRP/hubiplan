"""Einstellungen so laden, wie docker-compose.server.yml die Umgebung setzt."""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
KEY = "A" * 43 + "="


def _load(**env):
    base = {k: v for k, v in os.environ.items() if not k.startswith(("MFA_", "DJANGO_"))}
    base.update({"DJANGO_SECRET_KEY": "x" * 50, "DJANGO_DEBUG": "false"}, **env)
    code = "import config.settings as s; print(','.join(s.MFA_ENCRYPTION_KEYS))"
    return subprocess.run(  # noqa: S603 (fester Aufruf im Test)
        [sys.executable, "-c", code], cwd=BACKEND, env=base, capture_output=True, text=True
    )


def test_leere_schluesselliste_nutzt_einzelschluessel():
    # Gesamtaudit 30.10.a: Compose setzt MFA_ENCRYPTION_KEYS="" (${…:-}); das darf den
    # Start nicht verhindern
    res = _load(MFA_ENCRYPTION_KEY=KEY, MFA_ENCRYPTION_KEYS="")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == KEY


def test_schluesselliste_hat_vorrang():
    res = _load(MFA_ENCRYPTION_KEY=KEY, MFA_ENCRYPTION_KEYS="neu, alt")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "neu,alt"


def test_ohne_schluessel_startet_nicht():
    res = _load(MFA_ENCRYPTION_KEYS="")
    assert res.returncode != 0
    assert "MFA_ENCRYPTION_KEY muss gesetzt sein" in res.stderr
