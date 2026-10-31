"""Zusätzliche Passwortregeln (Audit 29.10. G08).

- Naheliegende Wörter: HUBIplan, Schützen, Verein und Name, Kurzname und Ort der
  Organisationen, in denen der Benutzer eine Rolle oder einen Zugang hat. Ein
  Passwort, das nach Abzug dieser Wörter, Ziffern und Satzzeichen kaum noch etwas
  enthält, wird abgelehnt.
- Geleakte Passwörter: mitgelieferte Liste (accounts/data), Prüfung nur auf dem
  Server, ohne externen Dienst.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.contrib.auth.password_validation import CommonPasswordValidator
from django.core.exceptions import ValidationError

FIXED_WORDS = (
    "hubiplan",
    "schuetzen",
    "schützen",
    "schuetze",
    "schütze",
    "verein",
    "bruderschaft",
    "passwort",
    "kennwort",
)
MIN_REST = 6
LEAKED = Path(__file__).resolve().parent / "data" / "geleakte-passwoerter.txt.gz"


def _plain(text: str) -> str:
    text = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    return text


def _org_words(user) -> set[str]:
    if user is None or not getattr(user, "pk", None):
        return set()
    from access.models import RoleAssignment
    from core.tenancy import rls_bypass
    from portal.models import PortalAccess

    with rls_bypass():
        orgs = [a.organization for a in RoleAssignment.objects.filter(user=user)]
        orgs += [
            a.membership.organization
            for a in PortalAccess.objects.filter(user=user).select_related(
                "membership__organization"
            )
        ]
    words: set[str] = set()
    for org in orgs:
        for value in (org.name, org.short_name, org.city):
            # Einzelne Bestandteile, z. B. „Hubertus“ und „Grimlinghausen“
            words.update(w for w in re.split(r"[\W_]+", _plain(value or "")) if len(w) >= 4)
    return words


class ContextWordValidator:
    """Passwort darf nicht nur aus naheliegenden Wörtern und Ziffern bestehen."""

    def validate(self, password: str, user=None) -> None:
        plain = _plain(password)
        rest = plain
        words = {_plain(w) for w in FIXED_WORDS} | _org_words(user)
        for word in sorted(words, key=len, reverse=True):
            rest = rest.replace(word, "")
        # Nur wenn ein naheliegendes Wort drinsteckt; zufällige Passwörter mit wenigen
        # Buchstaben bleiben erlaubt
        if rest == plain:
            return
        rest = re.sub(r"[\W\d_]+", "", rest)
        if len(rest) < MIN_REST:
            raise ValidationError(
                "Das Passwort ist zu leicht zu erraten: Es besteht fast nur aus "
                "naheliegenden Wörtern (z. B. Vereinsname, Ort, „Schützen“) und Ziffern.",
                code="password_context",
            )

    def get_help_text(self) -> str:
        return "Das Passwort darf nicht nur aus Vereinsname, Ort oder ähnlichen Wörtern bestehen."


class LeakedPasswordValidator(CommonPasswordValidator):
    """Liste häufiger Passwörter aus Datenlecks (NCSC, mitgeliefert)."""

    def __init__(self, password_list_path=LEAKED):
        super().__init__(password_list_path)

    def validate(self, password: str, user=None) -> None:
        if password.lower().strip() in self.passwords:
            raise ValidationError(
                "Dieses Passwort taucht in bekannten Datenlecks auf. Bitte ein anderes wählen.",
                code="password_leaked",
            )
