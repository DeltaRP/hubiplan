"""Rollen je Organisation und ihre Zuordnung zu Benutzerkonten."""

from __future__ import annotations

import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .catalog import DEPARTMENT_CODES, codes_for


class OrgRoleManager(models.Manager):
    """Rollen mit Anmeldung (Benutzerkonten), ohne die Rollen von Untereinheiten."""

    use_in_migrations = True

    def get_queryset(self):
        return super().get_queryset().filter(department__isnull=True)


class Role(models.Model):
    """Rolle einer Einheit, z. B. „Kassierer“ im Verein A oder „Zugführer“ im Zug B.

    Es gibt nur eine Rollenart. Rollen einer Untereinheit ohne eigenen Arbeitsbereich
    gehören zum Datenbereich der Einheit darüber (``organization``) und nennen die
    Untereinheit in ``department``; ihre Inhaber sind Mitgliedschaften
    (``RoleAssignment.membership``). ``Role.objects`` liefert nur die übrigen Rollen,
    ``organizations.DepartmentRole`` nur die der Untereinheiten.
    """

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="roles"
    )
    # Untereinheit, zu der die Rolle gehört (leer: Rolle der Einheit selbst)
    department = models.ForeignKey(
        "organizations.Department",
        on_delete=models.CASCADE,
        related_name="unit_roles",
        null=True,
        blank=True,
    )
    position = models.PositiveSmallIntegerField("Reihenfolge", default=0)
    name = models.CharField("Name", max_length=100)
    description = models.CharField("Beschreibung", max_length=300, blank=True)
    permissions = models.JSONField("Berechtigungen", default=list, blank=True)
    is_board = models.BooleanField(
        "Vorstandsrolle",
        default=True,
        help_text="Vorstandsrollen können als Kontakt der Organisation dienen.",
    )
    represents = models.BooleanField(
        "vertritt die Einheit (§ 26 BGB)",
        default=False,
        help_text="Die Inhaber erscheinen im Impressum als Vertretungsberechtigte.",
    )
    on_letterhead = models.BooleanField(
        "auf dem Briefbogen nennen",
        default=False,
        help_text="Die Inhaber stehen zusätzlich in der Fußzeile der Briefvorlage.",
    )
    contact_email = models.EmailField(
        "Funktionsadresse",
        blank=True,
        help_text="E-Mail-Adresse der Funktion (z. B. kassierer@…), wählbar in der Briefvorlage.",
    )
    on_website = models.BooleanField(
        "auf der Webseite zeigen",
        default=False,
        help_text="Die Inhaber erscheinen auf der Webseite unter Vorstand und Ansprechpartner.",
    )
    website_position = models.PositiveSmallIntegerField("Reihenfolge auf der Webseite", default=0)
    in_chronicle = models.BooleanField(
        "unter „Ämter“ zeigen",
        default=False,
        help_text="Heutige und frühere Inhaber erscheinen auf der Webseite unter "
        "Geschichte › Ämter (z. B. Vorsitzende seit …).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    all_objects = models.Manager()
    objects = OrgRoleManager()

    class Meta:
        verbose_name = "Rolle"
        verbose_name_plural = "Rollen"
        ordering = ["position", "name"]
        # Rückverweise (z. B. ``unit_roles``) sehen alle Rollen
        default_manager_name = "all_objects"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                condition=Q(department__isnull=True),
                name="rolle_name_je_org",
            ),
            models.UniqueConstraint(
                fields=["department", "name"],
                condition=Q(department__isnull=False),
                name="rolle_name_je_untereinheit",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.department if self.department_id else self.organization})"

    def save(self, *args, **kwargs):
        from core.reorder import append_if_new

        if self.department_id:
            self.organization_id = self.department.organization_id
            if self._state.adding:
                self.is_board = False
            siblings = Role.all_objects.filter(department_id=self.department_id)
        else:
            siblings = Role.all_objects.filter(
                organization_id=self.organization_id, department__isnull=True
            )
        # Neue Rollen hinten anstellen; Webseite und HUBIplan haben dieselbe Reihenfolge
        append_if_new(self, "position", siblings)
        self.website_position = self.position
        super().save(*args, **kwargs)

    def clean(self) -> None:
        allowed = (
            set(DEPARTMENT_CODES) if self.department_id else set(codes_for(self.organization.type))
        )
        unknown = sorted(set(self.permissions) - allowed)
        if unknown:
            raise ValidationError(
                {"permissions": f"Für diese Organisation nicht erlaubt: {', '.join(unknown)}"}
            )

    @property
    def holders(self):
        """Inhaber (alle Zuordnungen, auch frühere)."""
        return self.assignments


class RoleAssignmentQuerySet(models.QuerySet):
    def active(self, on: datetime.date | None = None):
        on = on or timezone.localdate()
        return self.filter(
            Q(valid_from__lte=on), Q(valid_until__isnull=True) | Q(valid_until__gte=on)
        )


class OrgAssignmentManager(models.Manager.from_queryset(RoleAssignmentQuerySet)):
    """Zuordnungen zu Benutzerkonten bzw. Akten, ohne Inhaber von Untereinheiten-Rollen."""

    use_in_migrations = True

    def get_queryset(self):
        return super().get_queryset().filter(membership__isnull=True)


def protect_unit_holders(collector, field, sub_objs, using):
    """Rolle löschen: Inhaber aus der Mitgliederverwaltung schützen, sonst mitlöschen.

    Wer eine Untereinheit oder eine ihrer Rollen löschen will, muss die Inhaber vorher
    austragen (wie früher bei den Abteilungsrollen).
    """
    held = [obj for obj in sub_objs if obj.membership_id]
    if held:
        models.PROTECT(collector, field, held, using)
    models.CASCADE(collector, field, sub_objs, using)


class RoleAssignment(models.Model):
    """Benutzer bzw. Mitglied hat eine Rolle von … bis … Daraus entsteht die Historie.

    Rollen einer Einheit gehen an Benutzerkonten (``user``, optional mit Akte
    ``person``), Rollen von Untereinheiten an Mitgliedschaften (``membership``).
    """

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="role_assignments"
    )
    role = models.ForeignKey(Role, on_delete=protect_unit_holders, related_name="assignments")
    # Inhaber einer Rolle einer Untereinheit: die Mitgliedschaft
    membership = models.ForeignKey(
        "members.Membership",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="department_roles",
    )
    # Leer bei reiner Historie (z. B. aus Altdaten): dann nur mit Mitgliedsakte
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="role_assignments",
        null=True,
        blank=True,
    )
    # Optional: Mitgliedsdatensatz der Person (Vorstandsrollen-Historie in der Akte)
    person = models.ForeignKey(
        "members.Person",
        verbose_name="Mitglied",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="board_roles",
    )
    valid_from = models.DateField("von", default=timezone.localdate)
    valid_until = models.DateField("bis", null=True, blank=True)
    # Früherer Amtsinhaber ohne Konto und ohne Mitgliedschaft (Ralf 2026-10-31): nur Name,
    # Zeitraum jahresgenau (1. 1. von bis 1. 1. bis), immer abgeschlossen. Siehe access/offices.py.
    name = models.CharField("Name (früherer Inhaber)", max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    all_objects = RoleAssignmentQuerySet.as_manager()
    objects = OrgAssignmentManager()

    class Meta:
        verbose_name = "Rollenzuordnung"
        verbose_name_plural = "Rollenzuordnungen"
        ordering = ["-valid_from"]
        default_manager_name = "all_objects"

    def __str__(self) -> str:
        if self.membership_id:
            return f"{self.role}"
        return f"{self.user or self.person or self.name} – {self.role.name}"

    def save(self, *args, **kwargs):
        self.organization_id = self.role.organization_id
        super().save(*args, **kwargs)

    def clean(self) -> None:
        if self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": "Das Ende liegt vor dem Beginn."})

    @property
    def is_former_entry(self) -> bool:
        """Freier Eintrag eines früheren Inhabers (kein Konto, keine Mitgliedschaft)."""
        return bool(self.name) and self.user_id is None and self.membership_id is None

    @property
    def is_active(self) -> bool:
        today = timezone.localdate()
        return self.valid_from <= today and (self.valid_until is None or self.valid_until >= today)
