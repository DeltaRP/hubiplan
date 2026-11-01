from __future__ import annotations

import datetime

from django.utils import timezone
from django.utils.translation import gettext
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from organizations.models import Department, DepartmentRole
from organizations.terms import fill

from . import services
from .models import (
    DepartmentMembership,
    DepartmentRoleHolder,
    ExitReason,
    Gender,
    Membership,
    MembershipPeriod,
    MemberType,
    MemberTypeAssignment,
    Person,
    overlaps,
)

# Plausible Daten: Ein Tippfehler wie 9999 würde sonst Dauer und Jubiläen sprengen.
EARLIEST = datetime.date(1800, 1, 1)
YEARS_AHEAD = 10


def check_plausible(attrs: dict, *fields: str) -> None:
    latest = timezone.localdate().replace(month=12, day=31)
    latest = latest.replace(year=latest.year + YEARS_AHEAD)
    for name in fields:
        value = attrs.get(name)
        if value is not None and not EARLIEST <= value <= latest:
            raise serializers.ValidationError(
                {
                    name: gettext(
                        "Bitte ein Datum zwischen {EARLIEST:%Y} und {latest:%Y} angeben."
                    ).format(EARLIEST=EARLIEST, latest=latest)
                }
            )


class MemberTypeSerializer(serializers.ModelSerializer):
    in_use = serializers.SerializerMethodField()

    class Meta:
        model = MemberType
        fields = [
            "id",
            "name",
            "reported",
            "active",
            "counts_for_duration",
            "is_archived",
            "sort_order",
            "in_use",
        ]

    def get_in_use(self, obj) -> bool:
        from .type_usage import usages

        return bool(usages(obj))

    def validate_name(self, value: str) -> str:
        org = self.context["org"]
        qs = MemberType.objects.filter(organization=org, name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(gettext("Diese Mitgliedsart gibt es schon."))
        return value


class ContactSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=50)
    street = serializers.CharField(max_length=200)
    postal_code = serializers.CharField(max_length=10)
    city = serializers.CharField(max_length=100)
    country = serializers.CharField(required=False, max_length=100, default="Deutschland")


@extend_schema_field(OpenApiTypes.INT)
class OrgPrimaryKeyField(serializers.PrimaryKeyRelatedField):
    """Fremdschlüssel, eingeschränkt auf die aktive Organisation."""

    def get_queryset(self):
        org = self.context["org"]
        return self.queryset_model.objects.filter(organization=org)

    def __init__(self, model, **kwargs):
        self.queryset_model = model
        super().__init__(**kwargs)


class AdmitSerializer(ContactSerializer):
    """Aufnahme: neue Person oder Verknüpfung mit einer gefundenen (``person``)."""

    person = serializers.PrimaryKeyRelatedField(
        queryset=Person.objects.all(), required=False, allow_null=True
    )
    last_name = serializers.CharField(max_length=100, required=False)
    first_name = serializers.CharField(max_length=100, required=False)
    birth_date = serializers.DateField(required=False)
    gender = serializers.ChoiceField(choices=Gender.choices, required=False, allow_blank=True)
    club_number = serializers.CharField(max_length=30, required=False, allow_blank=True)
    member_type = OrgPrimaryKeyField(MemberType)
    entry_date = serializers.DateField()
    department_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )

    def validate(self, attrs):
        org = self.context["org"]
        check_plausible(attrs, "entry_date", "birth_date")
        if not attrs.get("person"):
            missing = [f for f in ("last_name", "first_name", "birth_date") if not attrs.get(f)]
            if missing:
                raise serializers.ValidationError({f: "Pflichtfeld." for f in missing})
        birth = attrs.get("birth_date") or getattr(attrs.get("person"), "birth_date", None)
        if birth and attrs["entry_date"] < birth:
            raise serializers.ValidationError(
                {"entry_date": gettext("Der Eintritt liegt vor der Geburt.")}
            )
        if attrs["member_type"].is_archived:
            raise serializers.ValidationError(
                {"member_type": gettext("Diese Art wird nicht mehr verwendet.")}
            )
        wanted = set(attrs.pop("department_ids"))
        deps = list(Department.objects.filter(organization=org, pk__in=wanted))
        if len(deps) != len(wanted):
            # Inzwischen gelöscht oder fremd: nicht still ohne Zuordnung aufnehmen
            raise serializers.ValidationError(
                {
                    "department_ids": fill(
                        "Die gewählte Zuordnung gibt es nicht mehr. Bitte {einen} neu wählen.", org
                    )
                }
            )
        if any(d.is_remote for d in deps):
            raise serializers.ValidationError({"department_ids": REMOTE_UNIT})
        if len(deps) > 1 and not org.allow_multiple_departments:
            raise serializers.ValidationError(
                {"department_ids": fill("Nur {ein} je Mitglied erlaubt.", org)}
            )
        attrs["departments"] = deps
        return attrs


class DuplicateSerializer(serializers.ModelSerializer):
    """Was der aufnehmende Verein über eine gefundene Person sehen darf."""

    member_number = serializers.SerializerMethodField()
    clubs = serializers.SerializerMethodField()
    already_member_here = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = [
            "id",
            "last_name",
            "first_name",
            "birth_date",
            "member_number",
            "clubs",
            "already_member_here",
        ]

    def get_member_number(self, obj) -> int | None:
        fm = getattr(obj, "federation", None)
        return fm.member_number if fm else None

    def get_clubs(self, obj) -> list[str] | None:
        # Vereinszugehörigkeiten nur, wenn die Plattform frühere Mitgliedschaften
        # für diesen Dachverband sichtbar schaltet.
        club = self.context["org"]
        federation = club.federation
        if federation is None or not federation.federation_show_former_memberships:
            return None
        from core.tenancy import rls_bypass

        with rls_bypass():
            return sorted(
                m.organization.display_name
                for m in Membership.objects.filter(person=obj, scope=federation)
                .exclude(organization=club)
                .select_related("organization")
            )

    def get_already_member_here(self, obj) -> bool:
        return Membership.objects.filter(organization=self.context["org"], person=obj).exists()


class PeriodSerializer(serializers.ModelSerializer):
    exit_reason_label = serializers.CharField(source="get_exit_reason_display", read_only=True)
    member_type = OrgPrimaryKeyField(
        MemberType,
        write_only=True,
        required=False,
        allow_null=True,
        help_text="Mitgliedsart in diesem (nachgetragenen) Zeitraum.",
    )

    class Meta:
        model = MembershipPeriod
        fields = [
            "id",
            "entry_date",
            "exit_date",
            "exit_reason",
            "exit_reason_label",
            "note",
            "member_type",
        ]

    def create(self, validated_data):
        from .services import ensure_federation_member

        member_type = validated_data.pop("member_type", None)
        period = super().create(validated_data)
        if member_type is not None:
            MemberTypeAssignment.objects.create(
                organization=period.organization,
                membership=period.membership,
                member_type=member_type,
                valid_from=period.entry_date,
                valid_until=period.exit_date,
            )
            # Erste gemeldete Zeit, auch wenn nachgetragen: Verbandsnummer wie bei der
            # Aufnahme vergeben (Audit 31.10. M31-04)
            if member_type.reported:
                ensure_federation_member(period.membership.person, period.membership.organization)
        return period

    def update(self, instance, validated_data):
        validated_data.pop("member_type", None)
        return super().update(instance, validated_data)

    def validate(self, attrs):
        membership: Membership = self.context["membership"]
        check_plausible(attrs, "entry_date", "exit_date")
        entry = attrs.get("entry_date", getattr(self.instance, "entry_date", None))
        exit_ = attrs.get("exit_date", getattr(self.instance, "exit_date", None))
        reason = attrs.get("exit_reason", getattr(self.instance, "exit_reason", ""))
        if self.instance is None and not exit_:
            raise serializers.ValidationError(
                {"exit_date": gettext("Nachgetragene Zeiträume brauchen ein Austrittsdatum.")}
            )
        if exit_ and exit_ < entry:
            raise serializers.ValidationError(
                {"exit_date": gettext("Der Austritt liegt vor dem Eintritt.")}
            )
        if entry < membership.person.birth_date:
            raise serializers.ValidationError(
                {"entry_date": gettext("Der Eintritt liegt vor der Geburt.")}
            )
        if exit_ and not reason:
            raise serializers.ValidationError(
                {"exit_reason": gettext("Bitte einen Grund angeben.")}
            )
        others = membership.periods.all()
        if self.instance:
            others = others.exclude(pk=self.instance.pk)
        for other in others:
            if overlaps(entry, exit_, other.entry_date, other.exit_date):
                raise serializers.ValidationError(
                    gettext("Der Zeitraum überschneidet sich mit einem anderen Zeitraum.")
                )
        member_type = attrs.get("member_type")
        if self.instance is None and member_type is not None:
            from .services import active_elsewhere_between

            if member_type.is_archived:
                raise serializers.ValidationError(
                    {"member_type": gettext("Diese Art wird nicht mehr verwendet.")}
                )
            # Nur eine aktive Mitgliedschaft je Dachverband, auch in nachgetragenen Zeiten
            # (Audit 31.10. M31-04)
            if member_type.active:
                other = active_elsewhere_between(
                    membership.person, membership.organization, entry, exit_
                )
                if other:
                    raise serializers.ValidationError(
                        {
                            "member_type": gettext(
                                "In diesem Zeitraum war die Person schon aktives Mitglied in "
                                "„{other}“. "
                                "Bitte eine nicht aktive Art wählen."
                            ).format(other=other)
                        }
                    )
        return attrs


class TypeAssignmentSerializer(serializers.ModelSerializer):
    member_type_name = serializers.CharField(source="member_type.name", read_only=True)
    active = serializers.BooleanField(source="member_type.active", read_only=True)
    reported = serializers.BooleanField(source="member_type.reported", read_only=True)

    class Meta:
        model = MemberTypeAssignment
        fields = [
            "id",
            "member_type",
            "member_type_name",
            "active",
            "reported",
            "valid_from",
            "valid_until",
        ]


# Ferne Untereinheit (Verbund, Schritt 8): ihre Mitglieder pflegt ihre eigene Instanz
REMOTE_UNIT = "Diese Einheit liegt auf einer anderen Instanz und pflegt ihre Mitglieder dort."


class DepartmentMembershipSerializer(serializers.ModelSerializer):
    department = OrgPrimaryKeyField(Department)
    department_name = serializers.CharField(source="department.display_name", read_only=True)

    class Meta:
        model = DepartmentMembership
        fields = ["id", "department", "department_name", "valid_from", "valid_until"]

    def validate(self, attrs):
        membership: Membership = self.context["membership"]
        org = self.context["org"]
        start = attrs.get("valid_from", getattr(self.instance, "valid_from", None))
        end = attrs.get("valid_until", getattr(self.instance, "valid_until", None))
        if end and start and end < start:
            raise serializers.ValidationError(
                {"valid_until": gettext("Das Ende liegt vor dem Beginn.")}
            )
        department = attrs.get("department", getattr(self.instance, "department", None))
        if department.is_remote:
            raise serializers.ValidationError({"department": REMOTE_UNIT})
        others = membership.department_memberships.all()
        if self.instance:
            others = others.exclude(pk=self.instance.pk)
        for other in others:
            if not overlaps(start, end, other.valid_from, other.valid_until):
                continue
            if other.department_id == department.pk:
                raise serializers.ValidationError(
                    fill("Im Zeitraum bereits Mitglied {dieses}.", org)
                )
            if not org.allow_multiple_departments:
                raise serializers.ValidationError(
                    fill("Ein Mitglied darf nur {einem} gleichzeitig angehören.", org)
                )
        return attrs


class DepartmentRoleHolderSerializer(serializers.ModelSerializer):
    role = OrgPrimaryKeyField(DepartmentRole)
    role_name = serializers.CharField(source="role.name", read_only=True)
    department_name = serializers.CharField(source="role.department.display_name", read_only=True)

    class Meta:
        model = DepartmentRoleHolder
        fields = ["id", "role", "role_name", "department_name", "valid_from", "valid_until"]

    def validate(self, attrs):
        start = attrs.get("valid_from", getattr(self.instance, "valid_from", None))
        end = attrs.get("valid_until", getattr(self.instance, "valid_until", None))
        if end and start and end < start:
            raise serializers.ValidationError(
                {"valid_until": gettext("Das Ende liegt vor dem Beginn.")}
            )
        return attrs


class MemberUpdateSerializer(serializers.Serializer):
    """Stammdaten ändern (Person + Kontakt + Vereinsnummer)."""

    last_name = serializers.CharField(max_length=100, required=False)
    first_name = serializers.CharField(max_length=100, required=False)
    birth_date = serializers.DateField(required=False)
    gender = serializers.ChoiceField(choices=Gender.choices, required=False, allow_blank=True)
    club_number = serializers.CharField(max_length=30, required=False, allow_blank=True)
    pays_fee_self = serializers.BooleanField(required=False)
    info_opt_out = serializers.BooleanField(required=False)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=50)
    street = serializers.CharField(max_length=200, required=False)
    postal_code = serializers.CharField(max_length=10, required=False)
    city = serializers.CharField(max_length=100, required=False)
    country = serializers.CharField(max_length=100, required=False)

    def validate_birth_date(self, value):
        # Dieselbe Prüfung wie bei der Aufnahme (Audit 31.10. M31-03)
        check_plausible({"birth_date": value}, "birth_date")
        if value > timezone.localdate():
            raise serializers.ValidationError(gettext("Das Geburtsdatum liegt in der Zukunft."))
        return value


def check_birth_before_entries(person, birth) -> None:
    """Kein Geburtsdatum nach einem schon gespeicherten Eintritt (Audit 31.10. M31-03)."""
    if birth is None:
        return
    first = (
        MembershipPeriod.objects.filter(membership__person=person)
        .order_by("entry_date")
        .values_list("entry_date", flat=True)
        .first()
    )
    if first is not None and birth > first:
        raise serializers.ValidationError(
            {
                "birth_date": gettext(
                    "Das Geburtsdatum liegt nach dem Eintritt am {first:%d.%m.%Y}."
                ).format(first=first)
            }
        )


def _remote_federation(membership: Membership) -> dict | None:
    """Dachverband auf einer anderen Instanz (Verbund, namentliche Meldung)."""
    from peering.register import number_for

    rm = number_for(membership)
    if rm is None:
        return None
    return {
        "name": rm.coupling.remote_unit.name,
        "is_member": membership.current_period() is not None,
        "member_number": rm.number,
        "entry_date": None,
        "entry_date_manual": False,
        "remote": True,
    }


def member_detail(membership: Membership, org) -> dict:
    """Mitgliedsakte als Daten (Reiter Stammdaten, Mitgliedschaft, Rollen)."""
    from access.models import RoleAssignment

    person = membership.person
    contact = services.contact_for(person, org)
    current = membership.current_period()
    current_type = membership.current_type()
    fed = services.federation_status(person, org)
    board_roles = RoleAssignment.objects.filter(organization=org, person=person).select_related(
        "role"
    )
    return {
        "id": membership.pk,
        "person_id": person.pk,
        "last_name": person.last_name,
        "first_name": person.first_name,
        "birth_date": person.birth_date,
        "birth_year_only": person.birth_year_only,
        "gender": person.gender,
        "club_number": membership.club_number,
        "pays_fee_self": membership.pays_fee_self,
        "info_opt_out_at": membership.info_opt_out_at,
        "managed_by": {
            "id": membership.managed_by_id,
            "name": membership.managed_by.remote_unit.name,
        }
        if membership.managed_by_id
        else None,
        "contact": ContactSerializer(contact).data if contact else None,
        "contact_shared": services.shared_contacts(),
        "status": "active" if current else "former",
        "current_type": TypeAssignmentSerializer(current_type).data if current_type else None,
        "periods": PeriodSerializer(membership.periods.all(), many=True).data,
        "type_history": TypeAssignmentSerializer(
            membership.type_assignments.select_related("member_type"), many=True
        ).data,
        "departments": DepartmentMembershipSerializer(
            membership.department_memberships.select_related("department"), many=True
        ).data,
        "department_roles": DepartmentRoleHolderSerializer(
            membership.department_roles.select_related("role__department").order_by(
                "valid_from", "pk"
            ),
            many=True,
        ).data,
        "honorary_titles": _honorary(person.pk, org),
        "board_roles": [
            {
                "id": a.pk,
                "role_name": a.role.name,
                "valid_from": a.valid_from,
                "valid_until": a.valid_until,
            }
            for a in board_roles
        ],
        "federation": (
            {
                "name": services.federation_of(org).name,
                "is_member": fed.is_member,
                "member_number": fed.member_number,
                "entry_date": fed.entry_date,
                "entry_date_manual": fed.entry_date_manual,
            }
            if fed
            else _remote_federation(membership)
        ),
        "exit_reasons": [{"value": v, "label": label} for v, label in ExitReason.choices],
        "duration": _duration(membership),
        "photo": _photo(membership, org),
        "photo_consent_at": membership.photo_consent_at,
        "photo_consent_source": membership.photo_consent_source,
        "other_memberships": _other_memberships(membership),
        "purged": bool(membership.purged_at),
        "purge_due": _purge_due(membership),
    }


def _purge_due(membership: Membership):
    from .workflows import purge_due_date

    return purge_due_date(membership)


def _duration(membership: Membership):
    from .duration import duration_info

    return duration_info(membership)


def _other_memberships(membership: Membership):
    """Mitgliedschaften in anderen Vereinen des Dachverbands – nur Verein, Eintritt
    und Austritt, und nur wenn die Plattform das für den Dachverband freigibt."""
    federation = membership.organization.federation
    if federation is None or not federation.federation_show_former_memberships:
        return None
    from core.tenancy import rls_bypass

    result = []
    with rls_bypass():
        others = (
            Membership.objects.filter(person_id=membership.person_id, scope=federation)
            .exclude(pk=membership.pk)
            .select_related("organization")
            .prefetch_related("periods")
        )
        for other in others:
            for p in other.periods.all():
                result.append(
                    {
                        "club": other.organization.display_name,
                        "entry_date": p.entry_date,
                        "exit_date": p.exit_date,
                    }
                )
    return sorted(result, key=lambda r: r["entry_date"])


def _photo(membership: Membership, org):
    from .photo_views import photo_info

    return photo_info(membership, org.pk)


def _honorary(person_id: int, org):
    from .honorary import awards_of

    return awards_of(person_id, org)
