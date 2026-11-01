from django.apps import AppConfig


class PeeringConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "peering"
    verbose_name = "Verbund (Kopplung mit anderen Instanzen)"

    def ready(self):
        # Pakete registrieren sich beim Import
        from . import (  # noqa: F401
            packet_circulars,
            packet_events,
            packet_info,
            packet_invoices,
            packet_members,
            packet_results,
            packet_unit,
            packet_unit_members,
        )
