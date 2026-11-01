"""Fester Berechtigungskatalog, nach Modulen gegliedert.

Organisationen stellen ihre Rollen aus diesen Bausteinen zusammen. Neue Module
bringen hier ihre eigenen Berechtigungen mit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    code: str
    label: str


@dataclass(frozen=True)
class Module:
    id: str
    label: str
    permissions: tuple[Permission, ...]
    # Für welche Organisationsarten die Berechtigungen gelten
    org_types: tuple[str, ...] = ("federation", "club")
    # Lässt sich das Modul je Organisation ein-/ausschalten?
    switchable: bool = False


MEMBERS_VIEW = "members.view"
MEMBERS_EDIT = "members.edit"
PHOTOS_MANAGE = "photos.manage"
CARDS_MANAGE = "cards.manage"
ORG_EDIT = "org.edit"
AUDIT_VIEW = "audit.view"
ROLES_MANAGE = "roles.manage"
THEME_EDIT = "theme.edit"
EXPORT_RUN = "export.run"
PLATFORM_MANAGE = "platform.manage"
FINANCE_VIEW = "finance.view"
FINANCE_EDIT = "finance.edit"
DATA_EXPORT = "data.export"
CLUBS_MANAGE = "clubs.manage"
BILLING_VIEW = "billing.view"
BILLING_EDIT = "billing.edit"
EVENTS_MANAGE = "events.manage"
DOCS_VIEW = "docs.view"
DOCS_MANAGE = "docs.manage"
CIRCULARS_SEND = "circulars.send"
WEBSITE_MANAGE = "website.manage"
WEBSITE_CONTENT = "website.content"
PEERING_MANAGE = "peering.manage"
COMPETITIONS_MANAGE = "competitions.manage"
COMPETITIONS_RESULTS = "competitions.results"

# Rechte in einer Abteilung (Abteilungsrollen, ab Phase 2). Sie gelten nur für
# die Mitglieder dieser Abteilung.
DEPT_MEMBERS_VIEW = "dept.members.view"
DEPT_MEMBERS_EDIT = "dept.members.edit"
DEPT_ROLES_MANAGE = "dept.roles.manage"
DEPT_ACCESS_MANAGE = "dept.access.manage"
DEPT_EXPORT = "dept.export"
DEPT_INVOICES_VIEW = "dept.invoices.view"
DEPT_CARDS_MANAGE = "dept.cards.manage"
DEPT_EVENTS_MANAGE = "dept.events.manage"
DEPT_DOCS_MANAGE = "dept.docs.manage"
DEPT_CIRCULARS_SEND = "dept.circulars.send"

MODULES: tuple[Module, ...] = (
    Module(
        "members",
        "Mitglieder",
        (
            Permission(MEMBERS_VIEW, "Mitglieder lesen"),
            Permission(MEMBERS_EDIT, "Mitglieder bearbeiten"),
            Permission(PHOTOS_MANAGE, "Fotos verwalten"),
            Permission(CARDS_MANAGE, "Mitgliedsausweise (QR-Code) erstellen und sperren"),
        ),
        switchable=True,
    ),
    Module(
        "organization",
        "Einstellungen und Organisation",
        (
            Permission(ORG_EDIT, "Organisationsdaten und {pl} bearbeiten"),
            Permission(AUDIT_VIEW, "Änderungsprotokoll einsehen"),
            Permission(
                PEERING_MANAGE,
                "Verbund mit anderen HUBIplan-Instanzen verwalten (Namen und Rechnungen nur "
                "zusammen mit den Rechten dafür)",
            ),
        ),
        org_types=("platform", "federation", "club"),
    ),
    Module(
        "roles",
        "Rollen und Benutzer",
        (Permission(ROLES_MANAGE, "Rollen und Benutzer verwalten"),),
        org_types=("platform", "federation", "club", "unit"),
    ),
    Module(
        "theme",
        "Erscheinungsbild",
        (Permission(THEME_EDIT, "Erscheinungsbild ändern"),),
        org_types=("platform", "federation", "club"),
    ),
    Module(
        "finance",
        "Kasse",
        (
            Permission(FINANCE_VIEW, "Kasse, Belege und Berichte lesen (z. B. Kassenprüfer)"),
            Permission(FINANCE_EDIT, "Kasse führen: Konten, Kategorien, Buchungen, Belege"),
        ),
        org_types=("federation", "club", "unit"),
        switchable=True,
    ),
    Module(
        "billing",
        "Beiträge und Rechnungen",
        (
            Permission(BILLING_VIEW, "Beiträge, Rechnungen und Zahlungsstand lesen"),
            Permission(
                BILLING_EDIT,
                "Beitragsregeln, Beitragsläufe, Rechnungen, Mahnungen und Zahlungen bearbeiten",
            ),
        ),
        org_types=("federation", "club", "unit"),
        switchable=True,
    ),
    Module(
        "events",
        "Termine",
        (
            Permission(
                EVENTS_MANAGE,
                "Termine verwalten: Kalender der Organisation, Kategorien, öffentlicher Link",
            ),
        ),
        switchable=True,
    ),
    Module(
        "documents",
        "Dokumente",
        (
            Permission(DOCS_VIEW, "Dokumentenablage lesen"),
            Permission(DOCS_MANAGE, "Dokumentenablage verwalten: Ordner, Dokumente, Freigaben"),
        ),
    ),
    Module(
        "circulars",
        "Rundschreiben",
        (
            Permission(
                CIRCULARS_SEND,
                "Rundschreiben verfassen und versenden (E-Mails und Serienbriefe)",
            ),
        ),
    ),
    Module(
        "website",
        "Webseite",
        (
            Permission(
                WEBSITE_MANAGE,
                "Webseite verwalten: einrichten, Zustand, Domains, Vorschau, Bausteine",
            ),
            Permission(WEBSITE_CONTENT, "Inhalte der Webseite bearbeiten (Texte und Bilder)"),
        ),
        org_types=("federation", "club", "unit"),
        switchable=True,
    ),
    Module(
        "competitions",
        "Wettbewerbe",
        (
            Permission(
                COMPETITIONS_MANAGE,
                "Wettbewerbe verwalten: anlegen, Wertungen, abschließen, Auswertung",
            ),
            Permission(
                COMPETITIONS_RESULTS,
                "Ergebnisse erfassen: Starter, Werte und Stechen eintragen (z. B. Schießmeister)",
            ),
        ),
        switchable=True,
    ),
    Module(
        "export",
        "Export",
        (
            Permission(EXPORT_RUN, "Mitgliederlisten exportieren"),
            Permission(DATA_EXPORT, "Vollständigen Datenexport erstellen (alle Daten als Datei)"),
        ),
    ),
    Module(
        "clubs",
        "{Pl}",
        (Permission(CLUBS_MANAGE, "{Pl} anlegen und aus einer Exportdatei importieren"),),
        org_types=("federation",),
    ),
    Module(
        "platform",
        "Plattform",
        (Permission(PLATFORM_MANAGE, "Einheiten und Plattform verwalten"),),
        org_types=("platform",),
    ),
)

DEPARTMENT_MODULES: tuple[Module, ...] = (
    Module(
        "dept_members",
        "Mitglieder {gen}",
        (
            Permission(DEPT_MEMBERS_VIEW, "Mitglieder {gen} lesen"),
            Permission(DEPT_MEMBERS_EDIT, "Mitgliederdaten {gen} ändern"),
            Permission(DEPT_ACCESS_MANAGE, "Zugänge und Anmeldelinks für Mitglieder"),
            Permission(DEPT_CARDS_MANAGE, "Mitgliedsausweise (QR-Code) {gen}"),
            Permission(DEPT_EXPORT, "Daten {gen} exportieren"),
        ),
        org_types=("department",),
    ),
    Module(
        "dept_invoices",
        "Rechnungen {gen}",
        (Permission(DEPT_INVOICES_VIEW, "Sammelrechnungen {gen} sehen (Kassierer)"),),
        org_types=("department",),
    ),
    Module(
        "dept_events",
        "Termine {gen}",
        (Permission(DEPT_EVENTS_MANAGE, "Termine {gen} verwalten"),),
        org_types=("department",),
    ),
    Module(
        "dept_documents",
        "Dokumente {gen}",
        (Permission(DEPT_DOCS_MANAGE, "Dokumentenablage {gen} verwalten"),),
        org_types=("department",),
    ),
    Module(
        "dept_circulars",
        "Rundschreiben {gen}",
        (Permission(DEPT_CIRCULARS_SEND, "Rundschreiben an die Mitglieder {gen} versenden"),),
        org_types=("department",),
    ),
    Module(
        "dept_roles",
        "Rollen {gen}",
        (Permission(DEPT_ROLES_MANAGE, "Rollen {gen} und ihre Rechte verwalten"),),
        org_types=("department",),
    ),
)

DEPARTMENT_CODES: frozenset[str] = frozenset(
    p.code for m in DEPARTMENT_MODULES for p in m.permissions
)

ALL_CODES: frozenset[str] = frozenset(p.code for m in MODULES for p in m.permissions)
SWITCHABLE_MODULES: tuple[str, ...] = tuple(m.id for m in MODULES if m.switchable)
# Module, die eine neue Einheit nicht automatisch bekommt (die Plattform schaltet
# sie gezielt frei, z. B. die Webseite nur für Einheiten, die eine haben sollen)
OPT_IN_MODULES: frozenset[str] = frozenset({"website", "competitions"})
DEFAULT_MODULES: tuple[str, ...] = tuple(m for m in SWITCHABLE_MODULES if m not in OPT_IN_MODULES)


def codes_for(org_type: str) -> list[str]:
    return [p.code for m in MODULES if org_type in m.org_types for p in m.permissions]


def catalog_for(org_type: str | None = None, org=None) -> list[dict]:
    """Katalog mit Beschriftungen in der Abteilungsbezeichnung von ``org``.

    Die Beschriftungen enthalten Platzhalter wie ``{gen}`` (siehe
    ``organizations.terms``); ohne ``org`` gilt „Abteilung“.
    """
    from organizations.terms import fill

    modules = DEPARTMENT_MODULES if org_type == "department" else MODULES
    terms = org
    if org is None and org_type == "federation":
        from organizations.terms import default_terms_for

        terms = default_terms_for(org_type)
    return [
        {
            "id": m.id,
            "label": fill(m.label, terms),
            "permissions": [{"code": p.code, "label": fill(p.label, terms)} for p in m.permissions],
        }
        for m in modules
        if org_type is None or org_type in m.org_types
    ]
