from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Kern"

    def ready(self) -> None:
        # Registriert den Rollenwechsel (SET ROLE hubiplan_app) für jede neue
        # Datenbankverbindung – in Web-Anfragen, Celery-Jobs und Verwaltungsbefehlen.
        from . import tenancy  # noqa: F401

        # Alarm-Mails bei neuen Plattformzugängen und Superusern
        from .alarm import connect

        connect()
