"""Import: aus einer Exportdatei eine neue Organisation bzw. Abteilung anlegen.

Zwei Schritte:

1. ``check(job)`` liest die Datei, prüft sie und schreibt die Vorschau (Anzahlen,
   Fehler, Warnungen, mögliche Dubletten mit Vorschlag) nach ``job.preview``.
2. ``run(job, user)`` prüft erneut mit den Entscheidungen aus ``job.decisions``
   und legt alles in einer Transaktion an. Bei einem Fehler wird nichts angelegt.

Wo was entsteht:

- Plattform: Datei eines Dachverbands (mit Vereinen) oder eines Vereins → neue
  Organisation direkt unter der Plattform.
- Dachverband: Datei eines Vereins → neuer Verein im Dachverband.
- Verein: Datei einer Abteilung → neue Abteilung im Verein.
"""

from __future__ import annotations

import datetime
import json
import uuid
import zipfile

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from access.catalog import DEFAULT_MODULES, DEPARTMENT_CODES, SWITCHABLE_MODULES, codes_for
from access.models import Role, RoleAssignment
from accounts.models import User
from core.filecheck import clean_logo
from core.tenancy import rls_bypass
from customfields.models import FieldDefinition, FieldValue, clean_value
from members.models import (
    ContactDetails,
    DepartmentMembership,
    DepartmentRoleHolder,
    FederationMember,
    Gender,
    Membership,
    MembershipPeriod,
    MemberType,
    MemberTypeAssignment,
    Person,
    today,
)
from members.photo_models import MemberPhoto
from members.photos import FULL_SIZE, THUMB_SIZE, clean_photo
from organizations.models import (
    SHORT_NAME_MAX,
    Department,
    DepartmentRole,
    Organization,
    PlatformSettings,
)
from organizations.terms import department_terms, fill

from . import dump
from .tables import (
    DEPARTMENT_IMPORT_MODELS,
    NOT_INCLUDED,
    IdMap,
    check_cash_receipts,
    check_tables,
    load_tables,
)

MAX_JSON_BYTES = 200 * 1024 * 1024
MAX_FILE_BYTES = 25 * 1024 * 1024  # eine Datei im Archiv (größte Uploadgrenze: 20 MB)
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024  # alle Dateien zusammen, entpackt


def clean_email(value) -> str:
    """E-Mail-Adresse aus der Datei übernehmen, ungültige weglassen."""
    from django.core.exceptions import ValidationError as DjangoValidationError
    from django.core.validators import validate_email

    value = str(value or "").strip()[:254]
    try:
        validate_email(value)
    except DjangoValidationError:
        return ""
    return value


def load_social_links(org: Organization, items: list | None) -> None:
    """Social-Media-Kanäle (nur gültige Arten und Adressen)."""
    from django.core.exceptions import ValidationError as DjangoValidationError
    from django.core.validators import URLValidator

    from organizations.models import SocialLink

    check = URLValidator(schemes=["http", "https"])
    for pos, item in enumerate(items or []):
        if not isinstance(item, dict) or item.get("kind") not in SocialLink.Kind.values:
            continue
        url = str(item.get("url") or "").strip()[:200]
        try:
            check(url)
        except DjangoValidationError:
            continue
        SocialLink.objects.create(
            organization=org,
            kind=item["kind"],
            url=url,
            label=str(item.get("label") or "")[:100],
            position=item.get("position") if isinstance(item.get("position"), int) else pos,
        )


def load_letterhead(org: Organization, data: dict | None) -> None:
    """Briefbogen übernehmen; unbekannte Werte fallen auf den Standard zurück."""
    from letterhead.data import ensure
    from letterhead.models import Letterhead

    if not isinstance(data, dict):
        return
    lh = ensure(org)
    for field in dump.LETTERHEAD_FIELDS:
        if field not in data:
            continue
        value = data[field]
        model_field = Letterhead._meta.get_field(field)
        if model_field.get_internal_type() == "BooleanField":
            setattr(lh, field, bool(value))
        elif getattr(model_field, "choices", None):
            if value in {c[0] for c in model_field.choices}:
                setattr(lh, field, value)
        else:
            setattr(lh, field, str(value or "")[: model_field.max_length])
    if lh.mode == Letterhead.Mode.INHERIT and org.type != Organization.Type.UNIT:
        lh.mode = Letterhead.Mode.OWN
    lh.save()


def load_imprint(org: Organization, data: dict | None) -> None:
    """Übernimmt das gepflegte Impressum (ältere Dateien haben keins)."""
    if not isinstance(data, dict):
        return
    from organizations.imprint import ensure
    from organizations.models import Imprint

    imprint = ensure(org)
    for field in dump.IMPRINT_FIELDS:
        value = data.get(field)
        if isinstance(value, bool) and field == "registered":
            imprint.registered = value
        elif isinstance(value, str):
            setattr(imprint, field, value[: Imprint._meta.get_field(field).max_length or None])
    if imprint.mode not in Imprint.Mode.values:
        imprint.mode = Imprint.default_mode(org)
    if imprint.privacy_mode not in Imprint.PrivacyMode.values:
        imprint.privacy_mode = Imprint.PrivacyMode.TEXT
    if "privacy_published_text" not in data:
        # Ältere Dateien: dort war der Text sofort öffentlich
        imprint.privacy_published_text = imprint.privacy_text
    imprint.privacy_published_at = timezone.now() if imprint.privacy_published_text else None
    imprint.save()


EXIT_REASONS = {"exit", "exclusion", "strike_off", "death", "transfer"}
CONTACT_FIELDS = dump.CONTACT_FIELDS
MAX_LISTED = 50  # so viele Fehler/Warnungen höchstens in der Vorschau


def small_int(value) -> int:
    """Kleine, nicht negative Zahl aus der Datei (sonst 0)."""
    return value if isinstance(value, int) and 0 <= value <= 32767 else 0


def parse_uuid(value):
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


class FileProblem(Exception):
    """Die Datei lässt sich nicht lesen oder passt nicht zu dieser Ebene."""


# --- Datei lesen ---


class Files:
    """Dateien aus der ZIP-Datei (oder keine bei reiner JSON-Datei)."""

    def __init__(self, archive: zipfile.ZipFile | None):
        self.archive = archive
        self.names = set(archive.namelist()) if archive else set()
        self.total = 0

    def has(self, path: str | None) -> bool:
        return bool(path) and path in self.names

    def read(self, path: str | None) -> bytes | None:
        """Datei lesen, höchstens ``MAX_FILE_BYTES`` je Datei und ``MAX_TOTAL_BYTES`` gesamt.

        Gezählt wird beim Entpacken, nicht nach der Angabe im ZIP-Verzeichnis.
        """
        if not self.has(path):
            return None
        with self.archive.open(path) as handle:
            content = handle.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise FileProblem(f"Die Datei „{path}“ im Archiv ist zu groß.")
        self.total += len(content)
        if self.total > MAX_TOTAL_BYTES:
            raise FileProblem("Die Dateien im Archiv sind zusammen zu groß.")
        return content


def open_file(fieldfile) -> tuple[dict, Files]:
    with fieldfile.open("rb") as handle:
        magic = handle.read(2)
    archive = None
    if magic == b"PK":
        try:
            # Direkt aus dem Speicher lesen, nicht die ganze ZIP-Datei in den Arbeitsspeicher
            archive = zipfile.ZipFile(fieldfile.path)
        except zipfile.BadZipFile as exc:
            raise FileProblem("Die ZIP-Datei ist beschädigt.") from exc
        if dump.JSON_NAME not in archive.namelist():
            raise FileProblem(f"In der ZIP-Datei fehlt {dump.JSON_NAME}.")
        info = archive.getinfo(dump.JSON_NAME)
        if info.file_size > MAX_JSON_BYTES:
            raise FileProblem("Die Exportdatei ist zu groß.")
        with archive.open(dump.JSON_NAME) as handle:
            raw = handle.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise FileProblem("Die Exportdatei ist zu groß.")
    else:
        if fieldfile.size > MAX_JSON_BYTES:
            raise FileProblem("Die Exportdatei ist zu groß.")
        with fieldfile.open("rb") as handle:
            raw = handle.read()
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FileProblem("Das ist keine gültige JSON-Datei.") from exc
    if not isinstance(doc, dict) or doc.get("format") != dump.FORMAT:
        raise FileProblem("Das ist keine Exportdatei von HUBIplan.")
    version = doc.get("version")
    if not isinstance(version, int) or version > dump.VERSION:
        raise FileProblem(
            f"Die Datei hat Version {version}. Diese Installation liest bis Version "
            f"{dump.VERSION}. Bitte die Software aktualisieren."
        )
    return doc, Files(archive)


ADDRESS_LABELS = {"street": "Straße", "postal_code": "PLZ", "city": "Ort"}


def unit_address(doc: dict, options: dict) -> dict:
    """Anschrift für eine Untereinheit, die eigene Einheit wird: Angabe beim Import,
    sonst die des abgebenden Vereins aus der Datei."""
    club = doc.get("club") if isinstance(doc.get("club"), dict) else {}
    result = {}
    for field in (*ADDRESS_LABELS, "country"):
        value = options.get(field) or club.get(field) or ""
        result[field] = str(value).strip()
    return result


def expected_for(target: Organization) -> tuple[str, tuple[str, ...]]:
    """Welche Dateien die Ebene importieren kann: (kind, erlaubte Organisationsarten)."""
    if target.type == Organization.Type.PLATFORM:
        return "organization", (Organization.Type.FEDERATION, Organization.Type.CLUB)
    if target.type == Organization.Type.FEDERATION:
        return "organization", (Organization.Type.CLUB,)
    return "department", ()


# --- kleine Prüfhelfer ---


def parse_date(value) -> datetime.date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value)[:10])


def parse_datetime(value):
    if value in (None, ""):
        return None
    return datetime.datetime.fromisoformat(str(value))


def full_name(p: dict) -> str:
    return f"{p.get('last_name', '')}, {p.get('first_name', '')}".strip(", ")


def covers(item: dict, start: str, end: str, on: datetime.date) -> bool:
    begin = parse_date(item.get(start))
    finish = parse_date(item.get(end))
    return begin is not None and begin <= on and (finish is None or finish >= on)


class Problems:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, text: str) -> None:
        self.errors.append(text)

    def warn(self, text: str) -> None:
        self.warnings.append(text)


# --- Prüfung ---


class Checker:
    """Prüft die Datei gegen die Zielebene und ermittelt Dubletten."""

    def __init__(self, job, doc: dict, files: Files):
        self.job = job
        self.target: Organization = job.organization
        # Texte in der Abteilungsbezeichnung des Zielvereins
        self.t = department_terms(self.target)
        self.doc = doc
        self.files = files
        self.p = Problems()
        self.persons = {p.get("id"): p for p in doc.get("persons") or [] if isinstance(p, dict)}
        self.known: dict[str, set] = {
            "organization": set(),
            "department": set(),
            "membership": set(),
            "member_type": set(),
            "person": set(self.persons),
        }
        self.type_by_id: dict = {}
        self.summary = {
            "organizations": 0,
            "clubs": 0,
            "departments": 0,
            "roles": 0,
            "role_assignments": 0,
            "persons": len(self.persons),
            "memberships": 0,
            "table_rows": 0,
            "files": 0,
            "already_members": 0,
        }
        self.classes: dict[str, int] = {}

    # Grundprüfung

    def check(self) -> dict:
        kind, types = expected_for(self.target)
        doc_kind = self.doc.get("kind")
        # Plattform: eine Untereinheit wird zur eigenen Einheit (Verbund, Schritt 8b)
        as_unit = self.target.type == Organization.Type.PLATFORM and doc_kind == "department"
        if doc_kind != kind and not as_unit:
            raise FileProblem(self.wrong_kind_message(doc_kind))
        self.check_persons()
        if kind == "organization" and not as_unit:
            data = self.doc.get("organization")
            if not isinstance(data, dict):
                raise FileProblem("In der Datei fehlt die Organisation.")
            if data.get("type") not in types:
                raise FileProblem(self.wrong_kind_message(data.get("type")))
            self.check_org(data, top=True)
            name = (self.job.options or {}).get("name") or data.get("name") or ""
            self.check_org_name(name, data.get("type"))
            title, org_type = name, data.get("type")
        else:
            data = self.doc.get("department")
            if not isinstance(data, dict):
                raise FileProblem(fill("In der Datei fehlt {akk}.", self.t))
            for t in self.doc.get("member_types") or []:
                self.known["member_type"].add(t.get("id"))
                self.type_by_id[t.get("id")] = t
            self.check_department(data)
            where = f"{self.target.department_label} {data.get('name')}"
            for m in self.doc.get("memberships") or []:
                self.check_membership(m, where)
            if self.doc.get("tables"):
                check_cash_receipts(self.doc["tables"], self.p.warn)
                self.summary["table_rows"] += check_tables(
                    self.doc["tables"],
                    self.known,
                    self.p.errors,
                    where,
                    allowed=DEPARTMENT_IMPORT_MODELS,
                    per_class=self.classes,
                )
            name = (self.job.options or {}).get("name") or data.get("name") or ""
            if as_unit:
                self.check_org_name(name, Organization.Type.CLUB)
                address = unit_address(self.doc, self.job.options or {})
                missing = [label for f, label in ADDRESS_LABELS.items() if not address.get(f)]
                if missing:
                    self.p.error(
                        "Für die neue Einheit fehlt die Anschrift ("
                        + ", ".join(missing)
                        + "). Bitte beim Import angeben."
                    )
                kind, org_type = "unit", Organization.Type.CLUB
                if self.doc.get("workspace_tables"):
                    # Kasse und Rechnungen der Untereinheit (Ausgliederung, Fachfrage 3)
                    check_cash_receipts(self.doc["workspace_tables"], self.p.warn)
                    self.summary["table_rows"] += check_tables(
                        self.doc["workspace_tables"], self.known, self.p.errors, where
                    )
            elif Department.objects.filter(parent=self.target, name=name).exists():
                self.p.error(
                    fill("{e_Im} gibt es schon ", self.t)
                    + f"„{name}“. Bitte beim Import einen anderen Namen angeben."
                )
            if not as_unit:
                org_type = "department"
            title = name
        self.check_missing_files()
        duplicates = self.find_duplicates()
        self.check_active_conflicts(duplicates)
        users = self.user_summary()
        return {
            "kind": kind,
            "type": org_type,
            "name": title,
            "source": self.doc.get("source") or {},
            "exported_at": self.doc.get("exported_at"),
            "with_files": bool(self.doc.get("with_files")),
            "summary": self.summary,
            "classes": dict(sorted(self.classes.items())),
            "not_included": NOT_INCLUDED,
            "errors": self.p.errors[:MAX_LISTED],
            "error_count": len(self.p.errors),
            "warnings": self.p.warnings[:MAX_LISTED],
            "warning_count": len(self.p.warnings),
            "duplicates": duplicates,
            "users": users,
        }

    def wrong_kind_message(self, found) -> str:
        labels = {
            "federation": "einer übergeordneten Einheit",
            "club": "einer Einheit mit Mitgliedern",
            "department": "einer Untereinheit",
            "organization": "einer Einheit",
        }
        wanted = {
            "platform": "Hier lassen sich Dateien von Einheiten mit Mitgliedern, von "
            "übergeordneten Einheiten und von Untereinheiten (werden eigene Einheiten) "
            "importieren.",
            "federation": fill("Hier lassen sich nur Dateien von {pl_dat} importieren.", self.t),
            "club": fill("Hier lassen sich nur Dateien von {pl_dat} importieren.", self.t),
        }[self.target.type]
        return f"Die Datei enthält die Daten {labels.get(found, 'unbekannter Art')}. {wanted}"

    def check_org_name(self, name: str, org_type: str) -> None:
        if not name.strip():
            self.p.error("Die Einheit braucht einen Namen.")
            return
        parent = self.target
        if Organization.objects.filter(parent=parent, name__iexact=name.strip()).exists():
            self.p.warn(f"Es gibt hier schon eine Einheit mit dem Namen „{name}“.")

    def check_persons(self) -> None:
        for p in self.persons.values():
            where = f"Person {full_name(p) or p.get('id')}"
            if not p.get("last_name") or not p.get("first_name"):
                self.p.error(f"{where}: Name oder Vorname fehlt.")
            try:
                if parse_date(p.get("birth_date")) is None:
                    self.p.error(f"{where}: Geburtsdatum fehlt.")
            except ValueError:
                self.p.error(f"{where}: Geburtsdatum ist ungültig.")

    def check_org(self, data: dict, top: bool = False) -> None:
        self.summary["organizations"] += 1
        if data.get("type") == "club" and not top:
            self.summary["clubs"] += 1
        self.known["organization"].add(data.get("id"))
        where = data.get("name") or "Organisation"
        for field in ("founding_year", "street", "postal_code", "city"):
            if not data.get(field):
                self.p.error(f"{where}: Pflichtfeld „{field}“ fehlt.")
        role_ids = set()
        allowed = set(codes_for(data.get("type") or "club"))
        for r in data.get("roles") or []:
            self.summary["roles"] += 1
            role_ids.add(r.get("id"))
            unknown = sorted(set(r.get("permissions") or []) - allowed)
            if unknown:
                self.p.warn(
                    f"{where}: Rolle „{r.get('name')}“ hat hier unbekannte Rechte, sie "
                    f"entfallen: {', '.join(unknown)}"
                )
        for a in data.get("role_assignments") or []:
            self.summary["role_assignments"] += 1
            if a.get("role") not in role_ids:
                self.p.error(f"{where}: Rollenbesetzung verweist auf eine fehlende Rolle.")
            if a.get("person") is not None and a.get("person") not in self.persons:
                self.p.error(f"{where}: Rollenbesetzung verweist auf eine fehlende Person.")
        for t in data.get("member_types") or []:
            self.known["member_type"].add(t.get("id"))
            self.type_by_id[t.get("id")] = t
        for d in data.get("departments") or []:
            self.check_department(d, where)
        for m in data.get("memberships") or []:
            self.check_membership(m, where)
        if data.get("logo") and not self.files.has(data.get("logo")):
            self.p.warn(f"{where}: Das Logo fehlt in der Datei.")
        for c in data.get("clubs") or []:
            self.check_org(c)
        if data.get("tables"):
            check_cash_receipts(data.get("tables"), self.p.warn)
            self.summary["table_rows"] += check_tables(
                data.get("tables"), self.known, self.p.errors, where, per_class=self.classes
            )
        for d in data.get("departments") or []:
            if d.get("tables"):
                self.summary["table_rows"] += check_tables(
                    d["tables"],
                    self.known,
                    self.p.errors,
                    f"{where}, {d.get('name')}",
                    per_class=self.classes,
                )

    def check_department(self, d: dict, where: str = "") -> None:
        self.summary["departments"] += 1
        self.known["department"].add(d.get("id"))
        label = f"{where}: " if where else ""
        if not d.get("name"):
            self.p.error(label + fill("{Ein} hat keinen Namen.", self.t))
        dept_roles = self.known.setdefault("department_role", set())
        for r in d.get("roles") or []:
            dept_roles.add(r.get("id"))

    def check_membership(self, m: dict, where: str) -> None:
        self.summary["memberships"] += 1
        self.known["membership"].add(m.get("id"))
        person = self.persons.get(m.get("person"))
        if person is None:
            self.p.error(f"{where}: Eine Mitgliedschaft verweist auf eine fehlende Person.")
            return
        who = f"{where}, {full_name(person)}"
        try:
            for period in m.get("periods") or []:
                entry = parse_date(period.get("entry_date"))
                exit_ = parse_date(period.get("exit_date"))
                if entry is None:
                    self.p.error(f"{who}: Eintrittsdatum fehlt.")
                elif exit_ and exit_ < entry:
                    self.p.error(f"{who}: Austritt liegt vor dem Eintritt.")
                if exit_ and period.get("exit_reason") not in EXIT_REASONS:
                    self.p.error(f"{who}: Austrittsgrund fehlt oder ist unbekannt.")
            for t in m.get("types") or []:
                parse_date(t.get("valid_from"))
                parse_date(t.get("valid_until"))
                if t.get("member_type") not in self.known["member_type"]:
                    self.p.error(f"{who}: Mitgliedsart fehlt in der Datei.")
            for d in m.get("departments") or []:
                parse_date(d.get("valid_from"))
                if d.get("department") not in self.known["department"]:
                    self.p.error(f"{who}: {self.t['Sg']} fehlt in der Datei.")
            for h in m.get("department_roles") or []:
                parse_date(h.get("valid_from"))
                if h.get("role") not in self.known.get("department_role", set()):
                    self.p.error(f"{who}: " + fill("Rolle {im} fehlt in der Datei.", self.t))
        except ValueError:
            self.p.error(f"{who}: Ein Datum ist ungültig.")
        if not m.get("periods"):
            self.p.warn(f"{who}: keine Mitgliedszeiträume.")
        photo = m.get("photo")
        if photo and not self.files.has(photo.get("image")):
            self.p.warn(f"{who}: Das Foto fehlt in der Datei.")

    def check_missing_files(self) -> None:
        self.summary["files"] = len([n for n in self.files.names if n.startswith("files/")])
        if self.doc.get("with_files") and self.files.archive is None:
            self.p.warn(
                "Die Datei wurde mit Dateien exportiert, aber nur die JSON-Datei wurde "
                "hochgeladen. Logos, Belege und Fotos fehlen deshalb."
            )
        without = {"finance.receipt": 0, "statutes.statuteversion": 0}
        for tables in self.all_tables():
            for name in without:
                without[name] += sum(
                    1 for row in tables.get(name) or [] if not self.files.has(row.get("file"))
                )
        if without["finance.receipt"]:
            self.p.warn(
                f"{without['finance.receipt']} Belege ohne Datei werden nicht übernommen "
                f"(für Belege den Export mit Dateien verwenden)."
            )
        if without["statutes.statuteversion"]:
            self.p.warn(
                f"{without['statutes.statuteversion']} Satzungsfassungen ohne PDF werden nicht "
                f"übernommen (für die Satzung den Export mit Dateien verwenden)."
            )

    def all_tables(self) -> list[dict]:
        if self.doc.get("kind") == "department":
            return [self.doc.get("tables") or {}, self.doc.get("workspace_tables") or {}]
        result = []

        def walk(org):
            result.append(org.get("tables") or {})
            for d in org.get("departments") or []:
                result.append(d.get("tables") or {})
            for c in org.get("clubs") or []:
                walk(c)

        walk(self.doc.get("organization") or {})
        return result

    # Dubletten

    def scope(self) -> Organization | None:
        """Verbandsbereich, in dem es die Personen schon geben kann (oder None)."""
        if self.target.type == Organization.Type.FEDERATION:
            return self.target
        if self.target.type == Organization.Type.CLUB:
            return self.target.federation or self.target
        return None  # Plattform: neuer Verbandsbereich

    def find_duplicates(self) -> list[dict]:
        scope = self.scope()
        if scope is None:
            return []
        decisions = (self.job.decisions or {}).get("persons") or {}
        club = self.target if self.target.type == Organization.Type.CLUB else None
        result = []
        with rls_bypass():
            for pid, p in self.persons.items():
                try:
                    birth = parse_date(p.get("birth_date"))
                except ValueError:
                    continue
                if birth is None:
                    continue
                candidates = list(
                    Person.objects.filter(
                        scope=scope,
                        birth_date=birth,
                        last_name__iexact=(p.get("last_name") or "").strip(),
                        first_name__iexact=(p.get("first_name") or "").strip(),
                    )
                    .select_related("federation")
                    .order_by("pk")[:5]
                )
                if not candidates:
                    continue
                infos = [self.candidate_info(c, club) for c in candidates]
                member_here = next((i for i in infos if i["member_here"]), None)
                if member_here:
                    # Schon Mitglied im Verein: wird nur der Abteilung zugeordnet
                    self.summary["already_members"] += 1
                    result.append(
                        {
                            "person": pid,
                            "name": full_name(p),
                            "birth_date": p.get("birth_date"),
                            "candidates": [member_here],
                            "choice": str(member_here["id"]),
                            "fixed": True,
                        }
                    )
                    continue
                choice = str(decisions.get(str(pid), infos[0]["id"]))
                if choice != "new" and choice not in {str(i["id"]) for i in infos}:
                    choice = str(infos[0]["id"])
                result.append(
                    {
                        "person": pid,
                        "name": full_name(p),
                        "birth_date": p.get("birth_date"),
                        "candidates": infos,
                        "choice": choice,
                        "fixed": False,
                    }
                )
        return result

    def candidate_info(self, person: Person, club: Organization | None) -> dict:
        memberships = Membership.objects.filter(person=person).select_related("organization")
        clubs = []
        member_here = False
        for m in memberships:
            current = m.current_period() is not None
            clubs.append({"name": m.organization.name, "current": current})
            if club is not None and m.organization_id == club.pk:
                member_here = True
        fm = getattr(person, "federation", None)
        return {
            "id": person.pk,
            "name": str(person),
            "birth_date": person.birth_date.isoformat(),
            "member_number": fm.member_number if fm else None,
            "clubs": clubs,
            "member_here": member_here,
        }

    def check_active_conflicts(self, duplicates: list[dict]) -> None:
        """Zusammengeführte Person darf nicht zweimal aktiv sein (im Dachverband)."""
        scope = self.scope()
        if scope is None or scope.type != Organization.Type.FEDERATION:
            return
        on = today()
        active_ids = {tid for tid, t in self.type_by_id.items() if t.get("active")}
        file_memberships = self.all_memberships()
        with rls_bypass():
            for dup in duplicates:
                if dup["fixed"] or dup["choice"] == "new":
                    continue
                active_in_file = any(
                    m.get("person") == dup["person"]
                    and any(
                        covers(x, "entry_date", "exit_date", on) for x in m.get("periods") or []
                    )
                    and any(
                        t.get("member_type") in active_ids
                        and covers(t, "valid_from", "valid_until", on)
                        for t in m.get("types") or []
                    )
                    for m in file_memberships
                )
                if not active_in_file:
                    continue
                other = self.active_club_of(int(dup["choice"]), on)
                if other:
                    self.p.error(
                        f"{dup['name']} ist bereits aktives Mitglied in „{other}“. Im "
                        f"Verband ist nur eine aktive Mitgliedschaft erlaubt. Bitte dort "
                        f"zuerst Austritt oder Wechsel zu einer nicht aktiven Art erfassen "
                        f"und erneut prüfen."
                    )

    def all_memberships(self) -> list[dict]:
        if self.doc.get("kind") == "department":
            return list(self.doc.get("memberships") or [])
        result = []

        def walk(org):
            result.extend(org.get("memberships") or [])
            for c in org.get("clubs") or []:
                walk(c)

        walk(self.doc.get("organization") or {})
        return result

    @staticmethod
    def active_club_of(person_id: int, on) -> str | None:
        for m in Membership.objects.filter(person_id=person_id).select_related("organization"):
            if m.current_period(on) is None:
                continue
            assignment = m.current_type(on)
            if assignment and assignment.member_type.active:
                return m.organization.name
        return None

    def user_summary(self) -> dict:
        emails = set()

        def walk(org):
            for a in org.get("role_assignments") or []:
                if a.get("email"):
                    emails.add(a["email"].strip().lower())
            for c in org.get("clubs") or []:
                walk(c)

        if self.doc.get("kind") == "organization":
            walk(self.doc.get("organization") or {})
        existing = set(User.objects.filter(email__in=emails).values_list("email", flat=True))
        return {"total": len(emails), "existing": len(existing), "new": len(emails - existing)}


def check(job) -> dict:
    # Systemprüfung über Organisationen hinweg; die Rechte hat die API-Ansicht geprüft
    with rls_bypass():
        doc, files = open_file(job.file)
        return Checker(job, doc, files).check()


# --- Anlegen ---


class Loader:
    def __init__(self, job, doc: dict, files: Files, preview: dict, user):
        self.job = job
        self.target: Organization = job.organization
        # Texte in der Abteilungsbezeichnung des Zielvereins
        self.t = department_terms(self.target)
        self.doc = doc
        self.files = files
        self.user = user
        self.options = job.options or {}
        self.by_platform = self.target.type == Organization.Type.PLATFORM
        self.ids = IdMap()
        self.persons = {p["id"]: p for p in doc.get("persons") or []}
        self.choices = {d["person"]: d["choice"] for d in preview.get("duplicates") or []}
        self.new_person_ids: set[int] = set()
        self.invitations: list[tuple[User, Organization, str]] = []
        self.shared = PlatformSettings.load().person_data_mode == PlatformSettings.PersonData.SHARED
        self.result: dict = {}

    def save_file(self, fieldfile, path: str | None) -> bool:
        content = self.files.read(path)
        if content is None:
            return False
        name = path.rsplit("/", 1)[-1].split("-", 1)[-1]
        fieldfile.save(name, ContentFile(content), save=False)
        return True

    def save_logo(self, fieldfile, path: str | None) -> bool:
        """Logo wie beim normalen Hochladen prüfen und als PNG neu schreiben."""
        content = self.files.read(path)
        if content is None:
            return False
        try:
            data = clean_logo(content)
        except ValidationError as exc:
            raise ValidationError(f"Logo „{path}“: {' '.join(exc.messages)}") from exc
        fieldfile.save("logo.png", ContentFile(data), save=False)
        return True

    def save_photo(self, fieldfile, path: str | None, size: int) -> bool:
        """Mitgliederfoto prüfen und neu als JPEG schreiben (ohne Metadaten)."""
        content = self.files.read(path)
        if content is None:
            return False
        fieldfile.save("foto.jpg", ContentFile(clean_photo(content, size)), save=False)
        return True

    # Personen

    def create_persons(self, scope: Organization) -> None:
        for pid, p in self.persons.items():
            choice = self.choices.get(pid)
            if choice and choice != "new":
                self.ids.set("person", pid, int(choice))
                continue
            person = Person.objects.create(
                scope=scope,
                last_name=p["last_name"].strip(),
                first_name=p["first_name"].strip(),
                birth_date=parse_date(p["birth_date"]),
                # Ältere Exporte kennen kein Geschlecht
                gender=p.get("gender") if p.get("gender") in Gender.values else "",
            )
            self.ids.set("person", pid, person.pk)
            self.new_person_ids.add(person.pk)

    def assign_federation_numbers(self, scope: Organization, reported_persons: set[int]) -> int:
        """Verbandsnummern für neue Personen: aus der Datei, wenn frei, sonst neu."""
        if scope.type != Organization.Type.FEDERATION:
            return 0
        Organization.objects.select_for_update().filter(pk=scope.pk).first()
        used = set(
            FederationMember.objects.filter(scope=scope).values_list("member_number", flat=True)
        )
        renumbered = 0
        later = []
        for pid, p in self.persons.items():
            new_id = self.ids.get("person", pid)
            if new_id not in self.new_person_ids:
                continue
            fed = p.get("federation") or {}
            number = fed.get("member_number")
            if number and number not in used:
                FederationMember.objects.create(
                    scope=scope,
                    person_id=new_id,
                    member_number=number,
                    manual_entry_date=parse_date(fed.get("manual_entry_date")),
                )
                used.add(number)
            elif number or new_id in reported_persons:
                later.append((new_id, fed))
                renumbered += 1 if number else 0
        next_number = max(used, default=0)
        for new_id, fed in later:
            next_number += 1
            FederationMember.objects.create(
                scope=scope,
                person_id=new_id,
                member_number=next_number,
                manual_entry_date=parse_date(fed.get("manual_entry_date")),
            )
        return renumbered

    def save_field_values(self) -> None:
        for pid, p in self.persons.items():
            person_id = self.ids.get("person", pid)
            for v in p.get("field_values") or []:
                definition_id = self.ids.get("field", v.get("field"))
                if definition_id is None:
                    continue
                definition = FieldDefinition.objects.get(pk=definition_id)
                # Gleiche Prüfung wie beim Speichern im Formular (gestrichene Auswahlwerte
                # bleiben erlaubt); ein Fehler bricht den ganzen Import ab
                try:
                    value = clean_value(definition, v["value"], any_choice=True)
                except ValidationError as exc:
                    name = " ".join(filter(None, [p.get("first_name"), p.get("last_name")]))
                    raise ValidationError(
                        f"Zusatzfeld „{definition.label}“ bei {name or 'einer Person'}: "
                        + " ".join(exc.messages)
                    ) from exc
                if value in (None, []):
                    continue
                FieldValue.objects.update_or_create(
                    definition=definition,
                    person_id=person_id,
                    defaults={"organization_id": definition.organization_id, "value": value},
                )

    # Organisation

    def create_org(self, data: dict, parent: Organization, top: bool) -> Organization:
        org = Organization(type=data["type"], parent=parent)
        for field in dump.ORG_FIELDS:
            if field in ("type", "contact_source") or field not in data:
                continue
            setattr(org, field, org._meta.get_field(field).to_python(data[field]))
        org.short_name = (org.short_name or "").strip()[:SHORT_NAME_MAX]
        # Feste Kennung mitnehmen (Umzug auf eine andere Instanz), solange sie hier frei ist
        given = parse_uuid(data.get("uuid"))
        if given and not Organization.objects.filter(uuid=given).exists():
            org.uuid = given
        org.contact_source = Organization.ContactSource.OWN
        org.contact_role = None
        if top and self.options.get("name"):
            org.name = self.options["name"].strip()
        org.is_active = True if top else bool(data.get("is_active", True))
        modules = [m for m in data.get("enabled_modules") or [] if m in SWITCHABLE_MODULES]
        if not self.by_platform:
            # Diese Schalter stellt nur die Plattform ein
            modules = list(DEFAULT_MODULES)
            org.tax_areas_enabled = False
        org.enabled_modules = modules
        if org.type != Organization.Type.FEDERATION or not self.by_platform:
            org.federation_member_access = Organization.MemberAccess.NONE
            org.federation_show_former_memberships = False
        try:
            org.clean()
        except ValidationError as exc:
            raise ValidationError(f"{org.name}: {'; '.join(exc.messages)}") from exc
        org.save()
        if data.get("logo") and self.save_logo(org.logo, data["logo"]):
            org.save(update_fields=["logo"])
        self.ids.set("organization", data.get("id"), org.pk)
        return org

    def fill_org(self, org: Organization, data: dict, scope: Organization) -> None:
        allowed = set(codes_for(org.type))
        for r in data.get("roles") or []:
            role = Role.objects.create(
                organization=org,
                name=r["name"],
                description=r.get("description") or "",
                permissions=sorted(set(r.get("permissions") or []) & allowed),
                is_board=bool(r.get("is_board", True)),
                represents=bool(r.get("represents", False)),
                on_letterhead=bool(r.get("on_letterhead", False)),
                contact_email=clean_email(r.get("contact_email")),
                on_website=bool(r.get("on_website", False)),
                website_position=small_int(r.get("website_position")),
                in_chronicle=bool(r.get("in_chronicle", False)),
            )
            self.ids.set("role", r.get("id"), role.pk)
        contact_role = self.ids.get("role", data.get("contact_role"))
        if data.get("contact_source") == "role" and contact_role:
            org.contact_source = Organization.ContactSource.ROLE
            org.contact_role_id = contact_role
            org.save(update_fields=["contact_source", "contact_role"])
        self.role_assignments(org, data)
        load_imprint(org, data.get("imprint"))
        load_social_links(org, data.get("social_links"))
        load_letterhead(org, data.get("letterhead"))
        for t in data.get("member_types") or []:
            mt = MemberType.objects.create(
                organization=org,
                name=t["name"],
                reported=bool(t.get("reported")),
                active=bool(t.get("active")),
                counts_for_duration=bool(t.get("counts_for_duration", True)),
                is_archived=bool(t.get("is_archived")),
                sort_order=t.get("sort_order") or 0,
            )
            self.ids.set("member_type", t.get("id"), mt.pk)
        for f in data.get("fields") or []:
            definition = FieldDefinition.objects.create(
                organization=org,
                label=f["label"],
                key=f["key"],
                field_type=f.get("field_type") or "text",
                choices=f.get("choices") or [],
                repeatable=bool(f.get("repeatable")),
                subfields=f.get("subfields") or [],
                federation_wide=bool(f.get("federation_wide"))
                and org.type == Organization.Type.FEDERATION,
                help_text=f.get("help_text") or "",
                sort_order=f.get("sort_order") or 0,
                is_archived=bool(f.get("is_archived")),
            )
            self.ids.set("field", f.get("id"), definition.pk)
        for d in data.get("departments") or []:
            self.create_department(org, d)
        for m in data.get("memberships") or []:
            self.create_membership(org, scope, m)
        for c in data.get("clubs") or []:
            club = self.create_org(c, org, top=False)
            self.fill_org(club, c, scope)
        if data.get("tables"):
            self.result["table_rows"] = self.result.get("table_rows", 0) + load_tables(
                data["tables"], org, self.ids, self.files, self.user
            )
        # Eigene Arbeitsbereiche der Untereinheiten nach den Mitgliedschaften und den
        # Tabellen der Einheit (Verweise darauf), Audit 31.10. D31-01
        for d in data.get("departments") or []:
            if d.get("tables"):
                dept = Department.objects.get(pk=self.ids.get("department", d.get("id")))
                self.result["table_rows"] = self.result.get("table_rows", 0) + load_tables(
                    d["tables"], dept, self.ids, self.files, self.user
                )

    def role_assignments(self, org: Organization, data: dict) -> None:
        invite = bool(self.options.get("invite"))
        for a in data.get("role_assignments") or []:
            role_id = self.ids.get("role", a.get("role"))
            person_id = self.ids.get("person", a.get("person"))
            email = (a.get("email") or "").strip().lower()
            user = User.objects.filter(email=email).first() if email else None
            if user is None and email and invite:
                names = (a.get("name") or "").split(" ", 1)
                user = User.objects.create_user(
                    email=email,
                    first_name=names[0] if names else "",
                    last_name=names[1] if len(names) > 1 else "",
                )
                user.set_unusable_password()
                user.save(update_fields=["password"])
                self.invitations.append((user, org, Role.objects.get(pk=role_id).name))
            holder_name = "" if user else (a.get("holder_name") or "").strip()[:200]
            if user is None and person_id is None and not holder_name:
                self.result["skipped_assignments"] = self.result.get("skipped_assignments", 0) + 1
                continue
            RoleAssignment.objects.create(
                organization=org,
                role_id=role_id,
                user=user,
                person_id=person_id,
                name=holder_name,
                name_public=bool(a.get("name_public", False)),
                valid_from=parse_date(a.get("valid_from")) or today(),
                valid_until=parse_date(a.get("valid_until")),
            )

    def create_department(self, club: Organization, d: dict, name: str | None = None):
        dept = Department(organization=club)
        # Übergeordnete Untereinheit, falls sie mit übernommen wurde
        parent_id = self.ids.get("department", d.get("parent_unit"))
        if parent_id:
            dept.parent_id = parent_id
        for field in dump.DEPT_FIELDS:
            if field in d:
                setattr(dept, field, dept._meta.get_field(field).to_python(d[field]))
        if name:
            dept.name = name
        dept.short_name = (dept.short_name or "").strip()[:SHORT_NAME_MAX]
        dept.save()
        if d.get("logo") and self.save_logo(dept.logo, d["logo"]):
            dept.save(update_fields=["logo"])
        load_imprint(dept, d.get("imprint"))
        load_letterhead(dept, d.get("letterhead"))
        self.ids.set("department", d.get("id"), dept.pk)
        for r in d.get("roles") or []:
            role = DepartmentRole.objects.create(
                organization=club,
                department=dept,
                name=r["name"],
                permissions=sorted(set(r.get("permissions") or []) & DEPARTMENT_CODES),
                position=r.get("position") or 0,
                on_letterhead=bool(r.get("on_letterhead", False)),
                contact_email=clean_email(r.get("contact_email")),
                on_website=bool(r.get("on_website", False)),
                in_chronicle=bool(r.get("in_chronicle", False)),
            )
            self.ids.set("department_role", r.get("id"), role.pk)
            for h in r.get("former_holders") or []:
                name = (h.get("name") or "").strip()[:200]
                start = parse_date(h.get("valid_from"))
                if name and start:
                    RoleAssignment.all_objects.create(
                        organization=club,
                        role=role,
                        name=name,
                        name_public=bool(h.get("name_public", False)),
                        valid_from=start,
                        valid_until=parse_date(h.get("valid_until")),
                    )
        return dept

    def create_membership(self, club: Organization, scope: Organization, m: dict):
        person_id = self.ids.get("person", m["person"])
        membership = Membership.objects.create(
            organization=club,
            scope=scope,
            person_id=person_id,
            club_number=m.get("club_number") or "",
            pays_fee_self=bool(m.get("pays_fee_self")),
            info_opt_out_at=parse_datetime(m.get("info_opt_out_at")),
            photo_consent_at=parse_date(m.get("photo_consent_at")),
            photo_consent_source=m.get("photo_consent_source") or "",
            purged_at=parse_datetime(m.get("purged_at")),
            origin_ref=str(m.get("origin_ref") or "")[:40],
        )
        self.ids.set("membership", m.get("id"), membership.pk)
        self.save_contact(person_id, club, scope, m.get("contact"))
        MembershipPeriod.objects.bulk_create(
            MembershipPeriod(
                organization=club,
                membership=membership,
                entry_date=parse_date(p["entry_date"]),
                exit_date=parse_date(p.get("exit_date")),
                exit_reason=p.get("exit_reason") or "",
                note=p.get("note") or "",
            )
            for p in m.get("periods") or []
        )
        MemberTypeAssignment.objects.bulk_create(
            MemberTypeAssignment(
                organization=club,
                membership=membership,
                member_type_id=self.ids.get("member_type", t["member_type"]),
                valid_from=parse_date(t["valid_from"]),
                valid_until=parse_date(t.get("valid_until")),
            )
            for t in m.get("types") or []
        )
        self.department_links(club, membership, m)
        photo = m.get("photo")
        if photo and self.files.has(photo.get("image")):
            obj = MemberPhoto(
                organization=club,
                membership=membership,
                status=MemberPhoto.Status.APPROVED,
                source=photo.get("source") or MemberPhoto.Source.BOARD,
                width=photo.get("width") or 0,
                height=photo.get("height") or 0,
            )
            self.save_photo(obj.image, photo["image"], FULL_SIZE)
            # Vorschau immer aus dem geprüften Bild neu rechnen
            self.save_photo(obj.thumbnail, photo["image"], THUMB_SIZE)
            obj.save()
        return membership

    def department_links(self, club: Organization, membership: Membership, m: dict) -> None:
        if getattr(self, "unit_id", None) is not None:
            # Untereinheit wird eigene Einheit: Zuordnung entfällt, Ämter bleiben
            RoleAssignment.objects.bulk_create(
                RoleAssignment(
                    organization=club,
                    role_id=self.ids.get("unit_role", h["role"]),
                    person_id=membership.person_id,
                    valid_from=parse_date(h["valid_from"]),
                    valid_until=parse_date(h.get("valid_until")),
                )
                for h in m.get("department_roles") or []
                if self.ids.get("unit_role", h["role"])
            )
            return
        DepartmentMembership.objects.bulk_create(
            DepartmentMembership(
                organization=club,
                membership=membership,
                department_id=self.ids.get("department", d["department"]),
                valid_from=parse_date(d["valid_from"]),
                valid_until=parse_date(d.get("valid_until")),
            )
            for d in m.get("departments") or []
        )
        DepartmentRoleHolder.objects.bulk_create(
            DepartmentRoleHolder(
                organization=club,
                membership=membership,
                role_id=self.ids.get("department_role", h["role"]),
                valid_from=parse_date(h["valid_from"]),
                valid_until=parse_date(h.get("valid_until")),
            )
            for h in m.get("department_roles") or []
        )

    def save_contact(self, person_id, club, scope, contact: dict | None) -> None:
        if not contact:
            return
        values = {f: contact.get(f) or "" for f in CONTACT_FIELDS}
        values["country"] = values["country"] or "Deutschland"
        if self.shared:
            if ContactDetails.objects.filter(person_id=person_id, organization=None).exists():
                return  # vorhandene gemeinsame Kontaktdaten bleiben
            ContactDetails.objects.create(
                scope=scope, person_id=person_id, organization=None, **values
            )
        else:
            ContactDetails.objects.update_or_create(
                person_id=person_id, organization=club, defaults={"scope": scope, **values}
            )

    # Ablauf

    def run_organization(self) -> Organization:
        data = self.doc["organization"]
        org = self.create_org(data, self.target, top=True)
        if org.type == Organization.Type.FEDERATION or self.by_platform:
            scope = org
        else:
            scope = self.target  # Verein im Dachverband
        self.create_persons(scope)
        self.fill_org(org, data, scope)
        self.save_field_values()
        self.result["renumbered"] = self.assign_federation_numbers(scope, self.reported_persons())
        self.board(org)
        self.couplings(data)
        return org

    def couplings(self, data: dict) -> None:
        """Verbund: Kopplungen aus der Datei neu anlegen (Umzug auf diese Instanz)."""
        from peering.moving import load_couplings

        def walk(item):
            if item.get("peering"):
                org = Organization.objects.get(pk=self.ids.get("organization", item.get("id")))
                orgs = {
                    c.get("id"): Organization.objects.filter(
                        pk=self.ids.get("organization", c.get("id"))
                    ).first()
                    for c in item.get("clubs") or []
                }
                self.result["couplings"] = self.result.get("couplings", 0) + load_couplings(
                    org,
                    item["peering"],
                    orgs,
                    self.result.setdefault("coupling_warnings", []).append,
                    lambda old: self.ids.get("membership", old),
                )
            for club in item.get("clubs") or []:
                walk(club)

        walk(data)

    def run_department(self) -> Department:
        club = self.target
        scope = club.federation or club
        data = self.doc["department"]
        dept = self.create_department(club, data, (self.options.get("name") or "").strip() or None)
        # Mitgliedsarten über den Namen zuordnen, fehlende anlegen
        existing = {t.name.lower(): t for t in MemberType.objects.filter(organization=club)}
        created_types = []
        for t in self.doc.get("member_types") or []:
            mt = existing.get((t.get("name") or "").lower())
            if mt is None:
                mt = MemberType.objects.create(
                    organization=club,
                    name=t["name"],
                    reported=bool(t.get("reported")),
                    active=bool(t.get("active")),
                    counts_for_duration=bool(t.get("counts_for_duration", True)),
                )
                existing[mt.name.lower()] = mt
                created_types.append(mt.name)
            self.ids.set("member_type", t.get("id"), mt.pk)
        self.result["created_member_types"] = created_types
        self.create_persons(scope)
        joined = 0
        for m in self.doc.get("memberships") or []:
            person_id = self.ids.get("person", m["person"])
            membership = Membership.objects.filter(organization=club, person_id=person_id).first()
            if membership is not None:
                self.department_links(club, membership, m)
                continue
            self.create_membership(club, scope, m)
            joined += 1
        self.result["new_members"] = joined
        if self.doc.get("tables"):
            self.result["table_rows"] = load_tables(
                self.doc["tables"],
                club,
                self.ids,
                self.files,
                self.user,
                allowed=DEPARTMENT_IMPORT_MODELS,
            )
        self.result["renumbered"] = self.assign_federation_numbers(scope, self.reported_persons())
        return dept

    def run_unit(self) -> Organization:
        """Untereinheit wird eigene Einheit mit eigenen Mitgliedern (Verbund, Schritt 8b).

        Mitgliedsnummern, Zeiträume, Arten, Rollen und Dateien bleiben. Jede Mitgliedschaft
        merkt sich ihre Kennung beim abgebenden Verein (``origin_ref``): Darüber ordnet der
        Verein später den Abgleich zu, ohne dass Personen doppelt entstehen."""
        data = self.doc["department"]
        src = self.doc.get("club") if isinstance(self.doc.get("club"), dict) else {}
        org = Organization(type=Organization.Type.CLUB, parent=self.target)
        for field in dump.DEPT_FIELDS:
            if field in data and field not in ("sort_order", "is_active", "date_precision"):
                setattr(org, field, org._meta.get_field(field).to_python(data[field]))
        for field, value in unit_address(self.doc, self.options).items():
            if value:
                setattr(org, field, value[: Organization._meta.get_field(field).max_length])
        precision = data.get("date_precision") or src.get("date_precision")
        if precision in dict(Organization._meta.get_field("date_precision").choices):
            org.date_precision = precision
        if self.options.get("name"):
            org.name = self.options["name"].strip()
        org.short_name = (org.short_name or "").strip()[:SHORT_NAME_MAX]
        org.is_active = True
        org.enabled_modules = list(DEFAULT_MODULES)
        org.federation_member_access = Organization.MemberAccess.NONE
        try:
            org.clean()
        except ValidationError as exc:
            raise ValidationError(f"{org.name}: {'; '.join(exc.messages)}") from exc
        org.save()
        if data.get("logo") and self.save_logo(org.logo, data["logo"]):
            org.save(update_fields=["logo"])
        load_imprint(org, data.get("imprint"))
        load_letterhead(org, data.get("letterhead"))
        # Rollen der Untereinheit werden Rollen der Einheit; Rechte nur, soweit es sie gibt.
        # Zugänge gehen nicht mit (Fachfrage 4), Inhaber bleiben als Ämter ohne Konto.
        allowed = set(codes_for(org.type))
        for r in data.get("roles") or []:
            role = Role.objects.create(
                organization=org,
                name=r["name"],
                permissions=sorted(set(r.get("permissions") or []) & allowed),
                position=r.get("position") or 0,
                on_letterhead=bool(r.get("on_letterhead", False)),
                contact_email=clean_email(r.get("contact_email")),
                on_website=bool(r.get("on_website", False)),
            )
            self.ids.set("unit_role", r.get("id"), role.pk)
        for t in self.doc.get("member_types") or []:
            mt = MemberType.objects.create(
                organization=org,
                name=t["name"],
                reported=bool(t.get("reported")),
                active=bool(t.get("active")),
                counts_for_duration=bool(t.get("counts_for_duration", True)),
                is_archived=bool(t.get("is_archived")),
                sort_order=t.get("sort_order") or 0,
            )
            self.ids.set("member_type", t.get("id"), mt.pk)
        self.create_persons(org)
        self.unit_id = data.get("id")
        for m in self.doc.get("memberships") or []:
            membership = self.create_membership(org, org, m)
            membership.origin_ref = str(m.get("id") or "")[:40]
            membership.save(update_fields=["origin_ref"])
        self.result["new_members"] = len(self.doc.get("memberships") or [])
        if self.doc.get("tables"):
            self.result["table_rows"] = load_tables(
                self.doc["tables"],
                org,
                self.ids,
                self.files,
                self.user,
                allowed=DEPARTMENT_IMPORT_MODELS,
            )
        if self.doc.get("workspace_tables"):
            self.result["table_rows"] = self.result.get("table_rows", 0) + load_tables(
                self.doc["workspace_tables"], org, self.ids, self.files, self.user
            )
        self.result["renumbered"] = self.assign_federation_numbers(org, self.reported_persons())
        self.board(org)
        return org

    def reported_persons(self) -> set[int]:
        result = set()
        for mt_id, m in self._membership_types():
            if MemberType.objects.filter(pk=mt_id, reported=True).exists():
                result.add(m)
        return result

    def _membership_types(self):
        seen = set()
        for membership in Membership.objects.filter(person_id__in=self.new_person_ids):
            for ta in membership.type_assignments.all():
                key = (ta.member_type_id, membership.person_id)
                if key not in seen:
                    seen.add(key)
                    yield key

    def board(self, org: Organization) -> None:
        """Optional: ersten Vorstand per E-Mail festlegen (wie beim Anlegen von Hand)."""
        email = (self.options.get("board_email") or "").strip().lower()
        if not email:
            return
        from .services import add_board

        add_board(org, email, self.invitations)


def run(job, user) -> dict:
    with rls_bypass():
        doc, files = open_file(job.file)
        preview = Checker(job, doc, files).check()
    if preview["error_count"]:
        raise ValidationError(preview["errors"])
    with transaction.atomic(), rls_bypass():
        loader = Loader(job, doc, files, preview, user)
        if preview["kind"] == "organization":
            created = loader.run_organization()
            loader.result["organization"] = {"id": created.pk, "name": created.name}
        elif preview["kind"] == "unit":
            created = loader.run_unit()
            loader.result["organization"] = {"id": created.pk, "name": created.name}
        else:
            created = loader.run_department()
            loader.result["department"] = {"id": created.pk, "name": created.name}
        invitations = list(loader.invitations)

        def send():
            from accounts.invitations import send_invitation

            for invited_user, org, role_name in invitations:
                send_invitation(invited_user, org, role_name)

        transaction.on_commit(send)
    loader.result["invited"] = len(invitations)
    if preview["kind"] == "unit":
        couple_spin_off(created, doc, user, loader.result)
    return loader.result


def couple_spin_off(org: Organization, doc: dict, user, result: dict) -> None:
    """Ausgliederung: mit dem Code aus der Datei gleich die Kopplung unter den Verein anfragen.

    Gelingt das nicht (Verbund hier aus, Verein nicht erreichbar), steht der Code weiter in
    der Datei; der Vorstand koppelt dann von Hand unter Einstellungen › Verbund."""
    spin = doc.get("spin_off") if isinstance(doc.get("spin_off"), dict) else None
    if not spin or not spin.get("code"):
        return
    from peering import packets, services
    from peering.models import Coupling

    result["spin_off"] = {"way": spin.get("way"), "cutoff": spin.get("cutoff")}
    try:
        probe = Coupling(direction=Coupling.Direction.PARENT, options={"upper": packets.CLUB})
        services.request_coupling(org, str(spin["code"]), packets.defaults(probe), user)
        result["spin_off"]["coupling"] = "requested"
    except ValidationError as exc:
        result["spin_off"]["coupling"] = "failed"
        result["spin_off"]["error"] = "; ".join(exc.messages)
