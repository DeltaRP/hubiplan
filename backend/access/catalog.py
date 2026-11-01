"""Fester Berechtigungskatalog, nach Modulen gegliedert.

Organisationen stellen ihre Rollen aus diesen Bausteinen zusammen. Neue Module
bringen hier ihre eigenen Berechtigungen mit.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.utils.translation import gettext, gettext_noop


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
# HUBIplan so ansehen, wie eine Rolle der Einheit es sieht (nur lesen, nie mehr als die
# eigenen Rechte; siehe access/preview.py)
ROLES_PREVIEW = "roles.preview"
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
ENTRIES_SUBMIT = "entries.submit"
ENTRIES_MANAGE = "entries.manage"

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
DEPT_ENTRIES_SUBMIT = "dept.entries.submit"

MODULES: tuple[Module, ...] = (
    Module(
        "members",
        gettext_noop("Mitglieder"),
        (
            Permission(MEMBERS_VIEW, gettext_noop("Mitglieder lesen")),
            Permission(MEMBERS_EDIT, gettext_noop("Mitglieder bearbeiten")),
            Permission(PHOTOS_MANAGE, gettext_noop("Fotos verwalten")),
            Permission(
                CARDS_MANAGE, gettext_noop("Mitgliedsausweise (QR-Code) erstellen und sperren")
            ),
        ),
        switchable=True,
    ),
    Module(
        "organization",
        gettext_noop("Einstellungen und Organisation"),
        (
            Permission(ORG_EDIT, gettext_noop("Organisationsdaten und {pl} bearbeiten")),
            Permission(AUDIT_VIEW, gettext_noop("Änderungsprotokoll einsehen")),
            Permission(
                PEERING_MANAGE,
                gettext_noop(
                    "Verbund mit anderen HUBIplan-Instanzen verwalten (Namen und Rechnungen nur "
                    "zusammen mit den Rechten dafür)"
                ),
            ),
        ),
        org_types=("platform", "federation", "club"),
    ),
    Module(
        "roles",
        gettext_noop("Rollen und Benutzer"),
        (
            Permission(ROLES_MANAGE, gettext_noop("Rollen und Benutzer verwalten")),
            Permission(
                ROLES_PREVIEW,
                gettext_noop(
                    "Ansicht als Rolle: HUBIplan so ansehen, wie eine Rolle es sieht (nur lesen, "
                    "nie mehr als die eigenen Rechte)"
                ),
            ),
        ),
        org_types=("platform", "federation", "club", "unit"),
    ),
    Module(
        "theme",
        gettext_noop("Erscheinungsbild"),
        (Permission(THEME_EDIT, gettext_noop("Erscheinungsbild ändern")),),
        org_types=("platform", "federation", "club"),
    ),
    Module(
        "finance",
        gettext_noop("Kasse"),
        (
            Permission(
                FINANCE_VIEW, gettext_noop("Kasse, Belege und Berichte lesen (z. B. Kassenprüfer)")
            ),
            Permission(
                FINANCE_EDIT, gettext_noop("Kasse führen: Konten, Kategorien, Buchungen, Belege")
            ),
        ),
        org_types=("federation", "club", "unit"),
        switchable=True,
    ),
    Module(
        "billing",
        gettext_noop("Beiträge und Rechnungen"),
        (
            Permission(BILLING_VIEW, gettext_noop("Beiträge, Rechnungen und Zahlungsstand lesen")),
            Permission(
                BILLING_EDIT,
                gettext_noop(
                    "Beitragsregeln, Beitragsläufe, Rechnungen, Mahnungen und Zahlungen bearbeiten"
                ),
            ),
        ),
        org_types=("federation", "club", "unit"),
        switchable=True,
    ),
    Module(
        "events",
        gettext_noop("Termine"),
        (
            Permission(
                EVENTS_MANAGE,
                gettext_noop(
                    "Termine verwalten: Kalender der Organisation, Kategorien, öffentlicher Link"
                ),
            ),
        ),
        switchable=True,
    ),
    Module(
        "documents",
        gettext_noop("Dokumente"),
        (
            Permission(DOCS_VIEW, gettext_noop("Dokumentenablage lesen")),
            Permission(
                DOCS_MANAGE,
                gettext_noop("Dokumentenablage verwalten: Ordner, Dokumente, Freigaben"),
            ),
        ),
    ),
    Module(
        "circulars",
        gettext_noop("Rundschreiben"),
        (
            Permission(
                CIRCULARS_SEND,
                gettext_noop("Rundschreiben verfassen und versenden (E-Mails und Serienbriefe)"),
            ),
        ),
    ),
    Module(
        "website",
        gettext_noop("Webseite"),
        (
            Permission(
                WEBSITE_MANAGE,
                gettext_noop(
                    "Webseite verwalten: einrichten, Zustand, Domains, Vorschau, Bausteine"
                ),
            ),
            Permission(
                WEBSITE_CONTENT, gettext_noop("Inhalte der Webseite bearbeiten (Texte und Bilder)")
            ),
        ),
        org_types=("federation", "club", "unit"),
        switchable=True,
    ),
    Module(
        "competitions",
        gettext_noop("Wettbewerbe"),
        (
            Permission(
                COMPETITIONS_MANAGE,
                gettext_noop("Wettbewerbe verwalten: anlegen, Wertungen, abschließen, Auswertung"),
            ),
            Permission(
                COMPETITIONS_RESULTS,
                gettext_noop(
                    "Ergebnisse erfassen: Starter, Werte und Stechen eintragen "
                    "(z. B. Schießmeister)"
                ),
            ),
        ),
        switchable=True,
    ),
    Module(
        "entries",
        gettext_noop("Meldungen"),
        (
            Permission(
                ENTRIES_SUBMIT,
                gettext_noop(
                    "Meldungen an Veranstalter zusammenstellen und abgeben (z. B. Mannschaften)"
                ),
            ),
            Permission(
                ENTRIES_MANAGE,
                gettext_noop(
                    "Ausschreibungen an die eigenen Untereinheiten verwalten, Meldungen bestätigen"
                ),
            ),
        ),
        switchable=True,
    ),
    Module(
        "export",
        gettext_noop("Export"),
        (
            Permission(EXPORT_RUN, gettext_noop("Mitgliederlisten exportieren")),
            Permission(
                DATA_EXPORT,
                gettext_noop("Vollständigen Datenexport erstellen (alle Daten als Datei)"),
            ),
        ),
    ),
    Module(
        "clubs",
        gettext_noop("{Pl}"),
        (
            Permission(
                CLUBS_MANAGE, gettext_noop("{Pl} anlegen und aus einer Exportdatei importieren")
            ),
        ),
        org_types=("federation",),
    ),
    Module(
        "platform",
        gettext_noop("Plattform"),
        (Permission(PLATFORM_MANAGE, gettext_noop("Einheiten und Plattform verwalten")),),
        org_types=("platform",),
    ),
)

DEPARTMENT_MODULES: tuple[Module, ...] = (
    Module(
        "dept_members",
        gettext_noop("Mitglieder {gen}"),
        (
            Permission(DEPT_MEMBERS_VIEW, gettext_noop("Mitglieder {gen} lesen")),
            Permission(DEPT_MEMBERS_EDIT, gettext_noop("Mitgliederdaten {gen} ändern")),
            Permission(DEPT_ACCESS_MANAGE, gettext_noop("Zugänge und Anmeldelinks für Mitglieder")),
            Permission(DEPT_CARDS_MANAGE, gettext_noop("Mitgliedsausweise (QR-Code) {gen}")),
            Permission(DEPT_EXPORT, gettext_noop("Daten {gen} exportieren")),
        ),
        org_types=("department",),
    ),
    Module(
        "dept_invoices",
        gettext_noop("Rechnungen {gen}"),
        (Permission(DEPT_INVOICES_VIEW, gettext_noop("Sammelrechnungen {gen} sehen (Kassierer)")),),
        org_types=("department",),
    ),
    Module(
        "dept_events",
        gettext_noop("Termine {gen}"),
        (Permission(DEPT_EVENTS_MANAGE, gettext_noop("Termine {gen} verwalten")),),
        org_types=("department",),
    ),
    Module(
        "dept_documents",
        gettext_noop("Dokumente {gen}"),
        (Permission(DEPT_DOCS_MANAGE, gettext_noop("Dokumentenablage {gen} verwalten")),),
        org_types=("department",),
    ),
    Module(
        "dept_circulars",
        gettext_noop("Rundschreiben {gen}"),
        (
            Permission(
                DEPT_CIRCULARS_SEND, gettext_noop("Rundschreiben an die Mitglieder {gen} versenden")
            ),
        ),
        org_types=("department",),
    ),
    Module(
        "dept_entries",
        gettext_noop("Meldungen {gen}"),
        (
            Permission(
                DEPT_ENTRIES_SUBMIT,
                gettext_noop("Meldungen {gen} zu Ausschreibungen von oben abgeben"),
            ),
        ),
        org_types=("department",),
    ),
    Module(
        "dept_roles",
        gettext_noop("Rollen {gen}"),
        (Permission(DEPT_ROLES_MANAGE, gettext_noop("Rollen {gen} und ihre Rechte verwalten")),),
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
OPT_IN_MODULES: frozenset[str] = frozenset({"website", "competitions", "entries"})
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
            "label": fill(gettext(m.label), terms),
            "permissions": [
                {"code": p.code, "label": fill(gettext(p.label), terms)} for p in m.permissions
            ],
        }
        for m in modules
        if org_type is None or org_type in m.org_types
    ]
