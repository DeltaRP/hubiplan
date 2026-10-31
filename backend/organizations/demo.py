"""Alte Demodaten sauber entfernen.

Als Demo gelten genau die früheren Demo-Organisationen (feste Namensliste) und
Testzugänge mit E-Mail-Adresse auf ``.test``, die danach keiner Organisation mehr
zugeordnet sind. Superuser und Staff-Konten werden nie gelöscht.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q

from core.tenancy import rls_bypass

LEGACY_DEMO_ORGS = [
    # Vereine zuerst, dann der Dachverband (Vereine hängen an ihm)
    "Schützenverein Musterstadt 1890 e. V.",
    "Turnverein Beispielhausen e. V.",
    "Schachfreunde Testdorf",
    "Schützenbund Musterland e. V.",
]


def _delete_files(org) -> int:
    """Dateien im Speicher entfernen (Datenbankzeilen löschen die Kaskaden)."""
    from documents.models import DocumentVersion
    from exchange.models import ExportJob, ImportJob
    from finance.models import Receipt
    from members.photo_models import MemberPhoto
    from organizations.models import Department
    from statutes.models import StatuteVersion

    count = 0
    for photo in MemberPhoto.objects.filter(organization=org):
        photo.delete_files()
        count += 1
    for job in ExportJob.objects.filter(organization=org):
        if job.file:
            job.file.delete(save=False)
            count += 1
    for job in ImportJob.objects.filter(organization=org):
        for f in (job.file, job.error_file):
            if f:
                f.delete(save=False)
                count += 1
    for version in StatuteVersion.objects.filter(organization=org):
        version.file.delete(save=False)
        count += 1
    for doc_version in DocumentVersion.objects.filter(organization=org):
        doc_version.file.delete(save=False)
        count += 1
    for receipt in Receipt.objects.filter(organization=org):
        if receipt.file:
            receipt.file.delete(save=False)
            count += 1
    for owner in [org, *Department.objects.filter(organization=org)]:
        if owner.logo:
            owner.logo.delete(save=False)
            count += 1
    return count


def _delete_org(org) -> None:
    from finance.models import Account, Booking, Category
    from members.models import Membership, Person, TransferRequest

    # Kasse zuerst: Buchungen schützen ihre Konten und Kategorien vor dem Löschen
    Booking.objects.filter(organization=org).delete()
    Account.objects.filter(organization=org).delete()
    Category.objects.filter(organization=org).delete()
    TransferRequest.objects.filter(Q(from_org=org) | Q(to_org=org) | Q(scope=org)).delete()
    # Mitgliedschaften zuerst (Zeiträume, Arten, Abteilungen, Fotos, Zugänge hängen daran)
    Membership.objects.filter(organization=org).delete()
    # Personen dieses Verbandsbereichs, die nirgends mehr Mitglied sind
    Person.objects.filter(scope=org, memberships__isnull=True).delete()
    org.delete()


@transaction.atomic
def remove_legacy_demo(dry_run: bool = False) -> list[str]:
    from accounts.models import User
    from members.models import Membership
    from organizations.models import Organization

    report: list[str] = []
    with rls_bypass():
        orgs = [
            org
            for name in LEGACY_DEMO_ORGS
            for org in Organization.objects.filter(name=name).exclude(type__in=["platform", "unit"])
        ]
        for org in orgs:
            members = Membership.objects.filter(organization=org).count()
            report.append(f"Organisation „{org.name}“ ({members} Mitgliedschaften)")
            if not dry_run:
                files = _delete_files(org)
                _delete_org(org)
                if files:
                    report.append(f"  {files} Dateien")
        # Testzugänge ohne verbleibende Zuordnung
        candidates = User.objects.filter(
            email__iendswith=".test", is_superuser=False, is_staff=False
        )
        for user in candidates:
            has_role = user.role_assignments.exists()
            has_portal = hasattr(user, "portal_accesses") and user.portal_accesses.exists()
            orphan = not has_role and not has_portal
            # Im Probelauf zählen auch Zugänge, die erst nach dem Löschen verwaist wären
            if dry_run and not orphan:
                orphan = not user.role_assignments.exclude(organization__in=orgs).exists() and not (
                    hasattr(user, "portal_accesses")
                    and user.portal_accesses.exclude(organization__in=orgs).exists()
                )
            if orphan:
                report.append(f"Zugang {user.email}")
                if not dry_run:
                    user.delete()
    # Erst nach dem Verlassen des RLS-Kontexts (der dabei noch eine Abfrage stellt)
    if dry_run:
        transaction.set_rollback(True)
    return report
