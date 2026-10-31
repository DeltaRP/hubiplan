from django.apps import AppConfig


class DatatransferConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "datatransfer"
    verbose_name = "Datenübernahme (JSON-Export und -Import)"
