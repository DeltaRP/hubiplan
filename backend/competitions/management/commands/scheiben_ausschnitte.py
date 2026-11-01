"""Gesammelte Spiegelausschnitte für die Weiterentwicklung der Fotoerkennung ausgeben.

    python manage.py scheiben_ausschnitte /mnt/e/tmp/ausschnitte [--scheibe lg10_kyf]

Nur Ausschnitte von Vereinen, die das Sammeln eingeschaltet haben (siehe
``competitions/samples.py``). Schreibt je Ausschnitt ``NNNN.jpg`` (entzerrtes Graubild, Mitte in
der Bildmitte) und ``NNNN.json`` (Scheibe, Bildpunkte je mm, bestätigte und erkannte Treffer in
mm, y nach oben). Ohne Verein, Namen oder Uhrzeit. Nicht ins Repository legen.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from competitions.models import PhotoSample
from core.tenancy import rls_bypass


class Command(BaseCommand):
    help = "Gesammelte, bestätigte Spiegelausschnitte als Bilder mit Lösung ausgeben."

    def add_arguments(self, parser):
        parser.add_argument("ziel", help="Ordner für die Ausschnitte")
        parser.add_argument("--scheibe", help="nur diese Scheibe (Schlüssel)")

    def handle(self, *args, **opts):
        out = Path(opts["ziel"])
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        with rls_bypass():
            qs = PhotoSample.objects.order_by("id")
            if opts["scheibe"]:
                qs = qs.filter(target=opts["scheibe"])
            for n, sample in enumerate(qs.iterator(), start=1):
                (out / f"{n:04d}.jpg").write_bytes(bytes(sample.image))
                info = {
                    "scheibe": sample.target,
                    "masse": sample.target_data,
                    "px_je_mm": float(sample.px_per_mm),
                    "treffer": sample.hits,
                    "erkannt": sample.detected,
                    "monat": sample.created_on.strftime("%Y-%m"),
                }
                (out / f"{n:04d}.json").write_text(
                    json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8"
                )
        self.stdout.write(f"{n} Ausschnitte nach {out} geschrieben.")
