"""Einheiten unterscheiden sich nur durch Schalter, nicht durch eine Art.

Technisch merkt sich jede Einheit noch eine Art (``Organization.type``). Sie wird
aus der Lage im Baum und dem Schalter „führt eigene Mitglieder“ abgeleitet und
nicht mehr von Hand gewählt:

- direkt unter der Plattform, mit eigenen Mitgliedern  → ``club``
- direkt unter der Plattform, ohne eigene Mitglieder   → ``federation``
- unter einer Einheit, die Einheiten mit eigenen
  Mitgliedern zusammenfasst                             → ``club``
- eine oberste Einheit, die schon Einheiten mit eigenen
  Mitgliedern unter sich hat, kann zusätzlich selbst
  Mitglieder führen (``direct_members``)

Untereinheiten ohne eigene Mitglieder (z. B. Züge) bleiben ``unit``.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils.translation import gettext

from .models import DEFAULT_LABELS, Organization

T = Organization.Type

# Bezeichnung der Untereinheiten, solange die Einheit keine eigene gewählt hat
CHILD_LABELS = {
    T.FEDERATION: ("Verein", "Vereine", "m", "Vereins"),
    T.CLUB: ("Abteilung", "Abteilungen", "f", ""),
}


def type_for_new(parent: Organization | None, keeps_members: bool) -> str:
    """Art einer neuen Einheit aus übergeordneter Einheit und Schalter."""
    if parent is None or parent.type == T.PLATFORM:
        return T.CLUB if keeps_members else T.FEDERATION
    if parent.type == T.FEDERATION:
        if not keeps_members:
            raise ValidationError(
                {
                    "keeps_members": gettext(
                        "Einheiten unter dieser Einheit führen immer eigene Mitglieder. Gruppen "
                        "ohne eigene Mitglieder gibt es (noch) nur unter Einheiten mit eigenen "
                        "Mitgliedern (dort in den Einstellungen)."
                    )
                }
            )
        return T.CLUB
    raise ValidationError(
        {
            "federation": gettext(
                "Unter dieser Einheit lassen sich hier keine Einheiten anlegen. "
                "Untereinheiten ohne eigene Mitglieder legt die Einheit selbst in ihren "
                "Einstellungen an."
            )
        }
    )


def is_top(org: Organization) -> bool:
    return org.parent_id is not None and org.parent is not None and org.parent.type == T.PLATFORM


def has_member_units(org: Organization) -> bool:
    """Hat die Einheit Untereinheiten mit eigenen Mitgliedern?"""
    return org.children.filter(type=T.CLUB).exists()


def can_switch_members(org: Organization) -> bool:
    """Darf die Einheit den Schalter „führt eigene Mitglieder“ selbst umlegen?"""
    return org.type in (T.FEDERATION, T.CLUB) and is_top(org)


def apply_keeps_members(org: Organization, value: bool) -> bool:
    """Schalter „führt eigene Mitglieder“ setzen; ändert bei Bedarf die Art.

    Gibt zurück, ob sich die Art geändert hat. Die Einheit wird nicht gespeichert.
    Eine Art wechselt nur, solange die Einheit leer ist: keine Mitglieder, keine
    Untereinheiten. So geht nie etwas verloren.
    """
    from members.models import Membership

    if value == org.keeps_members:
        return False
    if not can_switch_members(org):
        raise ValidationError(
            {
                "keeps_members": gettext(
                    "Unter einer übergeordneten Einheit führen Einheiten immer eigene Mitglieder."
                )
            }
        )
    has_members = Membership.objects.filter(organization=org).exists()
    if not value and has_members:
        raise ValidationError(
            {
                "keeps_members": gettext(
                    "Es gibt schon eigene Mitglieder. Bitte diese zuerst entfernen."
                )
            }
        )
    if org.type == T.FEDERATION:
        if not value or has_member_units(org):
            # Oberste Einheit mit Einheiten darunter: Mitglieder zusätzlich führen
            org.direct_members = value
            return False
        if org.children.exists():
            raise ValidationError(
                {
                    "keeps_members": gettext(
                        "Bitte zuerst die Untereinheiten entfernen oder umhängen."
                    )
                }
            )
        _change_type(org, T.CLUB)
        org.direct_members = False
        return True
    # club → ohne eigene Mitglieder
    if org.children.exists():
        raise ValidationError(
            {
                "keeps_members": gettext(
                    "Es gibt noch Untereinheiten. Bitte diese zuerst entfernen oder umhängen."
                )
            }
        )
    _change_type(org, T.FEDERATION)
    return True


def _change_type(org: Organization, new_type: str) -> None:
    old = org.type
    # Vorgaben der alten Art durch die der neuen ersetzen, eigene Bezeichnungen bleiben
    if (org.label, org.label_plural) == DEFAULT_LABELS[old][:2]:
        org.label, org.label_plural, org.label_gender, org.label_genitive = DEFAULT_LABELS[new_type]
    if (org.department_label, org.department_label_plural) == CHILD_LABELS[old][:2]:
        (
            org.department_label,
            org.department_label_plural,
            org.department_label_gender,
            org.department_label_genitive,
        ) = CHILD_LABELS[new_type]
    org.type = new_type


def upgrade_full_roles(org: Organization, old_type: str) -> None:
    """Rollen mit allen Rechten der alten Art bekommen alle Rechte der neuen Art."""
    from access.catalog import codes_for
    from access.models import Role
    from core.tenancy import tenant_context

    old_codes = set(codes_for(old_type))
    new_codes = codes_for(org.type)
    with tenant_context(org.pk):
        for role in Role.objects.filter(organization=org):
            perms = set(role.permissions)
            if old_codes <= perms:
                role.permissions = sorted(new_codes)
            else:
                role.permissions = sorted(perms & set(new_codes))
            role.save(update_fields=["permissions"])
