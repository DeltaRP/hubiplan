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


class Command(BaseCommand):
    help = "Werte in verschlüsselten Feldern verschlüsseln (oder zurück)."

    def add_arguments(self, parser):
        parser.add_argument("--entschluesseln", action="store_true")
        parser.add_argument("--probe", action="store_true", help="Nur zählen.")

    def handle(self, *args, entschluesseln=False, probe=False, **options):
        changed = 0
        with rls_bypass():
            for model, fields in encrypted_fields():
                table = connection.ops.quote_name(model._meta.db_table)
                columns = ", ".join(connection.ops.quote_name(f.column) for f in fields)
                with connection.cursor() as cursor:
                    # Namen aus den Modellen, gequotet; Werte nur als Parameter
                    cursor.execute(f"SELECT id, {columns} FROM {table} ORDER BY id")  # noqa: S608
                    rows = cursor.fetchall()
                for row in rows:
                    pk, values = row[0], row[1:]
                    updates = {}
                    for field, raw in zip(fields, values, strict=True):
                        if raw in ("", None):
                            continue
                        encrypted, value = _stored(field, raw)
                        if entschluesseln and encrypted:
                            plain = decrypt_text(value, field)
                            updates[field] = (
                                plain
                                if not isinstance(field, EncryptedJSONField)
                                else json.loads(plain)
                            )
                        elif not entschluesseln and not encrypted:
                            obj = model._base_manager.only(*{"pk", *self._owner_fields(model)}).get(
                                pk=pk
                            )
                            text = (
                                json.dumps(value, ensure_ascii=False)
                                if isinstance(field, EncryptedJSONField)
                                else value
                            )
                            cipher = encrypt_text(text, owner_org_id(obj), field)
                            updates[field] = (
                                {field.KEY: cipher}
                                if isinstance(field, EncryptedJSONField)
                                else cipher
                            )
                    if updates and not probe:
                        self._write(table, pk, updates)
                    changed += bool(updates)
        verb = "entschlüsselt" if entschluesseln else "verschlüsselt"
        self.stdout.write(f"{changed} Datensätze {'zu ' if probe else ''}{verb}.")

    @staticmethod
    def _owner_fields(model):
        names = {f.attname for f in model._meta.concrete_fields}
        return [n for n in ("organization_id", "scope_id") if n in names] or list(names)

    @staticmethod
    def _write(table, pk, updates):
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
            sql = f"UPDATE {table} SET {', '.join(parts)} WHERE id = %s"  # noqa: S608
            cursor.execute(sql, [*params, pk])
