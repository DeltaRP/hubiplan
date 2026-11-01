from django.apps import AppConfig


class OidcConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "oidc"
    verbose_name = "Anmeldung für andere Dienste (OpenID Connect)"
