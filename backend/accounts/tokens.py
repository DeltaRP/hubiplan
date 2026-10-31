"""Links zum Passwort-Festlegen: Einladungen gelten länger als „Passwort vergessen“.

Ein neu angelegtes Konto ohne Passwort, das sich noch nie angemeldet hat, bekommt eine
Einladung per Mail (FQ-2 aus dem Gesamtaudit 31.10.b, statt Startpasswort). Deren Link
gilt ``INVITATION_DAYS`` Tage. Für alle anderen gilt die normale Frist
``PASSWORD_RESET_TIMEOUT``. Der Link ist wie bisher nur einmal nutzbar, weil sich mit
dem neuen Passwort der Hashwert ändert.
"""

from __future__ import annotations

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int

INVITATION_DAYS = 7


def is_invitation(user) -> bool:
    return user is not None and user.last_login is None and not user.has_usable_password()


class InvitationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp) -> str:
        # Wie allauths EmailAwarePasswordResetTokenGenerator (dessen Modul lädt diese
        # Klasse beim Import, daher hier nachgebildet): Adressänderung macht Links ungültig
        from allauth.account.internal.flows.manage_email import sync_user_email_address
        from allauth.account.models import EmailAddress
        from allauth.account.utils import user_email

        ret = super()._make_hash_value(user, timestamp)
        sync_user_email_address(user)
        email = user_email(user)
        emails = {email} if email else set()
        emails.update(EmailAddress.objects.filter(user_id=user.pk).values_list("email", flat=True))
        return ret + "|".join(sorted(emails))

    def check_token(self, user, token):
        if super().check_token(user, token):
            return True
        if not (token and is_invitation(user)):
            return False
        try:
            ts_b36, _ = token.split("-")
            ts = base36_to_int(ts_b36)
        except ValueError:
            return False
        if self._num_seconds(self._now()) - ts > INVITATION_DAYS * 86400:
            return False
        return any(
            constant_time_compare(self._make_token_with_timestamp(user, ts, secret), token)
            for secret in [self.secret, *self.secret_fallbacks]
        )
