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
    from django.contrib.auth import get_user_model
    from django.utils.translation import gettext

    from core.i18n import language_of

    with rls_bypass():
        user = get_user_model().objects.filter(pk=access[1]).first()
    # Sprache beim Senden bestimmen, damit eine zwischendurch geänderte Einstellung gilt
    with language_of(user):
        title = gettext(title)
    data = {"v": 1, "t": "info", "access": access[0], "title": title, "text": text}
    return send_to_user(access[1], data)
