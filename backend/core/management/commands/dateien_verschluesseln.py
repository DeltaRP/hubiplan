"""Vorhandene private Dateien verschlüsseln (einmalig nach dem Ausrollen) oder für den
Rückweg auf eine ältere Fassung wieder entschlüsseln (``--entschluesseln``).

Jede Datei wird in eine neue Datei daneben geschrieben und dann in einem Schritt
ersetzt; bricht der Lauf ab, ist jede Datei entweder ganz alt oder ganz neu. Ein
erneuter Lauf macht dort weiter. Vorher ein frisches Backup anlegen.
"""

from __future__ import annotations

import os

from django.apps import apps
from django.core.management.base import BaseCommand

from core import crypto
from core.privatefiles import PrivateFileField, org_id_of
from core.tenancy import rls_bypass


def private_fields():
    for model in apps.get_models():
        fields = [f for f in model._meta.get_fields() if isinstance(f, PrivateFileField)]
        if fields:
            yield model, fields


def _rewrite(storage, name: str, transform) -> None:
    path = storage.path(name)
    temp = f"{path}.neu-{os.getpid()}"
    with open(path, "rb") as source, open(temp, "wb") as target:
        for chunk in transform(source):
            target.write(chunk)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temp, path)


class Command(BaseCommand):
    help = "Private Dateien mit dem Schlüssel ihres Vereins verschlüsseln (oder zurück)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--entschluesseln",
            action="store_true",
            help="Rückweg: alle Dateien wieder im Klartext ablegen (vor zurueck.sh).",
        )
        parser.add_argument("--probe", action="store_true", help="Nur zählen, nichts ändern.")

    def handle(self, *args, entschluesseln=False, probe=False, **options):
        done = skipped = missing = 0
        with rls_bypass():
            for model, fields in private_fields():
                for obj in model._base_manager.all().iterator(chunk_size=200):
                    for field in fields:
                        fieldfile = getattr(obj, field.attname)
                        if not fieldfile:
                            continue
                        storage = fieldfile.storage
                        if not storage.exists(fieldfile.name):
                            missing += 1
                            continue
                        encrypted = storage.is_encrypted(fieldfile.name)
                        if encrypted != entschluesseln:
                            skipped += 1
                            continue
                        if not probe:
                            if entschluesseln:
                                _rewrite(storage, fieldfile.name, _decrypt)
                            else:
                                org_id = org_id_of(obj)
                                if org_id is None:
                                    from organizations.models import Organization

                                    org_id = Organization.platform().pk
                                key_id, key = crypto.key_for_org(org_id)
                                _rewrite(
                                    storage,
                                    fieldfile.name,
                                    lambda src, k=key_id, v=key: crypto.encrypt_chunks(src, k, v),
                                )
                        done += 1
        verb = "entschlüsselt" if entschluesseln else "verschlüsselt"
        if probe:
            verb = f"zu {verb}"
        self.stdout.write(
            f"{done} Dateien {verb}, {skipped} schon fertig, {missing} fehlen im Speicher."
        )


def _decrypt(source):
    reader = crypto.open_plain(source)
    while True:
        chunk = reader.read(crypto.CHUNK)
        if not chunk:
            return
        yield chunk
