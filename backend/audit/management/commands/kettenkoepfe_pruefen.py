"""Kettenköpfe aus dem externen Backup mit dem Änderungsprotokoll abgleichen (FQ-17).

Das Backup (deploy/backup/backup.sh) schreibt jeden Tag je Organisation Nummer und
Prüfsumme des zuletzt geprüften Protokolleintrags nach ``kettenkoepfe.log``; restic
bewahrt ältere Stände bei Hetzner auf. Dieser Befehl liest so eine Datei (Zeilen
„STEMPEL ORG NUMMER PRÜFSUMME“) und meldet, wo die Datenbank davon abweicht: Eintrag
fehlt oder hat eine andere Prüfsumme. Ausgabe nur Kennungen, keine Inhalte."""

from django.core.management.base import BaseCommand, CommandError

from audit.models import AuditEntry
from core.tenancy import rls_bypass


def check_heads(lines) -> tuple[int, list[str]]:
    """Rückgabe: (geprüfte Köpfe, Abweichungen)."""
    heads: dict[tuple[int, int], str] = {}
    for raw in lines:
        parts = raw.split()
        if len(parts) != 4:
            continue
        try:
            heads[(int(parts[1]), int(parts[2]))] = parts[3]
        except ValueError:
            continue
    problems = []
    with rls_bypass():
        for (org, seq), digest in sorted(heads.items()):
            stored = (
                AuditEntry.objects.filter(organization_id=org, seq=seq)
                .values_list("hash", flat=True)
                .first()
            )
            if stored is None:
                problems.append(f"Organisation {org}: Eintrag Nr. {seq} fehlt.")
            elif stored != digest:
                problems.append(f"Organisation {org}: Eintrag Nr. {seq} wurde verändert.")
    return len(heads), problems


class Command(BaseCommand):
    help = "Gleicht kettenkoepfe.log aus dem Backup mit dem Änderungsprotokoll ab."

    def add_arguments(self, parser):
        parser.add_argument("datei", help="kettenkoepfe.log (z. B. aus restic zurückgeholt)")

    def handle(self, *args, **options):
        try:
            with open(options["datei"], encoding="utf-8") as f:
                count, problems = check_heads(f)
        except OSError as exc:
            raise CommandError(f"Datei nicht lesbar: {exc}") from exc
        for line in problems:
            self.stdout.write(line)
        self.stdout.write(f"{count} Kettenköpfe geprüft, {len(problems)} Abweichungen.")
        if problems:
            raise CommandError("Das Änderungsprotokoll weicht vom Backup ab.")
