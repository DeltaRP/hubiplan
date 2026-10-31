from django.apps import AppConfig


class StatutesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "statutes"
    verbose_name = "Satzungen"

    def ready(self):
        from . import signals  # noqa: F401
