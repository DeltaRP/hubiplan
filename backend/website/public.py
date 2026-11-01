"""Öffentliche Sicht einer Webseite: berechnet aus den HUBIplan-Daten genau das,
was veröffentlicht werden darf. Die Datenschutzregeln stehen nur hier.

Keine internen Nummern nach außen: Personen, Rollen und Untereinheiten haben
Kennungen, die aus dem Schlüssel der Webseite abgeleitet sind (HMAC).
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
from functools import cached_property

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.text import slugify

from access.models import Role, RoleAssignment
from members.models import (
    DepartmentRoleHolder,
    HonoraryTitle,
    HonoraryTitleAward,
    Membership,
    Person,
)
from members.photo_models import MemberPhoto
from organizations.models import Department, DepartmentRole, SocialLink

from . import content, services
from .content_models import GALLERY_INTERVAL, WebsiteImage, WebsiteText
from .models import PublicationConsent, Website

Category = PublicationConsent.Category


def unit_slug(name: str) -> str:
    base = name.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        base = base.replace(a, b)
    return slugify(base) or "einheit"


def format_name(first: str, last: str, fmt: str) -> str:
    first, last = (first or "").strip(), (last or "").strip()
    if fmt == Website.NameFormat.INITIAL and last:
        return f"{first} {last[0]}.".strip()
    return f"{first} {last}".strip()


class SiteView:
    """``org`` ist die Einheit mit der Webseite (Verein, Dachverband oder eine
    Untereinheit mit eigenem Arbeitsbereich), ``area`` die Einheit mit ihrem
    Datenbereich (Mitglieder, Termine, Untereinheiten)."""

    def __init__(self, website: Website, base_url: str = ""):
        self.site = website
        self.org = website.organization
        self.area = services.data_area(self.org)
        self.is_unit = self.area.pk != self.org.pk
        self.today = timezone.localdate()
        self.base = base_url.rstrip("/")

    # --- Kennungen ---

    def token(self, kind: str, pk: int) -> str:
        msg = f"{self.site.public_key}:{kind}:{pk}".encode()
        return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()[:20]

    def url(self, path: str) -> str:
        return f"{self.base}/api/public/site/v1/{self.site.public_key}/{path}"

    # --- Personen ---

    @cached_property
    def memberships(self) -> dict[int, Membership]:
        """Mitgliedschaften der Einheit je Person (für Einwilligungen).

        Auch bereinigte: Deren Widersprüche gelten weiter, denn Chronik und frühere
        Rollen nennen die Person noch (Audit 29.10. W-S02). Eine laufende
        Mitgliedschaft geht einer bereinigten vor."""
        rows = Membership.objects.filter(organization=self.area)
        result: dict[int, Membership] = {}
        for m in sorted(rows, key=lambda m: m.purged_at is None):
            result[m.person_id] = m
        return result

    @cached_property
    def consents(self) -> dict[int, set[str]]:
        entries = services.active_entries(m.pk for m in self.memberships.values())
        # Bereinigte Mitgliedschaft: Widersprüche gelten weiter, Einwilligungen nicht mehr
        for m in self.memberships.values():
            if m.purged_at and m.pk in entries:
                entries[m.pk] &= set(PublicationConsent.OBJECTION_CATEGORIES)
        return entries

    @cached_property
    def photos(self) -> set[int]:
        return set(
            MemberPhoto.objects.filter(
                membership__in=list(self.memberships.values()),
                status=MemberPhoto.Status.APPROVED,
                membership__photo_consent_at__isnull=False,
            ).values_list("membership_id", flat=True)
        )

    def allowed(self, membership: Membership | None, category: str) -> bool:
        active = self.consents.get(membership.pk, set()) if membership else set()
        return services.allowed(category, active)

    def person(
        self,
        person: Person | None,
        fallback_name: str = "",
        *,
        category: str = Category.NAME,
        details: bool = False,
        ordinal: int | None = None,
    ) -> dict | None:
        """Angaben zu einer Person oder None, wenn sie nicht erscheinen darf.

        ``ordinal``: Ordnungszahl eines Würdenträgers, steht hinter dem Vornamen.
        """
        membership = self.memberships.get(person.pk) if person else None
        if not self.allowed(membership, category):
            if (
                self.site.missing_consent == Website.MissingConsent.NN
                and category == Category.HONORS
            ):
                return {"name": "N. N.", "photo_url": None}
            return None
        from honors.numbering import roman, split_name

        first, last = split_name(person, fallback_name)
        if ordinal:
            first = f"{first} {roman(ordinal)}.".strip()
        name = format_name(first, last, self.site.name_format) if last else first
        if not name:
            return None
        data = {"name": name, "photo_url": None}
        if membership and membership.pk in self.photos and self.allowed(membership, Category.PHOTO):
            data["photo_url"] = self.url(f"photos/{self.token('photo', membership.pk)}/")
        if details and membership is not None:
            contact = self.contact(person)
            if contact and contact.email and self.allowed(membership, Category.EMAIL):
                data["email"] = contact.email
            if contact and contact.phone and self.allowed(membership, Category.PHONE):
                data["phone"] = contact.phone
        return data

    def photo_membership(self, token: str) -> Membership | None:
        """Mitgliedschaft zum Foto-Kennzeichen, ohne alle Mitglieder zu laden (GA-P02).

        Kandidaten sind nur Mitgliedschaften mit freigegebenem Foto; für den Treffer
        gelten dieselben Regeln wie bei ``memberships``/``consents``."""
        candidates = (
            Membership.objects.filter(
                organization=self.area,
                photo_consent_at__isnull=False,
                photos__status=MemberPhoto.Status.APPROVED,
            )
            .order_by()
            .values_list("pk", flat=True)
            .distinct()
        )
        hit = next(
            (pk for pk in candidates if hmac.compare_digest(self.token("photo", pk), token)),
            None,
        )
        if hit is None:
            return None
        m = Membership.objects.get(pk=hit)
        if m.purged_at and (
            Membership.objects.filter(
                organization=self.area, person_id=m.person_id, purged_at__isnull=True
            ).exists()
        ):
            return None  # die laufende Mitgliedschaft der Person gilt
        active = services.active_entries([m.pk]).get(m.pk, set())
        if m.purged_at:
            active &= set(PublicationConsent.OBJECTION_CATEGORIES)
        if services.allowed(Category.PHOTO, active) and services.allowed(Category.NAME, active):
            return m
        return None

    # --- Vorstand ---

    @cached_property
    def shared_contacts(self) -> bool:
        from members.services import shared_contacts

        return shared_contacts()

    def contact(self, person: Person | None):
        from members.services import contact_for

        return contact_for(person, self.area, self.shared_contacts) if person else None

    def own_roles(self):
        """Rollen der Einheit selbst: Zugänge und bei einer Untereinheit auch die
        Rollen, die sie im Datenbereich darüber hat (Inhaber aus der Mitgliederliste)."""
        q = Q(organization=self.org, department__isnull=True)
        if self.is_unit:
            q |= Q(department=self.org)
        return Role.all_objects.filter(q).order_by("position", "name")

    @staticmethod
    def holder_person(a: RoleAssignment) -> tuple[Person | None, str]:
        """Person einer Zuordnung und Ersatzname (Benutzerkonto ohne Akte)."""
        if a.membership_id:
            return a.membership.person, ""
        return a.person, a.user.get_full_name() if a.user_id else a.name

    @cached_property
    def role_assignments(self) -> dict[int, list[RoleAssignment]]:
        """Heute aktive Inhaber der Rollen auf der Webseite, in einer Abfrage (W-P01)."""
        result: dict[int, list[RoleAssignment]] = {}
        rows = (
            RoleAssignment.all_objects.active(self.today)
            .filter(role__in=self.own_roles().filter(on_website=True))
            .select_related("person", "user", "membership__person")
            .prefetch_related("person__contacts", "membership__person__contacts")
            .order_by("valid_from", "pk")
        )
        for a in rows:
            result.setdefault(a.role_id, []).append(a)
        return result

    @cached_property
    def unit_role_holders(self) -> dict[int, list[DepartmentRoleHolder]]:
        """Heute aktive Inhaber der Untereinheiten-Rollen auf der Webseite."""
        result: dict[int, list[DepartmentRoleHolder]] = {}
        rows = (
            DepartmentRoleHolder.objects.filter(role__on_website=True, valid_from__lte=self.today)
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=self.today))
            .filter(role__department__in=[u.pk for u in self.units])
            .select_related("membership__person")
            .prefetch_related("membership__person__contacts")
            .order_by("valid_from", "pk")
        )
        for h in rows:
            result.setdefault(h.role_id, []).append(h)
        return result

    def _role_entry(self, kind: str, role, holders: list[dict], email: str) -> dict | None:
        if not holders and not self.site.show_vacant:
            return None
        contactable = self.site.block_on("contact") and bool(self.recipient_emails(kind, role))
        return {
            "id": self.token(kind, role.pk),
            "name": role.name,
            "holders": holders,
            "vacant": not holders,
            "email": email or None,
            "contact_form": contactable,
        }

    @staticmethod
    def join_names(names: list[str]) -> str:
        """„A“, „A & B“, „A, B & C“."""
        return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} & {names[-1]}"

    def _grouped(self, rows: list[tuple[frozenset, dict]]) -> list[dict]:
        """Rollen mit denselben Inhabern zu einem Eintrag „Rolle 1, Rolle 2 & Rolle 3“.

        Reihenfolge nach der ersten Rolle; unbesetzte Rollen bleiben einzeln.
        """
        groups: dict[frozenset, list[dict]] = {}
        order: list[list[dict]] = []
        for key, item in rows:
            if not key:
                order.append([item])
                continue
            if key not in groups:
                groups[key] = []
                order.append(groups[key])
            groups[key].append(item)
        result = []
        for items in order:
            first = dict(items[0])
            first["id"] = self.recipient_id(first["id"])
            if len(items) > 1:
                first["name"] = self.join_names([i["name"] for i in items])
                first["email"] = next((i["email"] for i in items if i["email"]), None)
                target = next((i for i in items if i["contact_form"]), None)
                first["contact_form"] = target is not None
                if target:
                    first["id"] = self.recipient_id(target["id"])
            result.append(first)
        return result

    @staticmethod
    def _holder_key(person: Person | None, fallback: str):
        return ("p", person.pk) if person else ("n", fallback)

    def board(self) -> list[dict]:
        rows = []
        for role in self.own_roles().filter(on_website=True):
            holders, keys = [], set()
            for a in self.role_assignments.get(role.pk, []):
                person, fallback = self.holder_person(a)
                entry = self.person(person, fallback, details=True)
                if entry:
                    holders.append(entry)
                    keys.add(self._holder_key(person, fallback))
            item = self._role_entry("role", role, holders, role.contact_email)
            if item:
                rows.append((frozenset(keys), item))
        return self._grouped(rows)

    def chairs(self) -> list[dict]:
        """Ämter: Rollen mit „unter Ämter zeigen“ und alle ihre Inhaber, auch frühere."""
        result = []
        for role in self.own_roles().filter(in_chronicle=True):
            entries = []
            for a in role.assignments.select_related(
                "person", "user", "membership__person"
            ).order_by("valid_from"):
                if a.needs_name_consent:
                    continue
                person, fallback = self.holder_person(a)
                entry = self.person(person, fallback)
                if entry:
                    entries.append(
                        {
                            **entry,
                            "from": a.valid_from,
                            "until": a.valid_until,
                            "current": a.valid_until is None or a.valid_until >= self.today,
                        }
                    )
            if entries:
                result.append({"role": role.name, "holders": entries})
        return result

    def honorary(self) -> list[dict]:
        """Ehrungen mit „auf der Webseite zeigen“ und ihre aktuellen Inhaber."""
        result = []
        if self.is_unit:
            return result  # Ehrungen vergibt die Einheit mit dem Datenbereich
        for title in HonoraryTitle.objects.filter(
            organization=self.org, is_public=True, is_archived=False
        ):
            people = []
            awards = (
                HonoraryTitleAward.objects.filter(title=title, valid_from__lte=self.today)
                .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=self.today))
                .select_related("person")
            )
            # Ohne Datum der Verleihung: auf der Webseite zählt nur, wer die Ehrung trägt
            for award in awards:
                entry = self.person(award.person, category=Category.HONORS)
                if entry:
                    people.append(entry)
            if people:
                # Überschrift: bei mehreren Trägern in der Mehrzahl (Ralf 2026-10-31)
                heading = title.plural if len(people) > 1 else title.name
                result.append({"title": title.name, "heading": heading, "holders": people})
        return result

    # --- Würden und Chronik ---

    def _photo_ok(self, reign) -> bool:
        """Foto einer Regentschaft: alle verknüpften Mitglieder haben eingewilligt."""
        people = [reign.person] + [c.person for c in reign.companions.all()]
        for person in people:
            if person is None:
                continue
            membership = self.memberships.get(person.pk)
            if membership is None or not self.allowed(membership, Category.PHOTO):
                return False
        return True

    def _view_for(self, area) -> SiteView:
        """Sicht mit den Einwilligungen einer anderen Einheit (z. B. des Dachverbands,
        der Würden weitergibt); Kennungen und Fotos laufen über diese Webseite."""
        if area.pk == self.area.pk:
            return self
        view = SiteView(self.site, self.base)
        view.area = area
        view.is_unit = False
        view.__dict__["reign_photos"] = self.reign_photos
        # Mitgliederfotos liefert nur die eigene Sicht aus (photo_membership)
        view.__dict__["photos"] = set()
        return view

    def dignity_sources(self, unit: Department | None = None) -> list[tuple]:
        """(Abfrage der Würden, Sicht für die Einwilligungen, Name der vergebenden Einheit
        oder leer, Herkünfte oder None). Dazu, wenn eingeschaltet, die nach unten
        weitergegebenen Würden der Einheiten darüber (nur auf der Hauptseite, nicht auf
        Unterseiten); von ihnen nur die Träger, die aus dieser Einheit (oder einer
        Einheit darunter) kamen (Ralf 2026-10-31)."""
        from honors.models import Dignity
        from organizations.models import Organization
        from organizations.tree import UnitTree, subtree_ids

        main = unit is None
        if unit is None and self.is_unit:
            unit = self.org  # Webseite einer Untereinheit: ihre eigenen Würden
        public = Dignity.objects.filter(is_public=True)
        sources = [(public.filter(organization=self.area, unit=unit), self, "", None)]
        if not (main and self.site.include_parent_honors):
            return sources
        shared = public.filter(share_down=True, is_archived=False)
        if self.is_unit:
            above = UnitTree.of(self.area.pk).ancestors(self.org.pk)[1:]
            q = Q(unit__isnull=True) | Q(unit_id__in=above)
            mine = list(subtree_ids(self.org))
            sources.append((shared.filter(q, organization=self.area), self, self.area.name, mine))
        # Einheiten darüber sehen nur den Verein selbst als Herkunft, nicht seine Züge
        for parent in self.area.ancestors()[1:]:
            if parent.type == Organization.Type.PLATFORM or not parent.is_active:
                continue
            sources.append(
                (
                    shared.filter(organization=parent, unit=None),
                    self._view_for(parent),
                    parent.name,
                    [self.area.pk],
                )
            )
        return sources

    @staticmethod
    def _with_reigns(qs, origins):
        """Würden mit mindestens einer (passenden) Regentschaft, Anzahl in reign_count."""
        q = Q(reigns__origin_id__in=origins) if origins is not None else Q()
        return qs.annotate(reign_count=Count("reigns", filter=q)).filter(reign_count__gt=0)

    def dignity_on(self, dignity) -> bool:
        """Würde auf dieser Webseite eingeschaltet (Häkchen im Menü, Ralf 2026-10-31)?"""
        return self.site.block_on(f"dignity:{dignity.pk}")

    def honors(self, unit: Department | None = None) -> list[dict]:
        """Öffentliche Würden mit aktuellen Trägern und Chronik (neueste zuerst);
        im Menü ausgeschaltete Würden fehlen."""
        result = []
        for dignities, view, owner, origins in self.dignity_sources(unit):
            for dignity in dignities:
                if not self.dignity_on(dignity):
                    continue
                item = view._dignity_entry(dignity, self, origins)
                if item:
                    if owner:
                        item["owner"] = owner
                    result.append(item)
        return result

    def _dignity_entry(self, dignity, site: SiteView, origins=None) -> dict | None:
        """Eine Würde mit ihren Regentschaften; Einwilligungen aus dieser Sicht, Kennungen
        und Foto-Adressen von der Webseite ``site``. ``origins``: nur Träger aus diesen
        Einheiten (weitergegebene Würde); die Ordnungszahl zählt trotzdem über alle."""
        from honors.numbering import ordinals

        reigns = list(
            dignity.reigns.select_related("person", "photo").prefetch_related("companions__person")
        )
        reigns.sort(key=lambda r: (r.sort_year, r.valid_from or datetime.date.min))
        numbers = ordinals(reigns, per_reign=dignity.count_each_reign) if dignity.numbered else {}
        if origins is not None:
            reigns = [r for r in reigns if r.origin_id in origins]
        seen: dict[str, int] = {}
        entries = []
        for reign in reigns:
            who = f"p{reign.person_id}" if reign.person_id else f"n{reign.name.strip().lower()}"
            seen[who] = seen.get(who, 0) + 1
            holder = self.person(
                reign.person,
                reign.name,
                category=Category.HONORS,
                ordinal=numbers.get(reign.pk),
            )
            if holder is None:
                continue
            companions = []
            for c in reign.companions.all():
                entry = self.person(c.person, c.name, category=Category.HONORS)
                if entry:
                    companions.append({"label": c.label, **entry})
            photo = getattr(reign, "photo", None)
            photo_url = None
            if photo is not None and holder["name"] != "N. N." and self._photo_ok(reign):
                token = site.token("reignphoto", reign.pk)
                site.reign_photos[token] = photo
                photo_url = site.url(f"honors/photos/{token}/")
            entries.append(
                {
                    "year": reign.year,
                    "from": reign.valid_from,
                    "until": reign.valid_until,
                    "period": reign.period_text,
                    "holder": holder,
                    "companions": companions,
                    "note": reign.note,
                    "photo_url": photo_url,
                    "times": seen[who],
                    "_sort": reign.sort_year,
                    "_end": reign.end_year,
                    # Genauer Zeitraum, der heute gilt, auch mit Enddatum (Audit 31.10.
                    # M31-05); vorher zählte nur ein offenes Ende
                    "_open": reign.valid_from is not None
                    and reign.valid_from <= self.today
                    and (reign.valid_until is None or reign.valid_until >= self.today),
                }
            )
        if not entries:
            return None
        # Jahresangaben: der letzte bekannte Träger bis heute; ein schon für die Zukunft
        # eingetragenes Jahr verdrängt den laufenden nicht
        known = [e["_sort"] for e in entries if e["_sort"] <= self.today.year]
        latest = max(known) if known else None
        current = [e for e in entries if e["_open"] or (e["year"] and e["_sort"] == latest)]
        # Gibt es einen Träger im laufenden Jahr? Sonst zeigt die Webseite gleich
        # alle Träger statt des letzten und einer zugeklappten Chronik (Ralf 31.10.)
        this_year = self.today.year
        current_year = any(
            e["_open"] or (e["year"] and e["year"] <= this_year <= (e["_end"] or e["year"]))
            for e in current
        )
        for e in entries:
            e.pop("_sort")
            e.pop("_open")
            e.pop("_end")
        entries.reverse()
        return {
            "id": site.token("dignity", dignity.pk),
            "name": dignity.name,
            "name_plural": dignity.plural,
            "current": current,
            "current_year": current_year,
            "reigns": entries,
        }

    def honors_label(self) -> str:
        """Menü und Überschrift der Majestäten: bei nur einer Würde ihr Name
        (Mehrzahl, sobald es mehr als eine Regentschaft gibt), sonst „Majestäten“."""
        dignities = []
        for qs, _view, _owner, origins in self.dignity_sources():
            dignities += [
                d for d in self._with_reigns(qs, origins).order_by("pk") if self.dignity_on(d)
            ]
        if len(dignities) != 1:
            return "Majestäten"
        dignity = dignities[0]
        return dignity.plural if dignity.reign_count > 1 else dignity.name

    def honors_menu(self) -> dict:
        """Unterpunkte des Menüs „Würdenträger“: je Würde mit Regentschaften ihr Name
        (Mehrzahl ab zwei Regentschaften), dazu „Ehrungen“, wenn es Träger gibt."""
        dignities = []
        if self.site.block_on("honors"):
            for qs, _view, _owner, origins in self.dignity_sources():
                for d in self._with_reigns(qs, origins):
                    if not self.dignity_on(d):
                        continue
                    label = d.plural if d.reign_count > 1 else d.name
                    dignities.append({"id": self.token("dignity", d.pk), "label": label})
        honorary = self.honorary() if self.site.block_on("honorary") else []
        return {
            "label": "Würdenträger",
            "dignities": dignities,
            "honorary": bool(honorary),
            "honorary_label": (honorary[0]["heading"] if len(honorary) == 1 else "Ehrungen")
            if honorary
            else None,
        }

    @cached_property
    def reign_photos(self) -> dict:
        return {}

    def reign_photo(self, token: str):
        if not self.reign_photos:
            self.honors()
            for u in self.units:
                self.honors(u)
        for known, photo in self.reign_photos.items():
            if hmac.compare_digest(known, token):
                return photo
        return None

    # --- Untereinheiten ---

    @cached_property
    def units(self) -> list[Department]:
        mode = self.site.units_mode
        if mode == Website.Units.NONE or not self.site.block_on("units"):
            return []
        qs = services.units_below(self.org).filter(is_active=True)
        if mode == Website.Units.SELECTED:
            qs = qs.filter(pk__in=self.site.unit_ids or [])
        return services.in_tree_order(qs)

    @cached_property
    def unit_slugs(self) -> dict[int, str]:
        seen: dict[str, int] = {}
        result = {}
        for u in self.units:
            slug = unit_slug(u.short_name or u.name)
            n = seen.get(slug, 0) + 1
            seen[slug] = n
            result[u.pk] = slug if n == 1 else f"{slug}-{n}"
        return result

    def unit_by_slug(self, slug: str) -> Department | None:
        return next((u for u in self.units if self.unit_slugs[u.pk] == slug), None)

    @cached_property
    def units_with_events(self) -> set[int]:
        """Untereinheiten mit anstehenden öffentlichen Terminen (Auswahl „Termine für“)."""
        if not self.site.block_on("events") or not self.units:
            return set()
        from events.models import Event
        from events.recurrence import occurrences

        now = timezone.now()
        qs = Event.objects.filter(
            organization=self.area,
            department__in=self.units,
            visibility=Event.Visibility.PUBLIC,
        )
        return {
            o.event.department_id for o in occurrences(qs, now, now + datetime.timedelta(days=400))
        }

    def unit_summary(self, u: Department) -> dict:
        text = self.unit_text(u)
        parent = self.unit_slugs.get(u.parent_id) if u.parent_id != self.org.pk else None
        return {
            "slug": self.unit_slugs[u.pk],
            "name": u.name,
            "short_name": u.short_name,
            "founding_year": u.founding_year,
            "parent": parent,
            "has_events": u.pk in self.units_with_events,
            "logo_url": self.abs(u.logo.url) if u.logo else None,
            "image": self.image(text.published_image) if text else None,
        }

    @cached_property
    def unit_texts(self) -> dict[int, WebsiteText]:
        """Veröffentlichte Texte aller Untereinheiten mit einer Abfrage (GA-P01)."""
        result: dict[int, WebsiteText] = {}
        for text in (
            WebsiteText.objects.filter(website=self.site, kind=WebsiteText.Kind.UNIT)
            .exclude(published_at=None)
            .exclude(department=None)
            .select_related("published_image")
            .order_by("pk")
        ):
            result.setdefault(text.department_id, text)
        return result

    def unit_text(self, u: Department) -> WebsiteText | None:
        return self.unit_texts.get(u.pk)

    def unit_detail(self, u: Department) -> dict:
        text = self.unit_text(u)
        rows = []
        if self.site.block_on("board"):
            for role in DepartmentRole.objects.filter(department=u, on_website=True).order_by(
                "position", "name"
            ):
                holders, keys = [], set()
                for h in self.unit_role_holders.get(role.pk, []):
                    entry = self.person(h.membership.person, details=True)
                    if entry:
                        holders.append(entry)
                        keys.add(self._holder_key(h.membership.person, ""))
                item = self._role_entry("unitrole", role, holders, role.contact_email)
                if item:
                    rows.append((frozenset(keys), item))
        roles = self._grouped(rows)
        return {
            **self.unit_summary(u),
            "title": text.published_title if text else u.name,
            "text": content.public_body(text.published_body, self.site) if text else "",
            "gallery": self.gallery(text) if text else [],
            "gallery_interval": text.published_gallery_interval if text else GALLERY_INTERVAL,
            "roles": roles,
            "social": self.social(u) if self.site.block_on("social") else [],
            # Eigene Homepage der Untereinheit, nur wenn dort freigegeben
            "homepage": u.website if u.website and u.website_on_site else None,
            "homepage_image": self.abs(u.website_image.url)
            if u.website and u.website_on_site and u.website_image
            else None,
            "posts": self.posts_available(u.pk)
            if self.site.block_on("posts")
            else {"instagram": False, "facebook": False},
            "honors": self.honors(u) if self.site.block_on("honors") else [],
            "events_url": self.url(f"events/?einheit={self.unit_slugs[u.pk]}")
            if self.site.block_on("events")
            else None,
        }

    # --- Sonstiges ---

    def abs(self, url: str) -> str:
        return url if url.startswith("http") else f"{self.base}{url}"

    def social(self, owner) -> list[dict]:
        return [
            {"kind": s.kind, "label": s.get_kind_display(), "url": s.url, "display": s.display}
            for s in SocialLink.objects.filter(organization=owner)
        ]

    def image(self, image: WebsiteImage | None) -> dict | None:
        if image is None:
            return None
        return {
            "key": image.key,
            "url": self.url(f"images/{image.public_key}/"),
            "small_url": self.url(f"images/{image.public_key}/?size=small"),
            "width": image.width,
            "height": image.height,
            "caption": image.caption,
            # Ohne Alternativtext trägt die Bildunterschrift die Beschreibung, außer
            # das Bild ist ausdrücklich nur Schmuck (Barrierefreiheit W-06)
            "alt": image.alt_text or ("" if image.decorative else image.caption),
        }

    # --- Social-Media-Beiträge (lokal gespeichert, nie von Meta ausgeliefert) ---

    @cached_property
    def social_feeds(self) -> list:
        from .social_models import SocialFeed

        return [
            f
            for f in SocialFeed.objects.filter(website=self.site)
            if f.department_id is None or f.department_id in self.unit_slugs
        ]

    def posts_available(self, department_id: int | None = None) -> dict[str, bool]:
        """Welche Kanäle Beiträge haben (Info für Menü und Startseiten-Bausteine)."""
        from .social_models import SocialPost

        result = {}
        for kind in ("instagram", "facebook"):
            feeds = [
                f for f in self.social_feeds if f.kind == kind and f.department_id == department_id
            ]
            result[kind] = SocialPost.objects.filter(
                feed__in=feeds, state=SocialPost.State.VISIBLE
            ).exists()
        return result

    def posts(self, kind: str | None, department_id: int | None, limit: int) -> list[dict]:
        from .social_models import SocialPost

        feeds = [
            f
            for f in self.social_feeds
            if f.department_id == department_id and (kind is None or f.kind == kind)
        ]
        qs = (
            SocialPost.objects.filter(feed__in=feeds, state=SocialPost.State.VISIBLE)
            .select_related("feed")
            .prefetch_related("images")
            .order_by("-published_at", "-pk")[:limit]
        )
        return [self.post_entry(p) for p in qs]

    def post_entry(self, post) -> dict:
        return {
            "id": self.token("post", post.pk),
            "kind": post.feed.kind,
            "kind_label": "Instagram" if post.feed.kind == "instagram" else "Facebook",
            "account": post.feed.account_name,
            "media_type": post.media_type,
            "text": post.text,
            "published_at": post.published_at.isoformat(),
            "permalink": post.permalink if post.feed.show_link else None,
            "images": [
                {
                    "url": self.url(f"posts/images/{i.key}/"),
                    "small_url": self.url(f"posts/images/{i.key}/?size=small"),
                    "width": i.width,
                    "height": i.height,
                    "alt": i.alt_text,
                    "is_video": i.is_video,
                }
                for i in post.images.all()
            ],
        }

    def public_post_image(self, key: str):
        from .social_models import SocialPost, SocialPostImage

        image = (
            SocialPostImage.objects.filter(key=key, post__state=SocialPost.State.VISIBLE)
            .select_related("post")
            .first()
        )
        if image is None or image.post.feed_id not in {f.pk for f in self.social_feeds}:
            return None
        return image

    def published_texts(self):
        return WebsiteText.objects.filter(website=self.site).exclude(published_at=None)

    def public_image(self, key: str) -> WebsiteImage | None:
        image = WebsiteImage.objects.filter(website=self.site, key=key).first()
        if image is None and "-v" in key:
            # Adresse mit Fassung (``<key>-v3``); ältere Fassungen zeigen das aktuelle Bild
            base, _, version = key.rpartition("-v")
            if version.isdigit():
                image = WebsiteImage.objects.filter(website=self.site, key=base).first()
        if image is None:
            return None
        marker = f"bild:{key}"
        for t in self.published_texts():
            if (
                t.published_image_id == image.pk
                or marker in t.published_body
                or image.pk in (t.published_gallery or [])
            ):
                if t.kind != WebsiteText.Kind.UNIT or t.department_id in self.unit_slugs:
                    return image
        return None

    def menu(self) -> list[dict]:
        return [
            {"slug": t.slug, "title": t.published_title}
            for t in self.published_texts()
            .filter(kind=WebsiteText.Kind.PAGE, show_in_menu=True)
            .order_by("menu_position", "published_title")
        ]

    def page(self, slug: str) -> dict | None:
        t = (
            self.published_texts()
            .filter(kind=WebsiteText.Kind.PAGE, slug=slug)
            .select_related("published_image")
            .first()
        )
        if t is None:
            return None
        return {
            "slug": t.slug,
            "title": t.published_title,
            "text": content.public_body(t.published_body, self.site),
            "image": self.image(t.published_image),
            "updated_at": t.published_at,
        }

    def greeting(self) -> dict | None:
        t = (
            self.published_texts()
            .filter(kind=WebsiteText.Kind.GREETING)
            .select_related("published_image")
            .first()
        )
        if t is None:
            return None
        return {
            "title": t.published_title,
            "text": content.public_body(t.published_body, self.site),
            "image": self.image(t.published_image),
            # Bilderkarussell (leer: nur das einzelne Bild wie bisher)
            "gallery": self.gallery(t),
            "gallery_interval": t.published_gallery_interval,
        }

    def gallery(self, t: WebsiteText) -> list[dict]:
        """Bilderkarussell eines veröffentlichten Textes, in seiner Reihenfolge."""
        ids = list(t.published_gallery or [])
        if not ids:
            return []
        by_id = {i.pk: i for i in WebsiteImage.objects.filter(website=self.site, pk__in=ids)}
        return [self.image(by_id[pk]) for pk in ids if pk in by_id]

    # --- Kontakt ---

    def recipient_emails(self, kind: str, role) -> list[str]:
        """Adressen, an die eine Formularnachricht für die Rolle geht."""
        if role.contact_email:
            return [role.contact_email]
        emails = []
        if kind == "role":
            for a in self.role_assignments.get(role.pk, []):
                contact = self.contact(self.holder_person(a)[0])
                email = (contact.email if contact else "") or (a.user.email if a.user_id else "")
                if email:
                    emails.append(email)
        else:
            for h in self.unit_role_holders.get(role.pk, []):
                contact = self.contact(h.membership.person)
                if contact and contact.email:
                    emails.append(contact.email)
        return sorted(set(emails))

    def general_email(self) -> str:
        from organizations.serializers import effective_contact

        return effective_contact(self.org).get("email") or ""

    def recipients(self) -> list[dict]:
        """Wählbare Empfänger im Kontaktformular."""
        result = []
        if self.general_email():
            result.append({"id": "allgemein", "name": f"{self.org.name} (allgemein)"})
        # Mehrere Rollen derselben Person(en) erscheinen als ein Empfänger
        found: list[tuple[str, tuple, str, str]] = []
        for role in self.own_roles().filter(on_website=True):
            emails = self.recipient_emails("role", role)
            if emails:
                found.append(("", tuple(emails), self.token("role", role.pk), role.name))
        for u in self.units:
            for role in DepartmentRole.objects.filter(department=u, on_website=True).order_by(
                "position", "name"
            ):
                emails = self.recipient_emails("unitrole", role)
                if emails:
                    found.append(
                        (u.name, tuple(emails), self.token("unitrole", role.pk), role.name)
                    )
        groups: dict[tuple, list] = {}
        for unit_name, emails, rid, name in found:
            groups.setdefault((unit_name, emails), [rid, []])[1].append(name)
        for (unit_name, _), (rid, names) in groups.items():
            label = self.join_names(names)
            result.append({"id": rid, "name": f"{label} ({unit_name})" if unit_name else label})
        self._recipient_alias = {
            r: groups[(unit_name, emails)][0] for unit_name, emails, r, _ in found
        }
        return result

    def recipient_id(self, rid: str) -> str:
        """Id des Empfängers im Kontaktformular, unter der die Rolle dort steht
        (zusammengefasste Rollen teilen sich die Id der ersten)."""
        if not hasattr(self, "_recipient_alias"):
            self.recipients()
        return self._recipient_alias.get(rid, rid)

    def resolve_recipient(self, rid: str) -> tuple[str, list[str]] | None:
        if rid == "allgemein":
            email = self.general_email()
            return (f"{self.org.name}", [email]) if email else None
        for role in self.own_roles().filter(on_website=True):
            if hmac.compare_digest(self.token("role", role.pk), rid):
                emails = self.recipient_emails("role", role)
                return (role.name, emails) if emails else None
        for u in self.units:
            for role in DepartmentRole.objects.filter(department=u, on_website=True):
                if hmac.compare_digest(self.token("unitrole", role.pk), rid):
                    emails = self.recipient_emails("unitrole", role)
                    return (f"{role.name} ({u.name})", emails) if emails else None
        return None
