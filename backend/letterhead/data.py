"""Welche Angaben in einer Briefvorlage stehen und wer sie erzeugen darf.

Der Briefbogen gehört einer Einheit. Untereinheiten übernehmen ihn von der
Einheit darüber; nur mit eigenem Arbeitsbereich dürfen sie einen eigenen pflegen.
Erzeugen darf eine Vorlage, wer in der Einheit eine aktive Vorstandsrolle hat
(oder eine Rolle in einer Untereinheit). Private Kontaktdaten kommen nur hinein,
wenn die Person sie selbst anhakt.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
from dataclasses import dataclass, field

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from access.models import RoleAssignment
from core.tenancy import rls_bypass
from organizations.models import Department, Imprint, Organization
from organizations.theme import effective_theme

from .models import Letterhead

# Rollen einer Untereinheit, die kürzer als so viele Tage bestehen, gelten als „neu“
NEW_FUNCTION_DAYS = 90

CONTACT_KEYS = ("unit", "role", "own_email", "own_phone", "own_address")


def default_tagline(org: Organization) -> str:
    """„gegründet …“, außer das Jahr steht schon im Namen (z. B. „… von 1920“)."""
    if org.type == Organization.Type.UNIT or not org.founding_year:
        return ""
    if str(org.founding_year) in org.name:
        return ""
    return f"gegründet {org.founding_year}"


def ensure(org: Organization) -> Letterhead:
    """Briefbogen der Einheit; legt ihn beim ersten Zugriff mit Standardwerten an."""
    letterhead = Letterhead.objects.filter(organization=org).first()
    if letterhead is not None:
        return letterhead
    try:
        with transaction.atomic():
            return Letterhead.objects.create(
                organization=org,
                mode=Letterhead.default_mode(org),
                tagline=default_tagline(org),
            )
    except IntegrityError:
        return Letterhead.objects.get(organization=org)


def may_have_own(org: Organization) -> bool:
    """Eigener Briefbogen: Dachverband und Verein immer, Untereinheiten nur mit Arbeitsbereich."""
    if org.type == Organization.Type.UNIT:
        return bool(org.own_workspace)
    return org.type in (Organization.Type.FEDERATION, Organization.Type.CLUB)


def owner_of(unit: Organization) -> tuple[Organization, Letterhead]:
    """Einheit, deren Briefbogen für ``unit`` gilt (sie selbst oder eine darüber)."""
    for node in unit.ancestors():
        if node.type == Organization.Type.PLATFORM:
            break
        letterhead = ensure(node)
        if node.type != Organization.Type.UNIT:
            return node, letterhead
        if may_have_own(node) and letterhead.mode == Letterhead.Mode.OWN:
            return node, letterhead
    return unit, ensure(unit)


# --- Daten der Einheit ---


def _person_name(person) -> str:
    return f"{person.first_name} {person.last_name}".strip()


def _iban(iban: str) -> str:
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))


def bank_account(owner: Organization, letterhead: Letterhead):
    """Konto für die Fußzeile: das gewählte, sonst das erste aktive Bankkonto mit IBAN."""
    from finance.models import Account

    with rls_bypass():
        accounts = Account.objects.filter(
            organization=owner, kind=Account.Kind.BANK, is_active=True
        ).exclude(iban="")
        if letterhead.account_id:
            chosen = accounts.filter(pk=letterhead.account_id).first()
            if chosen is not None:
                return chosen
        return accounts.order_by("position", "name").first()


def bank_accounts(owner: Organization) -> list[dict]:
    """Auswahl für die Einstellungen."""
    from finance.models import Account

    with rls_bypass():
        rows = Account.objects.filter(
            organization=owner, kind=Account.Kind.BANK, is_active=True
        ).exclude(iban="")
        return [
            {"id": a.pk, "name": a.name, "iban": _iban(a.iban), "bank": a.bank_name}
            for a in rows.order_by("position", "name")
        ]


def board(owner: Organization) -> list[dict]:
    """Vorstand für die Fußzeile: Vertretungsberechtigte, dann Rollen „auf dem Briefbogen“."""
    from members.models import DepartmentRoleHolder

    on = timezone.localdate()
    result: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(name: str, role: str) -> None:
        if name and (name, role) not in seen:
            seen.add((name, role))
            result.append({"name": name, "role": role})

    with rls_bypass():
        rows = (
            RoleAssignment.objects.active()
            .filter(organization=owner)
            .filter(Q(role__represents=True) | Q(role__on_letterhead=True))
            .select_related("role", "user", "person")
            .order_by("-role__represents", "role__name", "valid_from")
        )
        for row in rows:
            if row.person_id:
                name = _person_name(row.person)
            elif row.user_id:
                name = row.user.get_full_name()
            else:
                name = ""
            add(name, row.role.name)
        if owner.type == Organization.Type.UNIT:
            holders = (
                DepartmentRoleHolder.objects.filter(
                    role__department=owner, role__on_letterhead=True, valid_from__lte=on
                )
                .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
                .select_related("role", "membership__person")
                .order_by("role__position", "role__name")
            )
            for holder in holders:
                add(_person_name(holder.membership.person), holder.role.name)
    if not result:
        imprint = Imprint.objects.filter(organization=owner, mode=Imprint.Mode.OWN).first()
        if imprint is not None:
            for line in imprint.representatives.splitlines():
                if line.strip():
                    result.append({"name": line.strip(), "role": ""})
    return result


def register_lines(owner: Organization) -> list[str]:
    imprint = Imprint.objects.filter(organization=owner, mode=Imprint.Mode.OWN).first()
    if imprint is None:
        return []
    lines = []
    # Registerangaben nur bei eingetragenen Einheiten (Schalter im Impressum)
    parts = (imprint.register_court, imprint.register_number) if imprint.registered else ()
    register = ", ".join(p for p in parts if p)
    if register:
        lines.append(register)
    if imprint.vat_id:
        lines.append(f"USt-IdNr. {imprint.vat_id}")
    return lines


def logo_path(unit: Organization) -> str | None:
    for item in unit.ancestors():
        if item.logo:
            try:
                return item.logo.path
            except (ValueError, NotImplementedError):
                return None
    return None


@dataclass
class Sender:
    name: str = ""
    function: str = ""
    # (Bezeichnung, Wert) für den Informationsblock
    lines: list[tuple[str, str]] = field(default_factory=list)
    reply_address: list[str] = field(default_factory=list)
    signature: bytes | None = None


@dataclass
class LetterData:
    unit: Organization
    owner: Organization
    settings: Letterhead
    name: str
    tagline: str
    sub_line: str
    logo: str | None
    primary: str
    on_primary: str
    accent: str
    address: list[str]
    return_line: str
    contact: list[tuple[str, str]]
    bank: dict | None
    board: list[dict]
    register: list[str]
    social: list[tuple[str, str]]
    sender: Sender | None = None
    stand: datetime.date = field(default_factory=timezone.localdate)

    @property
    def form(self) -> str:
        return self.settings.form

    @property
    def font(self) -> str:
        return self.settings.font


# Rücksendeangabe passt nur einzeilig über das Anschriftfeld (85 mm, 6,5 pt)
RETURN_LINE_MAX = 80


def return_line(owner: Organization, address: list[str]) -> str:
    """Rücksendeangabe; bei langem Namen mit dem Kurznamen."""
    line = " · ".join(address)
    if len(line) > RETURN_LINE_MAX and owner.short_name:
        line = " · ".join([owner.short_name, *address[1:]])
    return line


def letter_data(
    unit: Organization, with_logo: bool = True, sender: Sender | None = None
) -> LetterData:
    """Alle Angaben der Vorlage für ``unit`` (ohne persönlichen Teil, wenn ``sender`` leer)."""
    from organizations.serializers import effective_contact

    owner, lh = owner_of(unit)
    theme = effective_theme(unit.ancestors())
    street_city = f"{owner.postal_code} {owner.city}".strip()
    address = [p for p in (owner.name, owner.street, street_city) if p]
    contact: list[tuple[str, str]] = []
    with rls_bypass():
        eff = effective_contact(owner)
    if lh.show_phone and eff["phone"]:
        contact.append(("Telefon", eff["phone"]))
    if lh.show_email and eff["email"]:
        contact.append(("E-Mail", eff["email"]))
    if lh.show_website and owner.website:
        contact.append(("Web", owner.website.split("://", 1)[-1].rstrip("/")))
    bank = None
    if lh.show_bank:
        account = bank_account(owner, lh)
        if account is not None:
            bank = {
                "holder": owner.name,
                "bank": account.bank_name,
                "iban": _iban(account.iban),
                "bic": account.bic,
            }
    social = []
    if lh.show_social:
        social = [(s.get_kind_display(), s.display) for s in owner.social_links.all()]
    show_logo = with_logo and lh.logo_position != Letterhead.LogoPosition.NONE
    return LetterData(
        unit=unit,
        owner=owner,
        settings=lh,
        name=owner.name,
        tagline=lh.tagline.strip(),
        sub_line=unit.name if unit.pk != owner.pk else "",
        logo=logo_path(unit) if show_logo else None,
        primary=theme["primary"],
        on_primary=theme["on_primary"],
        accent=theme["accent"],
        address=address,
        return_line=return_line(owner, address),
        contact=contact,
        bank=bank,
        board=board(owner) if lh.show_board else [],
        register=register_lines(owner) if lh.show_register else [],
        social=social,
        sender=sender,
    )


# --- Wer darf, mit welcher Funktion ---


@dataclass
class Function:
    key: str
    name: str
    contact_email: str
    since: datetime.date


@dataclass
class SenderContext:
    """Eine Einheit, für die eine Person Briefvorlagen erzeugen darf."""

    key: str
    org: Organization  # Einheit der Rolle
    area: Organization  # Datenbereich (für Mitgliedsakte und Untereinheiten)
    functions: list[Function]
    person_id: int | None = None

    def units(self) -> list[Organization]:
        """Einheiten, für die geschrieben werden kann: die eigene und ihre Untereinheiten."""
        result = [self.org]
        if self.org.type == Organization.Type.CLUB:
            from organizations.tree import UnitTree

            tree = UnitTree.of(self.org.pk)
            ids = [i for i in tree.ordered() if tree.nodes[i].is_active]
            by_id = {d.pk: d for d in Department.objects.filter(pk__in=ids)}
            result += [by_id[i] for i in ids if i in by_id]
        elif self.org.type == Organization.Type.UNIT and self.key.startswith("dept:"):
            from organizations.tree import UnitTree

            tree = UnitTree.of(self.area.pk)
            ids = [i for i in tree.subtree(self.org.pk)[1:] if tree.nodes[i].is_active]
            by_id = {d.pk: d for d in Department.objects.filter(pk__in=ids)}
            result += [by_id[i] for i in ids if i in by_id]
        return result


def contexts_for(user) -> list[SenderContext]:
    from members.models import DepartmentRoleHolder, Membership
    from portal.services import accesses_of

    if not user.is_authenticated:
        return []
    on = timezone.localdate()
    result: dict[str, SenderContext] = {}
    with rls_bypass():
        rows = (
            RoleAssignment.objects.active()
            .filter(user=user, role__is_board=True, organization__is_active=True)
            .exclude(organization__type=Organization.Type.PLATFORM)
            .select_related("role", "organization", "organization__organization")
            .order_by("valid_from")
        )
        for row in rows:
            org = row.organization
            if org.type == Organization.Type.UNIT and not (
                org.own_workspace and org.organization and org.organization.is_active
            ):
                continue
            key = f"org:{org.pk}"
            ctx = result.get(key)
            if ctx is None:
                area = org.organization if org.type == Organization.Type.UNIT else org
                ctx = result[key] = SenderContext(key, org, area, [])
            if ctx.person_id is None and row.person_id:
                ctx.person_id = row.person_id
            if not any(f.key == f"role:{row.role_id}" for f in ctx.functions):
                ctx.functions.append(
                    Function(
                        f"role:{row.role_id}", row.role.name, row.role.contact_email, row.valid_from
                    )
                )
        for access in accesses_of(user):
            club = access.organization
            if club.type != Organization.Type.CLUB:
                continue
            membership = Membership.objects.filter(pk=access.membership_id).first()
            if membership is None or membership.current_period(on) is None:
                continue
            org_ctx = result.get(f"org:{club.pk}")
            if org_ctx is not None and org_ctx.person_id is None:
                org_ctx.person_id = membership.person_id
            holders = (
                DepartmentRoleHolder.objects.filter(
                    membership=membership, valid_from__lte=on, role__department__is_active=True
                )
                .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
                .select_related("role", "role__department")
                .order_by("valid_from")
            )
            for holder in holders:
                dept = holder.role.department
                key = f"dept:{dept.pk}"
                ctx = result.get(key)
                if ctx is None:
                    ctx = result[key] = SenderContext(key, dept, club, [], membership.person_id)
                fkey = f"drole:{holder.role_id}"
                if not any(f.key == fkey for f in ctx.functions):
                    ctx.functions.append(
                        Function(
                            fkey, holder.role.name, holder.role.contact_email, holder.valid_from
                        )
                    )
    for ctx in result.values():
        if len(ctx.functions) > 1:
            ctx.functions.insert(0, combined_function(ctx.functions))
    order = {Organization.Type.FEDERATION: 0, Organization.Type.CLUB: 1, Organization.Type.UNIT: 2}
    return sorted(result.values(), key=lambda c: (order.get(c.org.type, 9), c.org.name))


ALL_FUNCTIONS = "all"


def join_names(names: list[str]) -> str:
    """„A“, „A & B“, „A, B & C“."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} & {names[-1]}"


def combined_function(functions: list[Function]) -> Function:
    """Alle Funktionen einer Person in der Einheit zusammen, z. B. „Adjutant & 1. Kassierer“.

    Steht vorn und ist damit voreingestellt; die Funktionsadressen kommen alle mit.
    """
    emails = list(dict.fromkeys(f.contact_email for f in functions if f.contact_email))
    return Function(
        ALL_FUNCTIONS,
        join_names([f.name for f in functions]),
        ", ".join(emails),
        max(f.since for f in functions),
    )


def own_contact(user, ctx: SenderContext) -> dict:
    """Eigene Kontaktdaten aus der Mitgliedsakte (sonst E-Mail des Kontos)."""
    from members.models import Person
    from members.services import contact_for

    data = {"email": user.email, "phone": "", "address": []}
    if ctx.person_id is None:
        return data
    with rls_bypass():
        person = Person.objects.filter(pk=ctx.person_id).prefetch_related("contacts").first()
        if person is None:
            return data
        contact = contact_for(person, ctx.area)
    if contact is not None:
        data["email"] = contact.email or user.email
        data["phone"] = contact.phone
        city = f"{contact.postal_code} {contact.city}".strip()
        data["address"] = [p for p in (contact.street, city) if p]
    return data


def user_name(user, ctx: SenderContext) -> str:
    from members.models import Person

    if ctx.person_id is not None:
        with rls_bypass():
            person = Person.objects.filter(pk=ctx.person_id).first()
        if person is not None:
            return _person_name(person)
    return user.get_full_name() or user.email


def unit_contact(unit: Organization) -> dict:
    from organizations.serializers import effective_contact

    owner, _ = owner_of(unit)
    with rls_bypass():
        eff = effective_contact(owner)
    return {"email": eff["email"], "phone": eff["phone"]}


def build_sender(
    user,
    ctx: SenderContext,
    unit: Organization,
    function_key: str,
    function_text: str = "",
    title: str = "",
    contacts: list[str] | tuple[str, ...] = ("unit",),
    signature: bytes | None = None,
) -> Sender:
    function = next((f for f in ctx.functions if f.key == function_key), ctx.functions[0])
    name = user_name(user, ctx)
    if title.strip():
        name = f"{title.strip()} {name}"
    sender = Sender(name=name, function=function_text.strip() or function.name)
    phones: list[str] = []
    mails: list[str] = []
    if "unit" in contacts:
        uc = unit_contact(unit)
        phones.append(uc["phone"])
        mails.append(uc["email"])
    if "role" in contacts:
        mails += function.contact_email.split(", ")
    own = None
    if {"own_email", "own_phone", "own_address"} & set(contacts):
        own = own_contact(user, ctx)
    if own and "own_phone" in contacts:
        phones.append(own["phone"])
    if own and "own_email" in contacts:
        mails.append(own["email"])
    for value in dict.fromkeys(p for p in phones if p):
        sender.lines.append(("Telefon", value))
    for value in dict.fromkeys(m for m in mails if m):
        sender.lines.append(("E-Mail", value))
    if own and "own_address" in contacts and own["address"]:
        sender.reply_address = [name, *own["address"]]
    sender.signature = signature
    return sender


# --- Prüfwerte für „Vorlage veraltet“ ---

SECTIONS = {
    "name": "Name und Logo/Wappen",
    "address": "Anschrift",
    "contact": "Kontakt",
    "bank": "Bankverbindung",
    "board": "Vorstand",
    "register": "Registerangaben",
    "social": "Social Media",
    "design": "Farben, Schrift und Aufbau",
    "sender": "deine Angaben",
}


def _logo_stamp(path: str | None) -> str:
    if not path:
        return ""
    try:
        import os

        stat = os.stat(path)
        return f"{os.path.basename(path)}:{stat.st_size}"
    except OSError:
        return path


def section_values(data: LetterData) -> dict:
    lh = data.settings
    sender = data.sender
    return {
        "name": [data.name, data.tagline, data.sub_line, _logo_stamp(data.logo)],
        "address": data.address,
        "contact": data.contact,
        "bank": data.bank,
        "board": data.board,
        "register": data.register,
        "social": data.social,
        "design": [
            data.primary,
            data.accent,
            lh.font,
            lh.form,
            lh.logo_position,
            lh.salutation,
            lh.closing,
        ],
        "sender": (
            [sender.name, sender.function, sender.lines, sender.reply_address] if sender else []
        ),
    }


def checksums(data: LetterData) -> dict[str, str]:
    key = settings.SECRET_KEY.encode()
    result = {}
    for section, value in section_values(data).items():
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
        result[section] = hmac.new(key, raw, hashlib.sha256).hexdigest()[:24]
    return result


def changed_sections(old: dict, new: dict) -> list[str]:
    return [SECTIONS[k] for k in SECTIONS if k in old and old.get(k) != new.get(k)]
