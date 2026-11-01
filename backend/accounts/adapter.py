from allauth.account.adapter import DefaultAccountAdapter
from allauth.headless.adapter import DefaultHeadlessAdapter


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request) -> bool:
        # Konten werden von Verwaltenden angelegt, nicht selbst registriert.
        return False

    def send_mail(self, template_prefix, email, context):
        """Mails von allauth (z. B. „Passwort vergessen“) in der Sprache des Kontos."""
        from django.utils import translation

        from core.i18n import user_language

        user = context.get("user")
        if user is None:
            from .models import User

            user = User.objects.filter(email__iexact=email).first()
        if user is None:
            return super().send_mail(template_prefix, email, context)
        with translation.override(user_language(user)):
            return super().send_mail(template_prefix, email, context)


class HeadlessAdapter(DefaultHeadlessAdapter):
    def serialize_user(self, user) -> dict:
        data = super().serialize_user(user)
        # Mit Startpasswort angemeldet: die Oberfläche verlangt zuerst ein eigenes Passwort
        data["must_change_password"] = bool(getattr(user, "must_change_password", False))
        if getattr(user, "pk", None):
            from core.i18n import user_language

            from .mfa_policy import status

            # Sprache des Kontos: die Oberfläche lädt neu, wenn sie anders angezeigt wird
            data["language"] = user_language(user)

            data.update(status(user))
        return data
