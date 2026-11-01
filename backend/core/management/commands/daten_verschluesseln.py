"""Vorhandene Werte in verschlüsselten Feldern verschlüsseln (einmalig nach dem
Ausrollen) oder für den Rückweg auf eine ältere Fassung wieder entschlüsseln
(``--entschluesseln``). Wiederholbar; schreibt direkt in die Spalten (keine Signale,
kein Änderungsprotokoll, ``updated_at`` bleibt). Vorher ein frisches Backup anlegen.
"""

from __future__ import annotations

import json

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from core.encfields import (
    EncryptedJSONField,
    EncryptedMixin,
    decrypt_text,
    encrypt_text,
    is_encrypted,
    owner_org_id,
)
from core.tenancy import rls_bypass


def encrypted_fields():
    for model in apps.get_models():
        fields = [f for f in model._meta.concrete_fields if isinstance(f, EncryptedMixin)]
        if fields:
            yield model, fields


def _stored(field, raw):
    """(verschlüsselt?, Chiffrat-Text oder Klartextwert) aus dem Spalteninhalt."""
    if isinstance(field, EncryptedJSONField):
        value = json.loads(raw) if isinstance(raw, str) else raw
        if field._wrapped(value):
            return True, value[field.KEY]
        return False, value
    return is_encrypted(raw), raw


BATCH = 1000


def _owner_columns(model) -> list[str]:
    names = {f.attname for f in model._meta.concrete_fields}
    return [n for n in ("organization_id", "scope_id") if n in names]


class Command(BaseCommand):
    help = "Werte in verschlüsselten Feldern verschlüsseln (oder zurück)."

    def add_arguments(self, parser):
        parser.add_argument("--entschluesseln", action="store_true")
        parser.add_argument("--probe", action="store_true", help="Nur zählen.")

    def handle(self, *args, entschluesseln=False, probe=False, **options):
        total = 0
        with rls_bypass():
            for model, fields in encrypted_fields():
                changed = self._model(model, fields, entschluesseln, probe)
                if changed:
                    self.stdout.write(f"  {model._meta.label}: {changed}")
                total += changed
        verb = "entschlüsselt" if entschluesseln else "verschlüsselt"
        self.stdout.write(f"{total} Datensätze {'zu ' if probe else ''}{verb}.")

    def _model(self, model, fields, entschluesseln, probe) -> int:
        table = connection.ops.quote_name(model._meta.db_table)
        pk_col = connection.ops.quote_name(model._meta.pk.column)
        owner_cols = [] if hasattr(model, "encryption_org_id") else _owner_columns(model)
        columns = ", ".join(
            connection.ops.quote_name(c) for c in [*(f.column for f in fields), *owner_cols]
        )
        changed = 0
        last = None
        while True:
            # Namen aus den Modellen, gequotet; Werte nur als Parameter. In Blöcken nach id,
            # damit große Tabellen (Protokoll) nicht auf einmal im Speicher liegen.
            where, params = (f"WHERE {pk_col} > %s", [last]) if last is not None else ("", [])
            with connection.cursor() as cursor:
                sql = f"SELECT {pk_col}, {columns} FROM {table} {where}"  # noqa: S608
                cursor.execute(f"{sql} ORDER BY {pk_col} LIMIT {BATCH}", params)
                rows = cursor.fetchall()
            if not rows:
                return changed
            last = rows[-1][0]
            owners = None
            for row in rows:
                pk, values = row[0], row[1 : 1 + len(fields)]
                owner_values = row[1 + len(fields) :]
                updates = {}
                for field, raw in zip(fields, values, strict=True):
                    encrypted, value = _stored(field, raw)
                    if not encrypted and field._stays_plain(value):
                        continue
                    if entschluesseln and encrypted:
                        plain = decrypt_text(value, field)
                        updates[field] = (
                            json.loads(plain) if isinstance(field, EncryptedJSONField) else plain
                        )
                    elif not entschluesseln and not encrypted:
                        if owner_cols:
                            org_id = next((v for v in owner_values if v is not None), None)
                        else:
                            if owners is None:
                                owners = model._base_manager.in_bulk([r[0] for r in rows])
                            org_id = owner_org_id(owners[pk])
                        text = (
                            json.dumps(value, ensure_ascii=False)
                            if isinstance(field, EncryptedJSONField)
                            else value
                        )
                        cipher = encrypt_text(text, org_id, field)
                        updates[field] = (
                            {field.KEY: cipher} if isinstance(field, EncryptedJSONField) else cipher
                        )
                if updates and not probe:
                    self._write(table, pk_col, pk, updates)
                changed += bool(updates)

    @staticmethod
    def _write(table, pk_col, pk, updates):
        parts, params = [], []
        for field, value in updates.items():
            column = connection.ops.quote_name(field.column)
            if isinstance(field, EncryptedJSONField):
                parts.append(f"{column} = %s::jsonb")
                params.append(json.dumps(value, ensure_ascii=False))
            else:
                parts.append(f"{column} = %s")
                params.append(value)
        with transaction.atomic(), connection.cursor() as cursor:
            sql = f"UPDATE {table} SET {', '.join(parts)} WHERE {pk_col} = %s"  # noqa: S608
            cursor.execute(sql, [*params, pk])
