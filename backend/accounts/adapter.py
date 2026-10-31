from allauth.account.adapter import DefaultAccountAdapter
from allauth.headless.adapter import DefaultHeadlessAdapter


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request) -> bool:
        # Konten werden von Verwaltenden angelegt, nicht selbst registriert.
        return False


class HeadlessAdapter(DefaultHeadlessAdapter):
    def serialize_user(self, user) -> dict:
        data = super().serialize_user(user)
        # Mit Startpasswort angemeldet: die Oberfläche verlangt zuerst ein eigenes Passwort
        data["must_change_password"] = bool(getattr(user, "must_change_password", False))
        if getattr(user, "pk", None):
            from .mfa_policy import status

            data.update(status(user))
        return data
