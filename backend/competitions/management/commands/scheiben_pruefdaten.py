"""Künstliche Scheibenfotos mit Lösung erzeugen (Schießscheiben Schritt 3).

    python manage.py scheiben_pruefdaten /mnt/e/tmp/scheiben --anzahl 200 --scheibe lg10_kyf

Schreibt je Bild ``NNNN.jpg`` und ``NNNN.json`` (Treffer in mm und im Foto, Ringe, Zehntel,
Aufnahmebedingungen) und eine Übersicht ``loesungen.jsonl``. Nur erfundene Daten; gleicher
Startwert, gleiche Bilder. Temporäres auf Ralfs PC auf Laufwerk E: ablegen.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from competitions import targets
from competitions.vision import synth


class Command(BaseCommand):
    help = "Künstliche Scheibenfotos mit bekannter Wertung erzeugen (Prüfdaten)."

    def add_arguments(self, parser):
        parser.add_argument("ziel", help="Ordner für die Bilder")
        parser.add_argument("--anzahl", type=int, default=50)
        parser.add_argument(
            "--scheibe",
            action="append",
            choices=sorted(targets.BY_KEY),
            help="Scheibe (mehrfach möglich); ohne: DSB- und Kyffhäuser-LG",
        )
        parser.add_argument("--schuss", type=int, default=5, help="Schüsse je Spiegel")
        parser.add_argument("--schwierigkeit", type=float, default=0.5, help="0 bis 1")
        parser.add_argument("--start", type=int, default=1, help="Zufallsstartwert")

    def handle(self, *args, **opts):
        if opts["anzahl"] < 1 or opts["anzahl"] > 10000:
            raise CommandError("Bitte 1 bis 10000 Bilder.")
        out = Path(opts["ziel"])
        out.mkdir(parents=True, exist_ok=True)
        keys = opts["scheibe"] or ["lg10_dsb", "lg10_kyf"]
        lines = []
        for i in range(opts["anzahl"]):
            seed = opts["start"] + i
            key = keys[i % len(keys)]
            image, sample = synth.make_sample(
                key, seed, shots=opts["schuss"], difficulty=opts["schwierigkeit"]
            )
            name = f"{i + 1:04d}"
            (out / f"{name}.jpg").write_bytes(image)
            truth = {"bild": f"{name}.jpg", "start": seed, **sample.truth()}
            (out / f"{name}.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1))
            lines.append(json.dumps(truth, ensure_ascii=False))
        (out / "loesungen.jsonl").write_text("\n".join(lines) + "\n")
        self.stdout.write(f"{len(lines)} Prüfbilder in {out}")
