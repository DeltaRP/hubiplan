"""Legt die eingeschränkte Datenbankrolle an und vergibt ihre Rechte (idempotent).

Läuft bei jedem Start des Backends nach den Migrationen – so stimmen die Rechte
auch nach einer Wiederherstellung aus einem Backup (das keine Rechte enthält).

Ist ``APP_DB_PASSWORD`` gesetzt, darf sich die Rolle mit diesem Passwort anmelden.
Backend, Worker und Beat verbinden sich dann direkt als hubiplan_app statt als
Datenbank-Superuser (siehe docker-compose.server.yml).
"""

import os

from django.core.management.base import BaseCommand
from django.db import connection

from core.rls import app_login_sql, create_app_role_sql


class Command(BaseCommand):
    help = "Rolle hubiplan_app anlegen und Rechte vergeben (nur PostgreSQL)."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write("Keine PostgreSQL-Datenbank – nichts zu tun.")
            return
        with connection.cursor() as cursor:
            cursor.execute(create_app_role_sql())
            password = os.environ.get("APP_DB_PASSWORD", "")
            if password:
                cursor.execute(app_login_sql(password, connection.connection))
                self.stdout.write("Rolle hubiplan_app darf sich mit Passwort anmelden.")
        self.stdout.write(self.style.SUCCESS("Rechte der Rolle hubiplan_app gesetzt."))
