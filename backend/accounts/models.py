import datetime
import secrets
import string

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone

# Startpasswörter gelten nur kurz und müssen bei der ersten Anmeldung ersetzt werden
# (Gesamtaudit 31.10.b, AT-S04): Wer das Konto eingerichtet hat, kennt sie.
INITIAL_PASSWORD_DAYS = 7


def generate_initial_password(length: int = 16) -> str:
    """Startpasswort für neu angelegte Konten (wird einmalig angezeigt)."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def set_initial_password(user: "User") -> str:
    """Startpasswort setzen (gilt ``INITIAL_PASSWORD_DAYS`` Tage); Rückgabe zum Anzeigen."""
    password = generate_initial_password()
    user.set_password(password)
    user.initial_password_expires = timezone.now() + datetime.timedelta(days=INITIAL_PASSWORD_DAYS)
    return password


class UserManager(BaseUserManager):
    """Manager für Benutzer mit E-Mail-Adresse als Login (kein Benutzername)."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError("Eine E-Mail-Adresse ist erforderlich.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("Superuser brauchen is_staff=True und is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Plattform-Benutzerkonto. Login ist die E-Mail-Adresse.

    Ein Konto ist nicht dasselbe wie ein Vereinsmitglied: Mitglieder (Personen)
    und ihre Rollen je Organisation kommen in späteren Meilensteinen dazu.
    """

    username = None
    email = models.EmailField("E-Mail-Adresse", unique=True)
    # Lernhilfen: Hauptschalter und die „Warum?“-Erklärungen, die der Nutzer
    # ausgeblendet hat (nur Schlüssel). Reine Anzeigepräferenz.
    learning_aids = models.BooleanField("Lernhilfen zeigen", default=True)
    learning_hidden = models.JSONField("ausgeblendete Erklärungen", null=True, blank=True)
    # Gesetzt, solange das Konto noch das ausgegebene Startpasswort hat: Es muss bei der
    # ersten Anmeldung ersetzt werden und wird nach Ablauf unbrauchbar (AT-S04)
    initial_password_expires = models.DateTimeField(
        "Startpasswort gültig bis", null=True, blank=True
    )
    # Pflicht-2FA (Gesamtaudit 31.10.b, Frage 1): bis dahin einrichten, sonst ruhen heikle Rechte
    mfa_required_by = models.DateTimeField(
        "Zwei-Faktor-Anmeldung einrichten bis", null=True, blank=True
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "Benutzer"
        verbose_name_plural = "Benutzer"

    def __str__(self) -> str:
        return self.email

    def set_password(self, raw_password) -> None:
        # Jedes selbst gesetzte Passwort (Mein Konto, Zurücksetzen) ersetzt das Startpasswort
        super().set_password(raw_password)
        self.initial_password_expires = None

    def save(self, *args, **kwargs):
        fields = kwargs.get("update_fields")
        if fields is not None and "password" in fields:
            kwargs["update_fields"] = {*fields, "initial_password_expires"}
        super().save(*args, **kwargs)

    @property
    def must_change_password(self) -> bool:
        return self.initial_password_expires is not None


class EmailChange(models.Model):
    """Bestätigungslink für eine neue Anmelde-E-Mail (nur der Hash des Tokens)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_changes")
    new_email = models.EmailField("neue E-Mail-Adresse")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "E-Mail-Änderung"
        verbose_name_plural = "E-Mail-Änderungen"

    def __str__(self) -> str:
        return f"{self.user} → {self.new_email}"


class StoredSignature(models.Model):
    """Hinterlegte Unterschrift einer Person (Mein Konto › Unterschrift).

    Nur die Form (Linienzüge, siehe finance/signature.py). Verwendet wird sie nur, wenn die
    Person selbst eine Quittung abschließt."""

    user = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="stored_signature"
    )
    strokes = models.JSONField("Unterschrift")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "hinterlegte Unterschrift"
        verbose_name_plural = "hinterlegte Unterschriften"

    def __str__(self) -> str:
        return f"Unterschrift {self.user_id}"
