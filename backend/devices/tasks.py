"""Hintergrund-Jobs der App: Hinweise per Push."""

from celery import shared_task

from core.tenancy import rls_bypass


@shared_task
def notify_membership(membership_id: int, title: str, text: str) -> int:
    """Hinweis an die App des Mitglieds (z. B. „Deine Änderung wurde übernommen“)."""
    from portal.models import PortalAccess

    from .push import send_to_user

    with rls_bypass():
        access = (
            PortalAccess.objects.filter(membership_id=membership_id)
            .values_list("pk", "user_id")
            .first()
        )
    if access is None:
        return 0
    data = {"v": 1, "t": "info", "access": access[0], "title": title, "text": text}
    return send_to_user(access[1], data)
