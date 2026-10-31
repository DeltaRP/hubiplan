"""Tägliche Prüfung der Protokollketten (Finanzamt-Prüfung C3)."""

from celery import shared_task

from core.tenancy import rls_bypass


@shared_task
def check_chains() -> int:
    """Versiegelt liegen gebliebene Einträge, prüft jede Kette und meldet Brüche."""
    from core.alarm import send_alert

    from .chain import seal, verify
    from .models import AuditCheck, AuditEntry

    with rls_bypass():
        # order_by(): sonst stünde die Standardsortierung im DISTINCT (Einheit je Eintrag)
        org_ids = sorted(
            set(AuditEntry.objects.order_by().values_list("organization_id", flat=True).distinct())
        )
        before = {
            c.organization_id: c.ok for c in AuditCheck.objects.filter(organization_id__in=org_ids)
        }
    broken = []
    for org_id in org_ids:
        seal(org_id)
        result = verify(org_id)
        if not result["ok"] and before.get(org_id, True):
            broken.append((org_id, result["problems"]))
    if broken:
        from organizations.models import Organization

        with rls_bypass():
            names = dict(
                Organization.objects.filter(pk__in=[o for o, _ in broken]).values_list("pk", "name")
            )
        lines = []
        for org_id, problems in broken:
            lines.append(f"{names.get(org_id, org_id)}:")
            lines.extend(f"  {p}" for p in problems)
        send_alert("Änderungsprotokoll wurde verändert", lines)
    return len(org_ids)
