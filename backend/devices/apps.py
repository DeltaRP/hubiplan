from django.apps import AppConfig


class DevicesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "devices"
    verbose_name = "Geräte (App)"

    def ready(self) -> None:
        from . import auth, signals  # noqa: F401  (auth: OpenAPI-Erweiterungen)

        signals.connect()
