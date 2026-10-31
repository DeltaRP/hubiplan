"""Eigene Bezeichnung für Abteilungen in Texten (Grammatik).

Vereine können „Abteilung“ umbenennen, z. B. in „Zug“ (männlich) oder
„Bataillon“ (sächlich). Damit Texte grammatisch stimmen, liefert
``department_terms`` alle nötigen Formen mit Artikel. Texte enthalten
Platzhalter wie ``{gen}`` („des Zugs“ / „der Abteilung“) und werden mit
``fill`` gefüllt. Großgeschriebene Schlüssel (``{Gen}``) liefern die Form mit
großem Anfangsbuchstaben für den Satzanfang.

Dieselbe Logik steckt im Frontend in ``frontend/src/org/terms.ts``.
"""

from __future__ import annotations

import re

FEMININE = "f"
MASCULINE = "m"
NEUTER = "n"
GENDERS = (FEMININE, MASCULINE, NEUTER)

DEFAULT_LABEL = "Abteilung"
DEFAULT_PLURAL = "Abteilungen"

# Artikel und Endungen je Genus: (feminin, maskulin, neutral)
_FORMS = {
    "nom": ("die", "der", "das"),
    "akk": ("die", "den", "das"),
    "dat": ("der", "dem", "dem"),
    "gen": ("der", "des", "des"),
    "ein": ("eine", "ein", "ein"),
    "einen": ("eine", "einen", "ein"),
    "einem": ("einer", "einem", "einem"),
    "eines": ("einer", "eines", "eines"),
    "kein": ("keine", "kein", "kein"),
    "diese": ("diese", "dieser", "dieses"),
    "diesem": ("dieser", "diesem", "diesem"),
    "dieses": ("dieser", "dieses", "dieses"),
    "diesen": ("diese", "diesen", "dieses"),
    "deinem": ("deiner", "deinem", "deinem"),
    "deines": ("deiner", "deines", "deines"),
    "ihrem": ("ihrer", "ihrem", "ihrem"),
    "ihres": ("ihrer", "ihres", "ihres"),
    "im": ("in der", "im", "im"),
    "zum": ("zur", "zum", "zum"),
    "vom": ("von der", "vom", "vom"),
    "beim": ("bei der", "beim", "beim"),
    "deinen": ("deine", "deinen", "dein"),
    "ihren": ("ihre", "ihren", "ihr"),
    "unser": ("unsere", "unser", "unser"),
    "ein_anderer": ("eine andere", "ein anderer", "ein anderes"),
    "einen_anderen": ("eine andere", "einen anderen", "ein anderes"),
    "einem_anderen": ("einer anderen", "einem anderen", "einem anderen"),
    "eines_anderen": ("einer anderen", "eines anderen", "eines anderen"),
    "der_andere": ("die andere", "der andere", "das andere"),
    "den_anderen": ("die andere", "den anderen", "das andere"),
    "beim_anderen": ("bei der anderen", "beim anderen", "beim anderen"),
}
# Fälle, in denen das Nomen im Genitiv steht
_GENITIVE_KEYS = {"gen", "eines", "dieses", "deines", "ihres", "eines_anderen"}
# Adjektivendung ohne Artikel (Nominativ): unbekannte / unbekannter / unbekanntes
_ADJ = ("e", "er", "es")


def genitive(label: str, gender: str) -> str:
    """Genitiv Einzahl: Abteilung → Abteilung, Zug → Zugs, Kreis → Kreises."""
    if gender == FEMININE or not label:
        return label
    if re.search(r"(s|ß|x|z)$", label):
        return label + "es"
    return label + "s"


def dative_plural(plural: str) -> str:
    """Dativ Mehrzahl: Züge → Zügen, Abteilungen → Abteilungen, Clubs → Clubs."""
    if not plural or re.search(r"(n|s)$", plural):
        return plural
    return plural + "n"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def build_terms(
    label: str, plural: str, gender: str = FEMININE, genitive_form: str = ""
) -> dict[str, str]:
    label = label or DEFAULT_LABEL
    plural = plural or DEFAULT_PLURAL
    if gender not in GENDERS:
        gender = FEMININE
    idx = GENDERS.index(gender)
    gen = genitive_form or genitive(label, gender)
    terms = {
        "sg": label,
        "pl": plural,
        "sg_gen": gen,
        "pl_dat": dative_plural(plural),
        "gender": gender,
    }
    for key, forms in _FORMS.items():
        noun = gen if key in _GENITIVE_KEYS else label
        terms[key] = f"{forms[idx]} {noun}"
    terms["adj"] = _ADJ[idx]  # z. B. „Unbekannt{adj} {sg}“
    for key in list(terms):
        if key not in ("gender", "adj"):
            terms[_cap(key)] = _cap(terms[key])
    return terms


DEFAULT_TERMS = build_terms(DEFAULT_LABEL, DEFAULT_PLURAL, FEMININE)


# Dachverband: Vereine sehen statt „Dachverband“ dessen Namen (Kurzname, sonst
# voller Name). Platzhalter mit Vorsilbe ``dv_``: ``{dv_im}`` „im BSV“,
# ``{dv_akk}`` „den BSV“, ``{dv_gen}`` „des BSV“, ``{dv_sg}`` „BSV“,
# ``{dv_Nom}`` „Der BSV“. ``dv_has`` ist „1“, wenn der Verein zu einem
# Dachverband gehört (sonst leer). Auf Dachverbands- und Plattformebene steht
# weiter „Dachverband“.
FED_LABEL = "Dachverband"
FED_PREFIX = "dv_"


def build_federation_terms(
    name: str = "", gender: str = MASCULINE, genitive_form: str = ""
) -> dict[str, str]:
    """Formen eines Dachverbandsnamens; ohne Namen die Formen von „Dachverband“.

    Namen (oft Abkürzungen wie „BSV“) bleiben im Genitiv unverändert („des BSV“),
    außer der Dachverband trägt eine eigene Form ein.
    """
    if name:
        base = build_terms(name, name, gender or MASCULINE, genitive_form or name)
    else:
        base = build_terms(FED_LABEL, "Dachverbände", MASCULINE, "Dachverbands")
    terms = {FED_PREFIX + k: v for k, v in base.items() if not k.lower().startswith("pl")}
    terms[FED_PREFIX + "has"] = "1" if name else ""
    return terms


DEFAULT_FED_TERMS = build_federation_terms()


def federation_of(org):
    """Dachverband eines Vereins (oder ``None``)."""
    if org is None or getattr(org, "type", None) != "club":
        return None
    parent = getattr(org, "parent", None)
    if parent is not None and parent.type == "federation":
        return parent
    return None


def federation_terms(org) -> dict[str, str]:
    """``dv_``-Formen für Texte, die ``org`` sieht (Verein: Name seines Dachverbands)."""
    if org is None or getattr(org, "type", None) != "club":
        return DEFAULT_FED_TERMS
    fed = federation_of(org)
    if fed is None:
        terms = dict(DEFAULT_FED_TERMS)
        terms[FED_PREFIX + "has"] = ""
        return terms
    return build_federation_terms(
        fed.display_name, fed.name_gender or MASCULINE, fed.name_genitive or ""
    )


# Bezeichnung der Einheit selbst (z. B. „Verein“, „Dachverband“, „Zug“):
# Platzhalter mit Vorsilbe ``e_``, z. B. {e_sg} „Verein“, {e_im} „im Verein“,
# {e_gen} „des Vereins“, {e_pl} „Vereine“, {e_eines_anderen} „eines anderen Vereins“.
OWN_PREFIX = "e_"
OWN_DEFAULT = ("Einheit", "Einheiten", FEMININE, "")


def build_own_terms(
    label: str = "", plural: str = "", gender: str = FEMININE, genitive_form: str = ""
) -> dict[str, str]:
    if not label:
        label, plural, gender, genitive_form = OWN_DEFAULT
    base = build_terms(label, plural or label, gender, genitive_form)
    return {OWN_PREFIX + k: v for k, v in base.items()}


DEFAULT_OWN_TERMS = build_own_terms()


def own_terms(org) -> dict[str, str]:
    """``e_``-Formen der eigenen Bezeichnung einer Einheit."""
    if org is None:
        return DEFAULT_OWN_TERMS
    return build_own_terms(
        getattr(org, "label", "") or "",
        getattr(org, "label_plural", "") or "",
        getattr(org, "label_gender", FEMININE) or FEMININE,
        getattr(org, "label_genitive", "") or "",
    )


def department_terms(org) -> dict[str, str]:
    """Formen für Texte einer Einheit.

    - ohne Vorsilbe: Bezeichnung ihrer Untereinheiten (z. B. „Zug“ im Verein,
      „Verein“ im Dachverband),
    - ``e_``: ihre eigene Bezeichnung,
    - ``dv_``: Name der übergeordneten Einheit (siehe oben).
    """
    if org is None:
        return {**DEFAULT_TERMS, **DEFAULT_FED_TERMS, **DEFAULT_OWN_TERMS}
    terms = build_terms(
        getattr(org, "department_label", "") or DEFAULT_LABEL,
        getattr(org, "department_label_plural", "") or DEFAULT_PLURAL,
        getattr(org, "department_label_gender", FEMININE) or FEMININE,
        getattr(org, "department_label_genitive", "") or "",
    )
    terms.update(federation_terms(org))
    terms.update(own_terms(org))
    return terms


def default_terms_for(org_type: str) -> dict[str, str]:
    """Formen ohne konkrete Einheit, nach den Vorgaben für neue Einheiten dieser Art."""
    from .models import DEFAULT_CHILD_LABELS, DEFAULT_LABELS

    child = DEFAULT_CHILD_LABELS.get(org_type)
    terms = build_terms(*child) if child else dict(DEFAULT_TERMS)
    terms.update(DEFAULT_FED_TERMS)
    own = DEFAULT_LABELS.get(org_type)
    terms.update(build_own_terms(*own) if own else DEFAULT_OWN_TERMS)
    return terms


class _Keep(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def fill(text: str, terms_or_org=None) -> str:
    """Platzhalter in ``text`` füllen; unbekannte Platzhalter bleiben stehen."""
    terms = terms_or_org if isinstance(terms_or_org, dict) else department_terms(terms_or_org)
    if FED_PREFIX + "sg" not in terms:
        terms = {**DEFAULT_FED_TERMS, **terms}
    if OWN_PREFIX + "sg" not in terms:
        terms = {**DEFAULT_OWN_TERMS, **terms}
    return text.format_map(_Keep(terms))


# Feste Wörter aus Modell- und Feldnamen (z. B. im Änderungsprotokoll)
_WORDS = {
    "Abteilung": "{Sg}",
    "Abteilungen": "{Pl}",
    "Abteilung (optional)": "{Sg} (optional)",
    "Abteilungsrolle": "Rolle {im}",
    "Abteilungsrollen": "Rollen in {pl_dat}",
    "Abteilungsrolle (Inhaber)": "Rolle {im} (Inhaber)",
    "Abteilungszugehörigkeit": "Zugehörigkeit {zum}",
    "Mitglied darf mehreren Abteilungen angehören": "Mitglied darf mehreren {pl_dat} angehören",
    "Zugang für Abteilungen freigeschaltet": "Zugang für {pl} freigeschaltet",
    "zahlt Beitrag selbst (keine Sammelrechnung über die Abteilung)": (
        "zahlt Beitrag selbst (keine Sammelrechnung über {akk})"
    ),
    # Dachverband: im Verein sein Name
    "Dachverband": "{dv_Sg}",
    "an Dachverband melden": "an {dv_akk} melden",
    "Eintritt in den Dachverband (manuell)": "Eintritt in {dv_akk} (manuell)",
    "Zugriff durch Dachverband": "Zugriff durch {dv_akk}",
    "geändert durch Dachverband": "geändert durch {dv_akk}",
    # Eigene Bezeichnung der Einheit bzw. ihrer Untereinheiten
    "Mitgliedsnummer im Verein": "Mitgliedsnummer {e_im}",
    "Änderungen an Kontaktdaten erst nach Bestätigung durch den Verein": (
        "Änderungen an Kontaktdaten erst nach Bestätigung durch {e_akk}"
    ),
    "Grundbetrag je Verein": "Grundbetrag je {sg}",
    "Eintritt im neuen Verein": "Eintritt {e_im} (neu)",
    "Austritt im alten Verein": "Austritt {e_beim_anderen}",
    "Wechsel in anderen Verein": "Wechsel in {e_einen_anderen}",
}


def rename_word(text: str, org) -> str:
    """Bekannte feste Bezeichnungen mit „Abteilung“ in die eigene Bezeichnung umsetzen."""
    template = _WORDS.get(text)
    return fill(template, org) if template else text
