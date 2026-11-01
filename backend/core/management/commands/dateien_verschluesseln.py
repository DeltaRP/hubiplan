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
        self.counts = {"done": 0, "skipped": 0, "missing": 0}
        self.entschluesseln, self.probe = entschluesseln, probe
        with rls_bypass():
            for model, fields in private_fields():
                for obj in model._base_manager.all().iterator(chunk_size=200):
                    for field in fields:
                        fieldfile = getattr(obj, field.attname)
                        if fieldfile:
                            self._file(
                                fieldfile.storage, fieldfile.name, lambda o=obj: org_id_of(o)
                            )
            self._outbox()
        verb = "entschlüsselt" if entschluesseln else "verschlüsselt"
        if probe:
            verb = f"zu {verb}"
        c = self.counts
        self.stdout.write(
            f"{c['done']} Dateien {verb}, {c['skipped']} schon fertig, "
            f"{c['missing']} fehlen im Speicher."
        )

    def _outbox(self) -> None:
        """Anhänge im Postausgang (nur die eigenen unter outbox/, keine Dokumente)."""
        from exchange.models import private_storage
        from outbox.models import OutgoingMail

        seen: set[str] = set()
        mails = OutgoingMail.objects.exclude(attachments=[]).only(
            "pk", "organization_id", "attachments"
        )
        for mail in mails.iterator(chunk_size=200):
            for item in mail.attachments or []:
                name = item.get("path", "") if isinstance(item, dict) else ""
                if not name.startswith("outbox/") or name in seen:
                    continue
                seen.add(name)
                self._file(private_storage(), name, mail.encryption_org_id)

    def _file(self, storage, name: str, owner) -> None:
        if not storage.exists(name):
            self.counts["missing"] += 1
            return
        if storage.is_encrypted(name) != self.entschluesseln:
            self.counts["skipped"] += 1
            return
        if not self.probe:
            if self.entschluesseln:
                _rewrite(storage, name, _decrypt)
            else:
                org_id = owner()
                if org_id is None:
                    from organizations.models import Organization

                    org_id = Organization.platform().pk
                key_id, key = crypto.key_for_org(org_id)
                _rewrite(
                    storage, name, lambda src, k=key_id, v=key: crypto.encrypt_chunks(src, k, v)
                )
        self.counts["done"] += 1


def _decrypt(source):
    reader = crypto.open_plain(source)
    while True:
        chunk = reader.read(crypto.CHUNK)
        if not chunk:
            return
        yield chunk
