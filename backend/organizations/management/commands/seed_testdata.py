"""Demodaten für den Testserver: Pilotorganisationen mit erfundenen Mitgliedern.

    python manage.py seed_testdata [--password PASSWORT] [--reset-passwords]
    python manage.py seed_testdata --remove-legacy-demo [--dry-run]

- Organisationen: die Pilotorganisationen (Dachverband und Verein mit 14 Zügen).
- Mitglieder, Kontakte, Zusatzfelder, Jubiläen, Kassendaten, Satzungen, Dokumente, Termine
  Impressumsangaben (Plattform, Dachverband, Verein) und die Webseite des Vereins
  (Wartungsmodus, Domain auf .test, erfundene Königsliste) sind erfunden
  (E-Mail-Adressen auf .test, IBAN mit erfundener Bankleitzahl). Der Befehl ist
  wiederholbar und ändert vorhandene Daten nicht.
- Testzugänge: Plattform, Vorstand Dachverband, Vorstand Verein, Kassierer.
  Ohne --password wird ein zufälliges Passwort erzeugt und einmal ausgegeben;
  bestehende Konten behalten ihr Passwort, außer mit --reset-passwords.
- --remove-legacy-demo entfernt die früheren Demo-Organisationen samt Zugängen,
  Mitgliedern, Buchungen, Satzungen, Fotos und Dateien. Andere Daten (z. B. Admin-Zugänge) bleiben.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from access.catalog import (
    AUDIT_VIEW,
    DEFAULT_MODULES,
    DOCS_MANAGE,
    DOCS_VIEW,
    EVENTS_MANAGE,
    EXPORT_RUN,
    FINANCE_EDIT,
    FINANCE_VIEW,
    MEMBERS_EDIT,
    MEMBERS_VIEW,
    codes_for,
)
from access.models import Role, RoleAssignment
from accounts.models import User, generate_initial_password
from core.tenancy import rls_bypass
from organizations.demo import remove_legacy_demo
from organizations.models import Department, DepartmentRole, Organization

FEDERATION_NAME = "Bürger-Schützenverein Neuss-Grimlinghausen von 1855 e.V."
CLUB_NAME = "Hubertus-Schützenverein Neuss-Grimlinghausen von 1920"

FEDERATION = {
    "founding_year": 1855,
    "street": "Am Schützenplatz 1",
    "postal_code": "41468",
    "city": "Neuss",
    "contact_email": "info@bsv-grimlinghausen.test",
    "primary_color": "#1f4e2c",
    "accent_color": "#c9a227",
    "federation_member_access": "read",
    "short_name": "BSV",
}

CLUB = {
    "founding_year": 1920,
    "street": "Hubertusweg 1",
    "postal_code": "41468",
    "city": "Neuss",
    "contact_email": "vorstand@hubertus-grimlinghausen.test",
    "department_label": "Zug",
    "department_label_plural": "Züge",
    "department_label_gender": "m",
    "allow_multiple_departments": False,
}

# Die Züge des Vereins – genau diese, in dieser Reihenfolge
ZUEGE = [
    "Herolde",
    "Strauchdiebe",
    "Hippelänger Prachtkerle",
    "Rose vom Rhein",
    "Drüje Fuchs",
    "Dörper Jonge",
    "Dööschtije Jonge",
    "Dicke Fründe",
    "Hippelänger Gömbötz",
    "Die härtesten unter der Sonne",
    "Wesse mer noch net",
    "Jot drop",
    "De Zojetrockene",
    "Hubertus Fanfaren-Corps",
]
# Typische Rollen in einem Zug, in dieser Reihenfolge (nur zur Information, ohne Rechte)
ZUG_ROLES = ["Oberleutnant", "Leutnant", "Spieß", "Kassierer", "Schriftführer"]
# Frühere Demo-Rolle, die in „Oberleutnant“ aufgeht
OLD_ZUG_ROLES = {"Zugführer": "Oberleutnant"}

CLUB_ROLES = {
    "Vorstand": None,  # alle Rechte
    "Kassierer": [MEMBERS_VIEW, EXPORT_RUN, FINANCE_VIEW, FINANCE_EDIT],
    "Schriftführer": [
        MEMBERS_VIEW,
        MEMBERS_EDIT,
        AUDIT_VIEW,
        EVENTS_MANAGE,
        DOCS_VIEW,
        DOCS_MANAGE,
    ],
}

# (E-Mail, Vorname, Nachname, [(Organisation, Rolle), …]) – alle Daten erfunden
USERS = [
    ("plattform@hubiplan.test", "Paula", "Plattform", [("platform", "Plattform-Administration")]),
    ("vorstand@bsv-grimlinghausen.test", "Bernd", "Brudermeister", [("federation", "Vorstand")]),
    ("vorstand@hubertus-grimlinghausen.test", "Hanna", "Hubertus", [("club", "Vorstand")]),
    ("kasse@hubertus-grimlinghausen.test", "Kai", "Kassenwart", [("club", "Kassierer")]),
]


def default_modules() -> list[str]:
    """Standard für neue Organisationen: alle schaltbaren Module außer der Webseite."""
    return list(DEFAULT_MODULES)


class Command(BaseCommand):
    help = "Demodaten der Pilotorganisationen anlegen bzw. alte Demodaten entfernen."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Passwort für alle Testzugänge")
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Passwort auch für bereits vorhandene Testzugänge setzen",
        )
        parser.add_argument(
            "--remove-legacy-demo",
            action="store_true",
            help="Frühere Demo-Organisationen samt Zugängen, Mitgliedern und Dateien löschen",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Nur anzeigen, was gelöscht würde"
        )

    def handle(self, *args, **options):
        if options["remove_legacy_demo"]:
            report = remove_legacy_demo(dry_run=options["dry_run"])
            prefix = "Würde löschen" if options["dry_run"] else "Gelöscht"
            for line in report:
                self.stdout.write(f"{prefix}: {line}")
            if not report:
                self.stdout.write("Keine alten Demodaten gefunden.")
            return
        password = options["password"] or generate_initial_password()
        with transaction.atomic(), rls_bypass():
            orgs = self.create_organizations()
            self.create_roles(orgs)
            created = self.create_users(orgs, password, options["reset_passwords"])
            from members.seed import seed_members

            seed_members(orgs)
            from finance.seed import seed_finance

            seed_finance(orgs)
            from statutes.seed import seed_statutes

            seed_statutes(orgs)
            from documents.seed import seed_documents

            seed_documents(orgs)
            from events.seed import seed_events

            seed_events(orgs)
            from finance.seed import seed_projects

            seed_projects(orgs)
            from organizations.imprint_seed import seed_imprints

            seed_imprints(orgs)
            from letterhead.seed import seed_letterheads

            seed_letterheads(orgs)
            from website.seed import seed_website

            seed_website(orgs)
        self.stdout.write(self.style.SUCCESS("Demodaten angelegt."))
        if created and not options["password"]:
            self.stdout.write(f"Passwort der neuen Testzugänge: {password}")

    def create_organizations(self) -> dict[str, Organization]:
        platform = Organization.platform()
        federation, _ = Organization.objects.get_or_create(
            type=Organization.Type.FEDERATION,
            name=FEDERATION_NAME,
            defaults={**FEDERATION, "parent": platform, "enabled_modules": default_modules()},
        )
        club, _ = Organization.objects.get_or_create(
            type=Organization.Type.CLUB,
            name=CLUB_NAME,
            defaults={**CLUB, "parent": federation, "enabled_modules": default_modules()},
        )
        for order, (name, year) in enumerate(
            zip(ZUEGE, [1920 + 5 * i for i in range(len(ZUEGE))], strict=True), start=1
        ):
            zug, _ = Department.objects.get_or_create(
                organization=club, name=name, defaults={"founding_year": year, "sort_order": order}
            )
            for old, new in OLD_ZUG_ROLES.items():
                if not DepartmentRole.objects.filter(department=zug, name=new).exists():
                    DepartmentRole.objects.filter(department=zug, name=old).update(name=new)
            for position, name in enumerate(ZUG_ROLES, start=1):
                role, _ = DepartmentRole.objects.get_or_create(
                    organization=club, department=zug, name=name, defaults={"position": position}
                )
                if role.position != position:
                    role.position = position
                    role.save(update_fields=["position"])
        return {"platform": platform, "federation": federation, "club": club}

    def create_roles(self, orgs: dict[str, Organization]) -> None:
        Role.objects.get_or_create(
            organization=orgs["platform"],
            name="Plattform-Administration",
            defaults={"permissions": codes_for("platform"), "is_board": False},
        )
        Role.objects.get_or_create(
            organization=orgs["federation"],
            name="Vorstand",
            defaults={"permissions": codes_for("federation")},
        )
        for name, perms in CLUB_ROLES.items():
            perms = codes_for("club") if perms is None else perms
            role, created = Role.objects.get_or_create(
                organization=orgs["club"], name=name, defaults={"permissions": perms}
            )
            # Neue Rechte ergänzen (z. B. Kasse), vorhandene nicht wegnehmen
            missing = [p for p in perms if p not in role.permissions]
            if not created and missing:
                role.permissions = [*role.permissions, *missing]
                role.save(update_fields=["permissions"])

    def create_users(self, orgs, password: str, reset: bool) -> int:
        created_count = 0
        for email, first, last, roles in USERS:
            user, created = User.objects.get_or_create(
                email=email, defaults={"first_name": first, "last_name": last}
            )
            if created or reset:
                user.set_password(password)
                user.save()
                created_count += int(created)
            for org_key, role_name in roles:
                org = orgs[org_key]
                role = Role.objects.get(organization=org, name=role_name)
                RoleAssignment.objects.get_or_create(
                    organization=org, role=role, user=user, defaults={"valid_from": "2020-01-01"}
                )
        return created_count
