from __future__ import annotations

from django.utils.translation import gettext
from rest_framework import serializers

from accounts.models import User

from .catalog import codes_for
from .models import Role, RoleAssignment


class RoleSerializer(serializers.ModelSerializer):
    assignment_count = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = [
            "id",
            "name",
            "description",
            "permissions",
            "is_board",
            "represents",
            "on_letterhead",
            "contact_email",
            "on_website",
            "position",
            "in_chronicle",
            "assignment_count",
        ]
        # Reihenfolge nur per Ziehen (…/roles/reorder/)
        read_only_fields = ["position"]

    def get_assignment_count(self, obj) -> int:
        return obj.assignments.active().count()

    def validate_permissions(self, value):
        org = self.context["org"]
        allowed = set(codes_for(org.type))
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise serializers.ValidationError(
                gettext("Für diese Organisation nicht erlaubt: {x}").format(x=", ".join(unknown))
            )
        return sorted(set(value))

    def validate_name(self, value: str) -> str:
        org = self.context["org"]
        qs = Role.objects.filter(organization=org, name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(gettext("Diese Rolle gibt es schon."))
        return value


class AssignmentSerializer(serializers.ModelSerializer):
    """Rollenzuordnung. Beim Anlegen per E-Mail; fehlt das Konto, wird es erzeugt."""

    email = serializers.EmailField(write_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True, default=None)
    user_name = serializers.SerializerMethodField()
    role = serializers.PrimaryKeyRelatedField(queryset=Role.objects.all())
    role_name = serializers.CharField(source="role.name", read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    member = serializers.IntegerField(
        write_only=True,
        required=False,
        allow_null=True,
        help_text="Mitgliedschaft (Mitgliedsakte) der Person, die die Rolle innehat.",
    )
    person_name = serializers.SerializerMethodField()
    member_record = serializers.SerializerMethodField()
    invited = serializers.SerializerMethodField()
    new_account = serializers.SerializerMethodField()
    has_mfa = serializers.SerializerMethodField()

    class Meta:
        model = RoleAssignment
        fields = [
            "id",
            "member",
            "person_name",
            "member_record",
            "email",
            "user_email",
            "user_name",
            "role",
            "role_name",
            "valid_from",
            "valid_until",
            "is_active",
            "invited",
            "new_account",
            "has_mfa",
        ]

    def get_fields(self):
        fields = super().get_fields()
        if self.instance is not None:
            # Beim Ändern sind Person und Rolle fest; nur der Zeitraum ändert sich.
            fields["email"].required = False
            fields["role"].read_only = True
        return fields

    def get_user_name(self, obj) -> str:
        return obj.user.get_full_name() if obj.user_id else ""

    def get_person_name(self, obj) -> str | None:
        return str(obj.person) if obj.person_id else None

    def get_member_record(self, obj) -> dict | None:
        """Mitgliedsakte der Person in dieser Einheit (für die Auswahl beim Bearbeiten)."""
        if not obj.person_id:
            return None
        from members.models import Membership

        membership = (
            Membership.objects.filter(organization=self.context["org"], person_id=obj.person_id)
            .order_by("-pk")
            .first()
        )
        if membership is None:
            return None
        return {
            "id": membership.pk,
            "first_name": obj.person.first_name,
            "last_name": obj.person.last_name,
        }

    def validate_member(self, value):
        if value is None:
            return None
        from members.models import Membership

        membership = (
            Membership.objects.filter(organization=self.context["org"], pk=value)
            .select_related("person")
            .first()
        )
        if membership is None:
            raise serializers.ValidationError(gettext("Unbekanntes Mitglied."))
        return membership.person

    def get_invited(self, obj) -> bool:
        return getattr(obj, "_invited", False)

    def get_has_mfa(self, obj) -> bool:
        from accounts.mfa_policy import has_mfa

        return has_mfa(obj.user)

    def get_new_account(self, obj) -> bool:
        return getattr(obj, "_new_account", False)

    def validate_role(self, role):
        if role.organization_id != self.context["org"].pk:
            raise serializers.ValidationError(gettext("Unbekannte Rolle."))
        return role

    def validate(self, attrs):
        start = attrs.get("valid_from", getattr(self.instance, "valid_from", None))
        end = attrs.get("valid_until", getattr(self.instance, "valid_until", None))
        if start and end and end < start:
            raise serializers.ValidationError(
                {"valid_until": gettext("Das Ende liegt vor dem Beginn.")}
            )
        return attrs

    def create(self, validated_data):
        person = validated_data.pop("member", None)
        if person is not None:
            validated_data["person"] = person
        email = validated_data.pop("email").lower()
        user, created = User.objects.get_or_create(email=email)
        if created:
            # Kein Startpasswort mehr: die Person legt ihr Passwort über die Einladung fest
            user.set_unusable_password()
            user.save(update_fields=["password"])
        assignment = RoleAssignment.objects.create(user=user, **validated_data)
        assignment._new_account = created
        if created:
            from accounts.invitations import send_invitation

            assignment._invited = send_invitation(
                user, self.context["org"], validated_data["role"].name
            )
        return assignment

    def update(self, instance, validated_data):
        validated_data.pop("email", None)
        if "member" not in validated_data:
            return super().update(instance, validated_data)
        person = validated_data.pop("member")
        validated_data["person"] = person
        assignment = super().update(instance, validated_data)
        if assignment.user_id:
            self._link_other_roles(assignment, person)
        return assignment

    def _link_other_roles(self, assignment, person) -> None:
        """Ein Konto gehört einer Person: Alle Zuordnungen des Kontos in dieser Einheit
        bekommen dieselbe Mitgliedsakte (protokolliert)."""
        from audit.log import diff, record, snapshot

        others = (
            RoleAssignment.objects.filter(organization=assignment.organization_id)
            .filter(user_id=assignment.user_id)
            .exclude(pk=assignment.pk)
            .exclude(person=person)
            .select_related("user", "role", "person")
        )
        request = self.context.get("request")
        for other in others:
            before = snapshot(other)
            other.person = person
            other.save(update_fields=["person"])
            record(
                self.context["org"],
                getattr(request, "user", None),
                "update",
                other,
                diff(before, snapshot(other)),
                person=person,
            )
