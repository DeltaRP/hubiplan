from celery import shared_task

from core.tenancy import rls_bypass

from . import services


@shared_task
def deliver_coupling(coupling_id: int) -> None:
    with rls_bypass():
        services.deliver(coupling_id)


@shared_task
def deliver_due() -> None:
    with rls_bypass():
        services.deliver_due()


@shared_task
def sync_all() -> None:
    """Geänderte Stände aller aktiven Kopplungen in den Postausgang legen."""
    with rls_bypass():
        services.sync_all()


@shared_task
def reconcile_all() -> None:
    """Täglicher Abgleich der Prüfsummen mit allen Partnern."""
    with rls_bypass():
        services.reconcile_all()


@shared_task
def announce_keys() -> None:
    """Neue Schlüssel allen Gegenstellen mitteilen (nach einem Wechsel)."""
    from . import keys

    with rls_bypass():
        keys.announce_all()


@shared_task
def keys_daily() -> None:
    """Täglich: alte Schlüssel löschen, nach einem Jahr wechseln, Ankündigung wiederholen."""
    from . import keys

    with rls_bypass():
        keys.daily()
