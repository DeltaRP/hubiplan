from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from access.catalog import DEPARTMENT_CODES, MEMBERS_VIEW, SWITCHABLE_MODULES
from access.models import Role, RoleAssignment
from core.api_base import ModelCleanMixin

from . import theme
from .models import Department, DepartmentRole, Organization, PlatformSettings
from .terms import department_terms, fill

WEBSITE_MODULE = "website"


def current_members_q(prefix: str = "") -> Q:
    """Abteilungszugehörigkeiten, die heute gelten (``prefix`` z. B. „memberships__“)."""
    today = timezone.localdate()
    return Q(**{f"{prefix}valid_from__lte": today}) & (
        Q(**{f"{prefix}valid_until__isnull": True}) | Q(**{f"{prefix}valid_until__gte": today})
    )


def logo_url(obj) -> str | None:
    return obj.logo.url if obj.logo else None


def effective_contact(org: Organization) -> dict:
    """Kontaktdaten, wie sie nach außen gelten.

    Bei „von Rolle übernehmen“ kommen sie von der Person, die die Rolle gerade
    innehat: aus ihrer Mitgliedsakte, falls die Rolle damit verknüpft ist, sonst
    die E-Mail-Adresse des Benutzerkontos.
    """
    if org.contact_source == Organization.ContactSource.ROLE and org.contact_role_id:
        holder = (
            RoleAssignment.objects.active()
            .filter(role_id=org.contact_role_id)
            .select_related("user", "person")
            .order_by("valid_from")
            .first()
        )
        email, phone, name = "", "", None
        if holder and holder.user_id:
            name = holder.user.get_full_name() or holder.user.email
            email = holder.user.email
        if holder:
            if holder.person_id:
                from members.services import contact_for

                name = f"{holder.person.first_name} {holder.person.last_name}"
                contact = contact_for(holder.person, org)
                if contact:
                    email, phone = contact.email, contact.phone
        return {
            "source": "role",
            "role": org.contact_role.name,
            "holder": name,
            "email": email,
            "phone": phone,
            "website": org.website,
        }
    return {
        "source": "own",
        "role": None,
        "holder": None,
        "email": org.contact_email,
        "phone": org.contact_phone,
        "website": org.website,
    }


def whole_years(value) -> list[int]:
    """Jahreszahlen als ganze Zahlen; 25.9, true oder „abc“ werden abgelehnt."""
    if not isinstance(value, list | tuple):
        raise serializers.ValidationError("Bitte ganze Jahre angeben.")
    years = set()
    for v in value:
        if isinstance(v, bool):
            raise serializers.ValidationError("Bitte ganze Jahre angeben.")
        if isinstance(v, int):
            years.add(v)
        elif isinstance(v, float) and v.is_integer():
            years.add(int(v))
        elif isinstance(v, str) and v.strip().lstrip("-").isdigit():
            years.add(int(v.strip()))
        else:
            raise serializers.ValidationError("Bitte ganze Jahre angeben.")
    return sorted(years)


class KeepsMembersMixin:
    """Schalter „führt eigene Mitglieder“; die Art der Einheit folgt daraus."""

    def get_can_switch_members(self, obj) -> bool:
        from .kinds import can_switch_members

        return can_switch_members(obj)

    def switch_members(self, attrs, keeps) -> None:
        from .kinds import apply_keeps_members

        old_type = self.instance.type
        try:
            self._type_changed = apply_keeps_members(self.instance, keeps)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        self._old_type = old_type
        for field in KIND_FIELDS:
            attrs.setdefault(field, getattr(self.instance, field))

    def update(self, instance, validated_data):
        org = super().update(instance, validated_data)
        if getattr(self, "_type_changed", False):
            from .kinds import upgrade_full_roles

            upgrade_full_roles(org, self._old_type)
        return org


class OrganizationSerializer(KeepsMembersMixin, ModelCleanMixin, serializers.ModelSerializer):
    """Stammdaten einer Organisation, wie ihr Vorstand sie pflegt."""

    keeps_members = serializers.BooleanField(required=False)
    can_switch_members = serializers.SerializerMethodField()

    type_label = serializers.CharField(source="kind_label", read_only=True)
    parent_name = serializers.CharField(source="parent.name", read_only=True, default=None)
    display_name = serializers.CharField(read_only=True)
    logo_url = serializers.SerializerMethodField()
    contact_effective = serializers.SerializerMethodField()
    contact_role = serializers.PrimaryKeyRelatedField(
        queryset=Role.objects.all(), allow_null=True, required=False
    )

    class Meta:
        model = Organization
        fields = [
            "id",
            "type",
            "type_label",
            "parent_name",
            "name",
            "short_name",
            "display_name",
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
            "contact_role",
            "contact_email",
            "contact_phone",
            "website",
            "contact_effective",
            "department_label",
            "department_label_plural",
            "department_label_gender",
            "department_label_genitive",
            "department_terms",
            "allow_multiple_departments",
            "direct_members",
            "keeps_members",
            "can_switch_members",
            "photo_approval_required",
            "member_portal_enabled",
            "department_access_enabled",
            "contact_changes_need_approval",
            "jubilee_years",
            "unit_jubilee_years",
            "federation_duration_rule",
            "date_precision",
            "fiscal_start_month",
            "fiscal_start_day",
            "fiscal_label",
            "logo_url",
            "imprint_key",
        ]
        read_only_fields = ["id", "type"]

    fiscal_label = serializers.SerializerMethodField()
    imprint_key = serializers.SerializerMethodField()

    def get_imprint_key(self, obj) -> str:
        from .imprint import ensure

        return ensure(obj).public_key

    department_terms = serializers.SerializerMethodField()

    def get_department_terms(self, obj) -> dict:
        return department_terms(obj)

    def get_logo_url(self, obj) -> str | None:
        return logo_url(obj)

    def get_contact_effective(self, obj) -> dict:
        return effective_contact(obj)

    def get_fiscal_label(self, obj) -> str:
        """Bezeichnung des laufenden Geschäftsjahres, z. B. „2025/26“."""
        return obj.fiscal_label(obj.fiscal_year_of(timezone.localdate()))

    def validate(self, attrs):
        org = self.instance
        keeps = attrs.pop("keeps_members", None)
        if org is not None and keeps is not None:
            self.switch_members(attrs, keeps)
        if org is not None and (
            attrs.get("fiscal_start_month", org.fiscal_start_month) != org.fiscal_start_month
            or attrs.get("fiscal_start_day", org.fiscal_start_day) != org.fiscal_start_day
        ):
            from finance.models import Booking

            if Booking.objects.filter(organization=org).exists():
                raise serializers.ValidationError(
                    {
                        "fiscal_start_month": "Es gibt schon Buchungen in der Kasse. Das "
                        "Geschäftsjahr lässt sich dann nicht mehr ändern."
                    }
                )
        return super().validate(attrs)

    def validate_direct_members(self, value):
        org = self.instance
        if org is None:
            return value
        if value and org.type != Organization.Type.FEDERATION:
            raise serializers.ValidationError(
                "Eigene Mitglieder neben denen darunter gibt es nur in der obersten Einheit."
            )
        if not value and org.direct_members:
            from members.models import Membership

            if Membership.objects.filter(organization=org).exists():
                raise serializers.ValidationError(
                    "Es gibt schon eigene Mitglieder. Bitte diese zuerst entfernen."
                )
        return value

    def validate_jubilee_years(self, value):
        years = whole_years(value)
        if any(y < 1 or y > 100 for y in years):
            raise serializers.ValidationError("Jubiläen zwischen 1 und 100 Jahren.")
        return years

    def validate_unit_jubilee_years(self, value):
        years = whole_years(value)
        if any(y < 1 or y > 1000 for y in years):
            raise serializers.ValidationError("Jubiläen zwischen 1 und 1000 Jahren.")
        return years

    def validate_contact_role(self, role):
        if role and self.instance and role.organization_id != self.instance.pk:
            raise serializers.ValidationError("Die Rolle gehört nicht zu dieser Organisation.")
        return role


def clean_primary(value: str) -> str:
    if value:
        theme.validate_hex_color(value)
        problems = theme.check_primary(value.lower())
        if problems:
            raise serializers.ValidationError(problems)
    return value.lower()


def clean_extra(value) -> list:
    from django.core.exceptions import ValidationError as DjangoValidationError

    try:
        return theme.clean_extra_colors(value)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(exc.messages) from exc


def clean_accent(value: str) -> str:
    if value:
        theme.validate_hex_color(value)
        problems = theme.check_accent(value.lower())
        if problems:
            raise serializers.ValidationError(problems)
    return value.lower()


class ThemeSerializer(serializers.ModelSerializer):
    """Eigene Farben einer Organisation; leer = erben. Mit Lesbarkeitsprüfung."""

    effective = serializers.SerializerMethodField()
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            "primary_color",
            "accent_color",
            "primary_color_name",
            "accent_color_name",
            "extra_colors",
            "logo_url",
            "effective",
        ]

    def get_logo_url(self, obj) -> str | None:
        return logo_url(obj)

    def get_effective(self, obj) -> dict:
        return theme.effective_theme(obj.ancestors())

    def validate_primary_color(self, value: str) -> str:
        return clean_primary(value)

    def validate_accent_color(self, value: str) -> str:
        return clean_accent(value)

    def validate_extra_colors(self, value) -> list:
        return clean_extra(value)


class HomepageImageSerializer(serializers.Serializer):
    """Eigenes Vorschaubild der Homepage; wird geprüft und als JPEG neu geschrieben."""

    image = serializers.ImageField()

    def validate_image(self, file):
        from django.core.files.base import ContentFile

        from .homepage_preview import clean_preview
        from .models import MAX_LOGO_BYTES

        if file.size > MAX_LOGO_BYTES * 2:
            raise serializers.ValidationError("Das Bild darf höchstens 4 MB groß sein.")
        file.seek(0)
        try:
            data = clean_preview(file.read())
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return ContentFile(data, name="vorschau.jpg")


class LogoSerializer(serializers.Serializer):
    logo = serializers.ImageField()
    # Weißen Hintergrund vom Rand her durchsichtig machen (Ralf 2026-10-30)
    remove_background = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        from django.core.exceptions import ValidationError as DjangoValidationError
        from django.core.files.base import ContentFile

        from core.filecheck import clean_logo

        file = attrs["logo"]
        file.seek(0)
        try:
            data = clean_logo(file.read(), remove_background=attrs["remove_background"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"logo": exc.messages}) from exc
        attrs["logo"] = ContentFile(data, name="logo.png")
        return attrs

    def validate_logo(self, file):
        from .models import MAX_LOGO_BYTES

        if file.size > MAX_LOGO_BYTES:
            raise serializers.ValidationError("Das Logo darf höchstens 2 MB groß sein.")
        return file


def clean_department_permissions(value) -> list[str]:
    unknown = sorted(set(value) - DEPARTMENT_CODES)
    if unknown:
        raise serializers.ValidationError(f"Unbekannte Berechtigungen: {', '.join(unknown)}")
    return sorted(set(value))


class DepartmentRoleSerializer(serializers.ModelSerializer):
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all())
    permissions = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True
    )
    holders = serializers.SerializerMethodField()

    class Meta:
        model = DepartmentRole
        fields = [
            "id",
            "department",
            "name",
            "position",
            "permissions",
            "on_letterhead",
            "contact_email",
            "on_website",
            "holders",
        ]
        extra_kwargs = {"position": {"required": False}}

    def get_holders(self, obj) -> list[dict]:
        """Aktuelle Inhaber (nur zur Information, nur mit Recht auf die Mitgliederliste)."""
        view = self.context.get("view")
        if MEMBERS_VIEW not in getattr(view, "org_permissions", set()):
            return []
        on = timezone.localdate()
        return [
            {
                "id": h.pk,
                "membership": h.membership_id,
                "name": f"{h.membership.person.first_name} {h.membership.person.last_name}",
                "valid_from": h.valid_from,
            }
            for h in sorted(obj.holders.all(), key=lambda h: (h.valid_from, h.pk))
            if h.valid_from <= on and (h.valid_until is None or h.valid_until >= on)
        ]

    def validate_permissions(self, value):
        return clean_department_permissions(value)

    def validate_department(self, department):
        org = self.context["org"]
        if department.organization_id != org.pk:
            raise serializers.ValidationError(fill("Unbekannt{adj} {sg}.", org))
        return department


class DepartmentSerializer(ModelCleanMixin, serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    logo_url = serializers.SerializerMethodField()
    roles = DepartmentRoleSerializer(many=True, read_only=True, source="unit_roles")
    effective_theme = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()
    # Übergeordnete Untereinheit; leer heißt direkt unter der Einheit
    parent_unit = serializers.IntegerField(required=False, allow_null=True)
    depth = serializers.SerializerMethodField()
    path = serializers.SerializerMethodField()
    child_terms = serializers.SerializerMethodField()
    # Eigene Webseite (nur mit eigenem Arbeitsbereich; die Einheit selbst braucht das Modul)
    own_website = serializers.BooleanField(required=False)
    # Homepage der Untereinheit; ohne „https://“ eingegeben wird es ergänzt
    website = serializers.CharField(required=False, allow_blank=True, max_length=200)
    # Vorschaubild der Homepage (von dort geholt oder selbst hochgeladen)
    website_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = [
            "id",
            "parent_unit",
            "depth",
            "path",
            "name",
            "short_name",
            "display_name",
            "founding_year",
            "website",
            "website_on_site",
            "website_image_url",
            "website_image_custom",
            "sort_order",
            "is_active",
            "date_precision",
            "fiscal_start_month",
            "fiscal_start_day",
            "primary_color",
            "accent_color",
            "primary_color_name",
            "accent_color_name",
            "extra_colors",
            "logo_url",
            "roles",
            "effective_theme",
            "member_count",
            "label",
            "label_plural",
            "label_gender",
            "department_label",
            "department_label_plural",
            "department_label_gender",
            "department_label_genitive",
            "child_terms",
            "own_workspace",
            "own_website",
            "self_managed",
            "fee_exempt",
            "is_remote",
        ]
        read_only_fields = [
            "label",
            "label_plural",
            "label_gender",
            "is_remote",
            "website_image_custom",
        ]
        # Gründungsjahr ist bei Untereinheiten freiwillig (leer = null)
        extra_kwargs = {"founding_year": {"required": False, "allow_null": True}}

    def tree(self):
        tree = self.context.get("tree")
        if tree is None:
            from .tree import UnitTree

            tree = self.context["tree"] = UnitTree.of(self.context["org"].pk)
        return tree

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["parent_unit"] = (
            None if instance.parent_id == instance.organization_id else instance.parent_id
        )
        data["own_website"] = WEBSITE_MODULE in (instance.enabled_modules or [])
        return data

    def get_depth(self, obj) -> int:
        return self.tree().depth(obj.pk)

    def get_website_image_url(self, obj) -> str | None:
        return obj.website_image.url if obj.website_image else None

    def validate_website(self, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if not value.lower().startswith(("https://", "http://")):
            value = f"https://{value}"
        try:
            URLValidator(schemes=["http", "https"])(value)
        except DjangoValidationError:
            raise serializers.ValidationError(
                "Bitte eine gültige Adresse angeben, z. B. https://www.beispiel.de"
            ) from None
        return value

    def get_path(self, obj) -> str:
        return self.tree().path(obj.pk) or obj.name

    def get_child_terms(self, obj) -> dict:
        return department_terms(obj)

    def validate(self, attrs):
        org = self.context["org"]
        if "parent_unit" in attrs:
            parent_unit = attrs.pop("parent_unit")
            attrs["parent_id"] = parent_unit or org.pk
        parent_id = attrs.get("parent_id") or (self.instance.parent_id if self.instance else org.pk)
        probe = Department(organization_id=org.pk, parent_id=parent_id)
        if self.instance:
            probe.pk = self.instance.pk
        error = probe.parent_error()
        if error:
            raise serializers.ValidationError({"parent_unit": error})
        name = attrs.get("name") or (self.instance.name if self.instance else "")
        siblings = Department.objects.filter(parent_id=parent_id, name__iexact=name)
        if self.instance:
            siblings = siblings.exclude(pk=self.instance.pk)
        if name and siblings.exists():
            raise serializers.ValidationError({"name": "Diesen Namen gibt es hier schon."})
        self._validate_self_managed(attrs)
        self._validate_own_website(attrs, org)
        return super().validate(attrs)

    def _validate_self_managed(self, attrs) -> None:
        """Ein eigener Arbeitsbereich hat Zugänge: nur bei selbst verwalteten Einheiten."""
        managed = attrs.get("self_managed", self.instance.self_managed if self.instance else False)
        workspace = attrs.get(
            "own_workspace", self.instance.own_workspace if self.instance else False
        )
        if workspace and not managed:
            if "self_managed" in attrs:
                raise serializers.ValidationError(
                    {
                        "self_managed": "Mit eigenem Arbeitsbereich verwaltet sich die Einheit "
                        "selbst. Bitte zuerst den Arbeitsbereich ausschalten."
                    }
                )
            attrs["self_managed"] = True

    def _validate_own_website(self, attrs, org) -> None:
        """Schalter „eigene Webseite“ in die freigeschalteten Module übernehmen."""
        modules = set(self.instance.enabled_modules or []) if self.instance else set()
        has = WEBSITE_MODULE in modules
        wanted = attrs.pop("own_website", has)
        workspace = attrs.get(
            "own_workspace", self.instance.own_workspace if self.instance else False
        )
        if wanted and not workspace:
            if not has or "own_workspace" not in attrs:
                raise serializers.ValidationError(
                    {
                        "own_website": fill(
                            "Eine eigene Webseite braucht einen eigenen Arbeitsbereich "
                            "{gen}: Zugänge, mit denen sie gepflegt wird.",
                            org,
                        )
                    }
                )
            wanted = False  # ohne Arbeitsbereich auch keine Webseite
        if wanted and not has and WEBSITE_MODULE not in (org.enabled_modules or []):
            raise serializers.ValidationError(
                {"own_website": "Dafür muss hier das Modul „Webseite“ freigeschaltet sein."}
            )
        if wanted != has:
            modules = (modules | {WEBSITE_MODULE}) if wanted else (modules - {WEBSITE_MODULE})
            attrs["enabled_modules"] = sorted(modules)

    def get_logo_url(self, obj) -> str | None:
        return logo_url(obj)

    def get_effective_theme(self, obj) -> dict:
        return theme.effective_theme(obj.ancestors())

    def get_member_count(self, obj) -> int:
        """Heute zugeordnete Mitglieder (aus der Annotation der Liste, sonst gezählt)."""
        count = getattr(obj, "current_member_count", None)
        if count is None:
            count = obj.unit_memberships.filter(current_members_q()).count()
        return count

    def validate_primary_color(self, value: str) -> str:
        return clean_primary(value)

    def validate_accent_color(self, value: str) -> str:
        return clean_accent(value)

    def validate_extra_colors(self, value) -> list:
        return clean_extra(value)

    def validate_short_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            return value
        org = self.context["org"]
        qs = Department.objects.filter(organization=org).filter(
            Q(short_name__iexact=value) | Q(name__iexact=value)
        )
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                fill("Diesen Namen trägt schon {ein_anderer} {e_gen}.", org)
            )
        return value


# --- Plattformbereich ---


def _has_memberships(org: Organization) -> bool:
    from core.tenancy import rls_bypass
    from members.models import Membership

    with rls_bypass():
        return Membership.objects.filter(organization=org).exists()


class PlatformOrganizationSerializer(
    KeepsMembersMixin, ModelCleanMixin, serializers.ModelSerializer
):
    """Dachverbände und Vereine aus Sicht der Plattform-Administration."""

    type_label = serializers.CharField(source="kind_label", read_only=True)
    federation = serializers.PrimaryKeyRelatedField(
        source="parent",
        queryset=Organization.objects.filter(type=Organization.Type.FEDERATION),
        allow_null=True,
        required=False,
        help_text="Nur für Vereine: zugehöriger Dachverband (leer = direkt unter der Plattform).",
    )
    federation_name = serializers.SerializerMethodField()
    display_name = serializers.CharField(read_only=True)
    club_count = serializers.SerializerMethodField()
    logo_url = serializers.SerializerMethodField()
    # Die Art ergibt sich aus der Lage und dem Schalter „führt eigene Mitglieder“
    type = serializers.CharField(read_only=True)
    keeps_members = serializers.BooleanField(required=False)
    can_switch_members = serializers.SerializerMethodField()
    # Entscheidet die Organisation selbst in der Kasse, nicht die Plattform
    tax_areas_enabled = serializers.BooleanField(read_only=True)

    class Meta:
        model = Organization
        fields = [
            "id",
            "type",
            "type_label",
            "keeps_members",
            "can_switch_members",
            "federation",
            "federation_name",
            "name",
            "short_name",
            "display_name",
            "label",
            "label_plural",
            "label_gender",
            "label_genitive",
            "founding_year",
            "street",
            "postal_code",
            "city",
            "country",
            "contact_email",
            "contact_phone",
            "website",
            "federation_member_access",
            "federation_show_former_memberships",
            "enabled_modules",
            "tax_areas_enabled",
            "is_active",
            "is_remote",
            "club_count",
            "logo_url",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not (instance.parent and instance.parent.type == Organization.Type.FEDERATION):
            data["federation"] = None
        return data

    def get_federation_name(self, obj) -> str | None:
        if obj.parent and obj.parent.type == "federation":
            return obj.parent.display_name
        return None

    def get_club_count(self, obj) -> int:
        return obj.children.count() if obj.type == Organization.Type.FEDERATION else 0

    def get_logo_url(self, obj) -> str | None:
        return logo_url(obj)

    def validate_enabled_modules(self, value):
        unknown = sorted(set(value) - set(SWITCHABLE_MODULES))
        if unknown:
            raise serializers.ValidationError(f"Unbekannte Module: {', '.join(unknown)}")
        return sorted(set(value))

    def validate(self, attrs):
        from .kinds import type_for_new

        keeps = attrs.pop("keeps_members", None)
        if keeps is None and self.instance is None:
            # Ältere Aufrufe nennen noch die Art
            keeps = self.initial_data.get("type") != Organization.Type.FEDERATION
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        if self.instance is None:
            try:
                org_type = type_for_new(parent, keeps)
            except DjangoValidationError as exc:
                raise serializers.ValidationError(exc.message_dict) from exc
            attrs["type"] = org_type
        else:
            org_type = self.instance.type
            if keeps is not None:
                if "parent" in attrs and attrs["parent"] != self.instance.parent:
                    raise serializers.ValidationError(
                        {"keeps_members": "Bitte erst umhängen und danach den Schalter ändern."}
                    )
                self.switch_members(attrs, keeps)
                org_type = self.instance.type
        if (
            self.instance
            and org_type == Organization.Type.CLUB
            and "parent" in attrs
            and (attrs["parent"] or Organization.platform()).pk != self.instance.parent_id
            and _has_memberships(self.instance)
        ):
            raise serializers.ValidationError(
                {
                    "federation": fill(
                        "{e_Diese} hat schon Mitglieder. Mit Mitgliedern lässt sich {e_nom} "
                        "noch nicht umhängen; bitte über die Datenübernahme exportieren und "
                        "in der neuen übergeordneten Einheit einlesen.",
                        self.instance,
                    )
                }
            )
        if org_type == Organization.Type.FEDERATION:
            attrs["parent"] = Organization.platform()
        elif parent is None:
            attrs["parent"] = Organization.platform()
        return super().validate(attrs)


# Felder, die ``apply_keeps_members`` an der Einheit ändern kann
KIND_FIELDS = (
    "type",
    "direct_members",
    "label",
    "label_plural",
    "label_gender",
    "label_genitive",
    "department_label",
    "department_label_plural",
    "department_label_gender",
    "department_label_genitive",
)


class PlatformSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformSettings
        fields = [
            "person_data_mode",
            "deletion_period_months",
            "peering_enabled",
            "peering_allowed_hosts",
            "peering_login",
        ]


class FederationClubSerializer(ModelCleanMixin, serializers.ModelSerializer):
    """Vereine eines Dachverbands: Stammdaten, die der Dachverband pflegen darf."""

    display_name = serializers.CharField(read_only=True)
    logo_url = serializers.SerializerMethodField()
    # Baum darunter, nur zum Ansehen: Namen der Untereinheiten (keine Mitgliedsdaten)
    units = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "short_name",
            "display_name",
            "department_label_plural",
            "units",
            "founding_year",
            "street",
            "postal_code",
            "city",
            "country",
            "contact_email",
            "contact_phone",
            "website",
            "is_active",
            "is_remote",
            "logo_url",
        ]
        read_only_fields = ["department_label_plural", "is_remote"]
        extra_kwargs = {"founding_year": {"min_value": 800, "max_value": 2100}}

    def get_logo_url(self, obj) -> str | None:
        return logo_url(obj)

    def get_units(self, obj) -> list[dict]:
        from .tree import UnitTree

        tree = UnitTree.of(obj.pk)
        return [
            {"id": pk, "name": tree.path(pk), "depth": tree.depth(pk)}
            for pk in tree.ordered()
            if tree.nodes[pk].is_active
        ]
