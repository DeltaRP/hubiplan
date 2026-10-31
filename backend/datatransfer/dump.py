"""Export: eine Organisation (mit Untereinheiten) oder eine Abteilung als JSON.

Aufbau der Datei (Format ``hubiplan-export``, Version 1)::

    {
      "format": "hubiplan-export", "version": 1, "kind": "organization" | "department",
      "exported_at": "...", "source": {"type", "name"},
      "with_files": false, "person_data_mode": "shared" | "per_club",
      "persons": [...],                 # alle Personen, auf die die Datei verweist
      "organization": {...}             # bei kind = organization
      "department": {...}, "club": {...}, "member_types": [...], "memberships": [...]
                                        # bei kind = department
    }

Verweise innerhalb der Datei laufen über die ``id`` der Objekte (die Nummern der
Quelle). Beim Import werden neue Nummern vergeben. Mit Dateien entsteht eine
ZIP-Datei mit ``export.json`` und den Dateien unter ``files/``.

Der Export liest systemweit (RLS aufgehoben) und filtert selbst nach den
Organisationen der Datei. Die Berechtigung prüft vorher die API-Ansicht.
"""

from __future__ import annotations

import datetime
import io
import json
import zipfile
from contextlib import contextmanager
from decimal import Decimal

from django.db import connection, transaction
from django.utils import timezone
from django.utils.text import slugify

from access.models import Role, RoleAssignment
from core.tenancy import rls_bypass
from customfields.models import FieldDefinition, FieldValue
from members.models import (
    FederationMember,
    Membership,
    MemberType,
    Person,
)
from members.photo_models import MemberPhoto
from organizations.models import (
    Department,
    DepartmentRole,
    Imprint,
    Organization,
    PlatformSettings,
)
from organizations.tree import UnitTree

from .tables import dump_tables

FORMAT = "hubiplan-export"
VERSION = 1

# Impressum: gepflegte Felder (der öffentliche Schlüssel wird neu vergeben)
IMPRINT_FIELDS = [
    "mode",
    "external_url",
    "name",
    "legal_form",
    "street",
    "postal_code",
    "city",
    "representatives",
    "email",
    "phone",
    "registered",
    "register_court",
    "register_number",
    "vat_id",
    "responsible",
    "data_protection_officer",
    "extra_text",
    "privacy_mode",
    "privacy_text",
    "privacy_published_text",
    "privacy_url",
]


LETTERHEAD_FIELDS = [
    "mode",
    "form",
    "logo_position",
    "tagline",
    "font",
    "salutation",
    "closing",
    "show_bank",
    "show_email",
    "show_phone",
    "show_website",
    "show_board",
    "show_register",
    "show_social",
]


def letterhead_data(org: Organization) -> dict | None:
    """Briefbogen ohne Kontowahl (Konten bekommen beim Einlesen neue Nummern)."""
    from letterhead.models import Letterhead

    lh = Letterhead.objects.filter(organization=org).first()
    return {f: getattr(lh, f) for f in LETTERHEAD_FIELDS} if lh else None


def social_data(org: Organization) -> list[dict]:
    return [
        {"kind": s.kind, "url": s.url, "label": s.label, "position": s.position}
        for s in org.social_links.all()
    ]


def imprint_data(org: Organization) -> dict | None:
    imprint = Imprint.objects.filter(organization=org).first()
    return {f: getattr(imprint, f) for f in IMPRINT_FIELDS} if imprint else None


JSON_NAME = "export.json"

ORG_FIELDS = (
    "type",
    "name",
    "short_name",
    "name_gender",
    "name_genitive",
    "label",
    "label_plural",
    "label_gender",
    "label_genitive",
    "founding_year",
    "street",
    "postal_code",
    "city",
    "country",
    "contact_source",
    "contact_email",
    "contact_phone",
    "website",
    "primary_color",
    "accent_color",
    "primary_color_name",
    "accent_color_name",
    "extra_colors",
    "fiscal_start_month",
    "fiscal_start_day",
    "department_label",
    "department_label_plural",
    "department_label_gender",
    "department_label_genitive",
    "allow_multiple_departments",
    "photo_approval_required",
    "member_portal_enabled",
    "contact_changes_need_approval",
    "department_access_enabled",
    "federation_member_access",
    "federation_show_former_memberships",
    "jubilee_years",
    "unit_jubilee_years",
    "federation_duration_rule",
    "date_precision",
    "enabled_modules",
    "tax_areas_enabled",
    "is_active",
    # Dachverband mit eigenen Mitgliedern (Audit 31.10. D31-02)
    "direct_members",
    # Platzhalter einer Einheit auf einer anderen Instanz (Verbund)
    "is_remote",
    # Finanzeinstellungen und Festschreibung (Gesamtaudit 01.11., GA-F08)
    "finance_locked_until",
    "cash_counts_enabled",
    "reserves_enabled",
    "datev_enabled",
    "datev_consultant",
    "datev_client",
    "datev_account_length",
    "datev_chart",
)
DEPT_FIELDS = (
    "name",
    "short_name",
    "founding_year",
    # Homepage der Untereinheit und ob die Vereinswebseite sie verlinkt
    "website",
    "website_on_site",
    "sort_order",
    "date_precision",
    "is_active",
    "primary_color",
    "accent_color",
    "primary_color_name",
    "accent_color_name",
    "extra_colors",
    "fiscal_start_month",
    "fiscal_start_day",
    "department_label",
    "department_label_plural",
    "department_label_gender",
    "department_label_genitive",
    # Eigener Arbeitsbereich mit Kasse/Rechnungen (Audit 31.10. D31-01)
    "own_workspace",
    "self_managed",
    "fee_exempt",
    # Finanzeinstellungen und Festschreibung (Gesamtaudit 01.11., GA-F08)
    "finance_locked_until",
    "cash_counts_enabled",
    "reserves_enabled",
    "datev_enabled",
    "datev_consultant",
    "datev_client",
    "datev_account_length",
    "datev_chart",
)
MEMBERSHIP_PREFETCH = (
    "periods",
    "type_assignments",
    "department_memberships",
    "department_roles__role",
    "photos",
    "person__contacts",
)
CONTACT_FIELDS = ("email", "phone", "street", "postal_code", "city", "country")


def plain(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def values(obj, names) -> dict:
    return {name: plain(getattr(obj, name)) for name in names}


def period(obj, start="valid_from", end="valid_until") -> dict:
    return {start: plain(getattr(obj, start)), end: plain(getattr(obj, end))}


class Packer:
    """Sammelt Dateien für die ZIP-Datei (nur wenn ``with_files``)."""

    def __init__(self, with_files: bool):
        self.with_files = with_files
        self.files: list[tuple[str, object]] = []

    def add(self, fieldfile, folder: str) -> str | None:
        if not self.with_files or not fieldfile:
            return None
        base = fieldfile.name.rsplit("/", 1)[-1]
        path = f"files/{folder}/{len(self.files) + 1:05d}-{base}"
        self.files.append((path, fieldfile))
        return path


class Dumper:
    def __init__(self, *, with_files: bool, member_data_for: callable, finance_for: callable):
        self.packer = Packer(with_files)
        self.member_data_for = member_data_for
        self.finance_for = finance_for
        self.shared_contacts = (
            PlatformSettings.load().person_data_mode == PlatformSettings.PersonData.SHARED
        )
        self.person_ids: set[int] = set()
        self.field_ids: set[int] = set()
        self.counts = {
            "organizations": 0,
            "departments": 0,
            "roles": 0,
            "persons": 0,
            "memberships": 0,
            "bookings": 0,
            "invoices": 0,
            "files": 0,
        }

    # --- Bausteine ---

    def roles(self, org: Organization) -> tuple[list, list]:
        roles = list(Role.objects.filter(organization=org).order_by("name"))
        self.counts["roles"] += len(roles)
        role_data = [
            {
                "id": r.pk,
                "name": r.name,
                "description": r.description,
                "permissions": list(r.permissions or []),
                "is_board": r.is_board,
                "represents": r.represents,
                "on_letterhead": r.on_letterhead,
                "contact_email": r.contact_email,
                "on_website": r.on_website,
                "website_position": r.website_position,
                "in_chronicle": r.in_chronicle,
            }
            for r in roles
        ]
        assignments = []
        member_data = self.member_data_for(org)
        for a in (
            RoleAssignment.objects.filter(organization=org, role__department__isnull=True)
            .select_related("user")
            .order_by("valid_from", "pk")
        ):
            person_id = a.person_id if member_data else None
            if a.user_id is None and person_id is None and not a.name:
                continue
            if person_id:
                self.person_ids.add(person_id)
            assignments.append(
                {
                    "role": a.role_id,
                    "email": a.user.email if a.user_id else None,
                    "name": (
                        f"{a.user.first_name} {a.user.last_name}".strip() if a.user_id else ""
                    ),
                    "person": person_id,
                    # Früherer Inhaber ohne Konto (Mitglieder › Ämter)
                    "holder_name": a.name,
                    **period(a),
                }
            )
        return role_data, assignments

    def member_types(self, org: Organization) -> list:
        return [
            {
                "id": t.pk,
                **values(t, ("name", "reported", "active", "counts_for_duration", "is_archived")),
                "sort_order": t.sort_order,
            }
            for t in MemberType.objects.filter(organization=org)
        ]

    def fields(self, org: Organization) -> list:
        result = []
        for d in FieldDefinition.objects.filter(organization=org):
            self.field_ids.add(d.pk)
            result.append(
                {
                    "id": d.pk,
                    **values(
                        d,
                        (
                            "label",
                            "key",
                            "field_type",
                            "choices",
                            "repeatable",
                            "subfields",
                            "federation_wide",
                            "help_text",
                            "sort_order",
                            "is_archived",
                        ),
                    ),
                }
            )
        return result

    def department(
        self, dept: Department, with_holders: bool = True, tables: dict | None = None
    ) -> dict:
        self.counts["departments"] += 1
        data = {
            "id": dept.pk,
            # Übergeordnete Untereinheit (leer: direkt unter der Einheit)
            "parent_unit": None if dept.parent_id == dept.organization_id else dept.parent_id,
            **values(dept, DEPT_FIELDS),
            "logo": self.packer.add(dept.logo, "logos"),
            "roles": [
                {
                    "id": r.pk,
                    "name": r.name,
                    "permissions": list(r.permissions or []),
                    "position": r.position,
                    "on_letterhead": r.on_letterhead,
                    "contact_email": r.contact_email,
                    "on_website": r.on_website,
                    "in_chronicle": r.in_chronicle,
                    # Frühere Inhaber ohne Mitgliedschaft (Mitglieder › Ämter), nur Name
                    "former_holders": [
                        {"name": a.name, **period(a)}
                        for a in r.assignments.filter(
                            membership__isnull=True, user__isnull=True
                        ).exclude(name="")
                    ],
                }
                for r in DepartmentRole.objects.filter(department=dept)
            ],
            "imprint": imprint_data(dept),
            "letterhead": letterhead_data(dept),
        }
        if tables:
            # Kasse, Rechnungen, Belege … des eigenen Arbeitsbereichs (Audit 31.10. D31-01)
            data["tables"] = tables
        return data

    def membership(self, m: Membership, club: Organization, dept: Department | None = None):
        """Eine Mitgliedschaft. ``m`` kommt mit ``MEMBERSHIP_PREFETCH``."""
        self.person_ids.add(m.person_id)
        self.counts["memberships"] += 1
        departments = [
            d for d in m.department_memberships.all() if dept is None or d.department_id == dept.pk
        ]
        holders = sorted(
            (
                h
                for h in m.department_roles.all()
                if dept is None or h.role.department_id == dept.pk
            ),
            key=lambda h: (h.valid_from, h.pk),
        )
        photo = None
        if self.packer.with_files:
            photo = next(
                (p for p in m.photos.all() if p.status == MemberPhoto.Status.APPROVED), None
            )
        return {
            "id": m.pk,
            "person": m.person_id,
            "club_number": m.club_number,
            "pays_fee_self": m.pays_fee_self,
            "info_opt_out_at": plain(m.info_opt_out_at),
            "photo_consent_at": plain(m.photo_consent_at),
            "photo_consent_source": m.photo_consent_source,
            "purged_at": plain(m.purged_at),
            "origin_ref": m.origin_ref,
            "contact": self.contact(m.person, club),
            "periods": [
                {
                    **period(p, "entry_date", "exit_date"),
                    "exit_reason": p.exit_reason,
                    "note": p.note,
                }
                for p in m.periods.all()
            ],
            "types": [
                {"member_type": t.member_type_id, **period(t)} for t in m.type_assignments.all()
            ],
            "departments": [{"department": d.department_id, **period(d)} for d in departments],
            "department_roles": [{"role": h.role_id, **period(h)} for h in holders],
            "photo": (
                {
                    "image": self.packer.add(photo.image, "photos"),
                    "thumbnail": self.packer.add(photo.thumbnail, "photos"),
                    "width": photo.width,
                    "height": photo.height,
                    "source": photo.source,
                }
                if photo
                else None
            ),
        }

    def contact(self, person: Person, club: Organization) -> dict | None:
        contacts = list(person.contacts.all())
        own = next((c for c in contacts if c.organization_id == club.pk), None)
        shared = next((c for c in contacts if c.organization_id is None), None)
        chosen = (shared or own) if self.shared_contacts else (own or shared)
        return values(chosen, CONTACT_FIELDS) if chosen else None

    def tables(
        self, org: Organization, everything: bool = True, department=None, members=True
    ) -> dict:
        tables = dump_tables(
            org, self.packer, everything=everything, department=department, members=members
        )
        self.counts["bookings"] += len(tables.get("finance.booking", []))
        self.counts["invoices"] += len(tables.get("billing.invoice", []))
        return tables

    def organization(self, org: Organization) -> dict:
        self.counts["organizations"] += 1
        roles, assignments = self.roles(org)
        data = {
            "id": org.pk,
            "uuid": str(org.uuid),
            **values(org, ORG_FIELDS),
            "contact_role": org.contact_role_id,
            "logo": self.packer.add(org.logo, "logos"),
            "roles": roles,
            "role_assignments": assignments,
            "fields": self.fields(org),
            "imprint": imprint_data(org),
            "social_links": social_data(org),
            "letterhead": letterhead_data(org),
        }
        if not org.is_remote:
            # Verbund: offene Kopplungen ziehen beim Umzug mit (ohne Schlüssel dieser Instanz)
            from peering.moving import dump_couplings

            couplings = dump_couplings(org)
            if couplings:
                data["peering"] = couplings
        member_data = self.member_data_for(org)
        if org.type == Organization.Type.CLUB:
            data["member_data"] = member_data
            data["member_types"] = self.member_types(org)
            # Baumreihenfolge, damit beim Einlesen jede Einheit vor ihren Untereinheiten kommt
            units = {d.pk: d for d in Department.objects.filter(organization=org)}
            data["departments"] = [
                self.department(
                    units[pk],
                    tables=self.tables(
                        units[pk], everything=self.finance_for(org), members=bool(member_data)
                    ),
                )
                for pk in UnitTree.of(org.pk).ordered()
            ]
            data["memberships"] = (
                [
                    self.membership(m, org)
                    for m in Membership.objects.filter(organization=org)
                    .select_related("person")
                    .prefetch_related(*MEMBERSHIP_PREFETCH)
                    .order_by("pk")
                ]
                if member_data
                else []
            )
        # Kasse und Beiträge nur mit Recht darauf, Satzungen immer
        tables = self.tables(org, everything=self.finance_for(org), members=bool(member_data))
        if tables:
            data["tables"] = tables
        if org.type == Organization.Type.FEDERATION and org.direct_members:
            # Eigene Mitglieder des Dachverbands (Audit 31.10. D31-02); eigene Daten,
            # unabhängig von der Freigabe für Vereinsdaten
            data["member_types"] = self.member_types(org)
            data["memberships"] = [
                self.membership(m, org)
                for m in Membership.objects.filter(organization=org)
                .select_related("person")
                .prefetch_related(*MEMBERSHIP_PREFETCH)
                .order_by("pk")
            ]
        if org.type == Organization.Type.FEDERATION:
            data["clubs"] = [
                self.organization(c)
                for c in org.children.filter(type=Organization.Type.CLUB).order_by("name")
            ]
        return data

    def persons(self) -> list:
        fed_numbers = {
            fm.person_id: fm
            for fm in FederationMember.objects.filter(person_id__in=self.person_ids)
        }
        field_values: dict[int, list] = {}
        for v in FieldValue.objects.filter(
            person_id__in=self.person_ids, definition_id__in=self.field_ids
        ):
            field_values.setdefault(v.person_id, []).append(
                {"field": v.definition_id, "value": v.value}
            )
        result = []
        for p in Person.objects.filter(pk__in=self.person_ids).order_by("pk"):
            fm = fed_numbers.get(p.pk)
            result.append(
                {
                    "id": p.pk,
                    **values(p, ("last_name", "first_name", "birth_date", "gender")),
                    "federation": (
                        {
                            "member_number": fm.member_number,
                            "manual_entry_date": plain(fm.manual_entry_date),
                        }
                        if fm
                        else None
                    ),
                    "field_values": field_values.get(p.pk, []),
                }
            )
        self.counts["persons"] = len(result)
        return result


def _header(kind: str, source, with_files: bool) -> dict:
    return {
        "format": FORMAT,
        "version": VERSION,
        "kind": kind,
        "exported_at": timezone.now().isoformat(),
        "source": {"type": getattr(source, "type", "department"), "name": source.name},
        "with_files": with_files,
        "person_data_mode": PlatformSettings.load().person_data_mode,
    }


def export_organization(org: Organization, *, with_files: bool, by_platform: bool):
    """Daten einer Organisation mit ihren Untereinheiten.

    Ein Dachverband bekommt Mitgliedsdaten und Kasse seiner Vereine nur, soweit
    die Plattform ihm Zugriff gibt (Mitgliedsdaten) bzw. gar nicht (Kasse). Die
    Plattform bekommt alles.
    """

    def member_data_for(o: Organization) -> bool:
        if by_platform or o.pk == org.pk:
            return True
        return org.federation_member_access != Organization.MemberAccess.NONE

    def finance_for(o: Organization) -> bool:
        return o.type != Organization.Type.PLATFORM and (by_platform or o.pk == org.pk)

    with consistent_snapshot(), rls_bypass():
        dumper = Dumper(
            with_files=with_files, member_data_for=member_data_for, finance_for=finance_for
        )
        doc = _header("organization", org, with_files)
        body = dumper.organization(org)
        doc["persons"] = dumper.persons()
        doc["organization"] = body
        return _finish(doc, dumper, org.name)


@contextmanager
def consistent_snapshot():
    """Alle Tabellen auf demselben Stand lesen (REPEATABLE READ).

    Sonst könnten gleichzeitige Änderungen zwischen dem Lesen zweier Tabellen ein
    Paket mit Verweisen ins Leere ergeben. Läuft schon eine Transaktion (Tests),
    wird sie mitbenutzt.
    """
    if connection.in_atomic_block:
        yield
        return
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        yield


def export_department(dept: Department, *, with_files: bool, spin_off: dict | None = None):
    """Eine Abteilung: Stammdaten, Rollen, Mitglieder (mit ihren Vereinsdaten)."""
    club = dept.organization
    with consistent_snapshot(), rls_bypass():
        dumper = Dumper(
            with_files=with_files, member_data_for=lambda o: True, finance_for=lambda o: False
        )
        doc = _header("department", dept, with_files)
        doc["club"] = {
            "name": club.name,
            "department_label": club.department_label,
            # Für den Fall, dass die Untereinheit eigene Einheit wird (Verbund, Schritt 8b)
            "uuid": str(club.uuid),
            "street": club.street,
            "postal_code": club.postal_code,
            "city": club.city,
            "country": club.country,
            "date_precision": club.date_precision,
        }
        doc["department"] = dumper.department(dept)
        doc["tables"] = dumper.tables(club, department=dept)
        memberships = Membership.objects.filter(
            organization=club, department_memberships__department=dept
        ).distinct()
        memberships = memberships.select_related("person").prefetch_related(*MEMBERSHIP_PREFETCH)
        doc["memberships"] = [dumper.membership(m, club, dept) for m in memberships.order_by("pk")]
        type_ids = {t["member_type"] for m in doc["memberships"] for t in m["types"]}
        doc["member_types"] = [t for t in dumper.member_types(club) if t["id"] in type_ids]
        if spin_off:
            # Ausgliederung (Verbund, Schritt 8c): Weg, Stichtag und Kopplungscode für die
            # neue Instanz; Kasse und Rechnungen im eigenen Datenbereich gehen mit
            doc["spin_off"] = {
                "way": spin_off.get("way"),
                "cutoff": spin_off.get("cutoff"),
                "code": spin_off.get("code"),
                "club_uuid": str(club.uuid),
                "unit_uuid": str(dept.uuid),
            }
            if dept.own_workspace:
                doc["workspace_tables"] = dumper.tables(dept, members=False)
        doc["persons"] = dumper.persons()
        return _finish(doc, dumper, dept.name)


def _finish(doc: dict, dumper: Dumper, name: str) -> tuple[bytes, str, dict]:
    stamp = timezone.localtime().strftime("%Y-%m-%d")
    base = f"{slugify(name)[:60] or 'export'}-{stamp}"
    counts = dict(dumper.counts)
    counts["files"] = len(dumper.packer.files)
    doc["counts"] = counts
    payload = json.dumps(doc, ensure_ascii=False, indent=1).encode()
    if not dumper.packer.with_files:
        return payload, f"{base}.json", counts
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(JSON_NAME, payload)
        for path, fieldfile in dumper.packer.files:
            try:
                with fieldfile.open("rb") as handle:
                    archive.writestr(path, handle.read())
            except FileNotFoundError:
                # Datei fehlt im Speicher: Verweis bleibt, der Import meldet es
                continue
    return buffer.getvalue(), f"{base}.zip", counts
