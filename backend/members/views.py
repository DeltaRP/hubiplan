from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import transaction
from django.db.models import (
    BigIntegerField,
    Exists,
    F,
    Func,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
)
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import DATA_EXPORT, MEMBERS_EDIT, MEMBERS_VIEW, ORG_EDIT
from audit.log import diff, record, snapshot
from audit.models import AuditEntry
from changes import idempotency
from core.api_base import AuditMixin, OrgScopedMixin
from core.reorder import reorder_response
from organizations.models import Organization
from organizations.terms import fill
from organizations.tree import with_descendants

from . import services, type_usage
from .models import (
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
from .serializers import (
    AdmitSerializer,
    DepartmentMembershipSerializer,
    DepartmentRoleHolderSerializer,
    DuplicateSerializer,
    MemberTypeSerializer,
    MemberUpdateSerializer,
    PeriodSerializer,
    check_birth_before_entries,
    member_detail,
)


class _ClubMixin(OrgScopedMixin):
    """Mitgliedschaften der Einheit selbst: im Verein und, wenn eingeschaltet,
    in der obersten Einheit (eigene Mitglieder des Dachverbands)."""

    allowed_org_types = (Organization.Type.CLUB, Organization.Type.FEDERATION)
    read_permission = MEMBERS_VIEW
    write_permission = MEMBERS_EDIT

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not self.org.keeps_members:
            raise NotFound(fill("{e_Nom} führt keine eigenen Mitglieder.", self.org))

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["org"] = getattr(self, "org", None)
        return ctx


class MemberTypeViewSet(_ClubMixin, AuditMixin, viewsets.ModelViewSet):
    """Mitgliedsarten des Vereins (lesen: Mitglieder lesen; ändern: Organisation)."""

    serializer_class = MemberTypeSerializer
    write_permission = ORG_EDIT
    read_permission = None

    def get_queryset(self):
        return MemberType.objects.filter(organization=self.org)

    def get_create_kwargs(self) -> dict:
        return {"organization": self.org}

    @action(detail=False, methods=["post"])
    def reorder(self, request, *args, **kwargs):
        return reorder_response(
            request, self.org, MemberType.objects.filter(organization=self.org), "sort_order"
        )

    @action(detail=True, methods=["get"])
    def usage(self, request, org_id: int, pk: int):
        """Vorschau: wird die Art gelöscht oder archiviert, und warum?"""
        member_type = self.get_object()
        found = type_usage.usages(member_type)
        return Response(
            {
                "deletable": not found,
                "reasons": [u.text for u in found],
                "is_archived": member_type.is_archived,
            }
        )

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        """Löschen, wenn unbenutzt; sonst 409 mit Grund (dann archivieren)."""
        member_type = self.get_object()
        found = type_usage.usages(member_type)
        if found:
            return Response(
                {
                    "detail": f"„{member_type.name}“ wird noch verwendet und kann nur "
                    "archiviert werden.",
                    "reasons": [u.text for u in found],
                    "can_archive": not member_type.is_archived,
                },
                status=status.HTTP_409_CONFLICT,
            )
        self.perform_destroy(member_type)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def archive(self, request, org_id: int, pk: int):
        return self._set_archived(True)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def restore(self, request, org_id: int, pk: int):
        return self._set_archived(False)

    def _set_archived(self, archived: bool):
        member_type = self.get_object()
        if member_type.is_archived != archived:
            member_type.is_archived = archived
            member_type.save(update_fields=["is_archived"])
            record(
                self.org,
                self.request.user,
                "update",
                member_type,
                {"archiviert": [not archived, archived]},
            )
        return Response(self.get_serializer(member_type).data)


# --- Mitgliederliste ---


class MemberPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


def _current_type(on):
    return MemberTypeAssignment.objects.filter(
        membership=OuterRef("pk"), valid_from__lte=on
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))


def _current_departments(on):
    return DepartmentMembership.objects.filter(
        membership=OuterRef("pk"), valid_from__lte=on
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))


def member_queryset(org: Organization):
    """Mitgliedschaften mit berechneten Spalten für Liste, Filter und Export."""
    on = today()
    open_period = MembershipPeriod.objects.filter(
        membership=OuterRef("pk"), entry_date__lte=on
    ).filter(Q(exit_date__isnull=True) | Q(exit_date__gte=on))
    current_type = _current_type(on)
    first_entry = MembershipPeriod.objects.filter(membership=OuterRef("pk")).order_by("entry_date")
    last_exit = MembershipPeriod.objects.filter(membership=OuterRef("pk")).order_by("-entry_date")
    return (
        Membership.objects.filter(organization=org)
        .select_related("person", "person__federation")
        .annotate(
            is_current=Exists(open_period),
            current_type_id=Subquery(current_type.values("member_type_id")[:1]),
            current_type_name=Subquery(current_type.values("member_type__name")[:1]),
            entry_date=Subquery(first_entry.values("entry_date")[:1]),
            exit_date=Subquery(last_exit.values("exit_date")[:1]),
        )
    )


def _persons_by_email(qs, word: str) -> set[int]:
    """Personen, deren E-Mail-Adresse ``word`` enthält. Die Adressen sind verschlüsselt
    (core/encfields.py); die Datenbank kann darin nicht suchen, also hier im Speicher."""
    word = word.lower()
    contacts = ContactDetails.objects.filter(person_id__in=qs.values("person_id")).values_list(
        "person_id", "email"
    )
    return {pid for pid, email in contacts if email and word in email.lower()}


def filter_members(qs, params, org: Organization):
    search = (params.get("suche") or "").strip()
    if search:
        q = Q()
        for word in search.split():
            word_q = (
                Q(person__last_name__icontains=word)
                | Q(person__first_name__icontains=word)
                | Q(club_number__iexact=word)
                | Q(person_id__in=_persons_by_email(qs, word))
            )
            if word.isdigit():
                word_q |= Q(person__federation__member_number=int(word))
            q &= word_q
        qs = qs.filter(q)
    status_filter = params.get("status", "aktiv")
    if status_filter == "aktiv":
        qs = qs.filter(is_current=True)
    elif status_filter == "ehemalig":
        qs = qs.filter(is_current=False)
    if params.get("art"):
        qs = qs.filter(current_type_id=params["art"])
    gender = params.get("geschlecht")
    if gender == "ohne":
        qs = qs.filter(person__gender="")
    elif gender in Gender.values:
        qs = qs.filter(person__gender=gender)
    if params.get("abteilung"):
        on = today()
        # Mitglieder der Untereinheit und aller Einheiten darunter
        unit_id = int(params["abteilung"]) if str(params["abteilung"]).isdigit() else 0
        unit_ids = with_descendants(org.pk, [unit_id]) or {unit_id}
        qs = qs.filter(
            Exists(
                DepartmentMembership.objects.filter(
                    membership=OuterRef("pk"),
                    department_id__in=unit_ids,
                    valid_from__lte=on,
                ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
            )
        )
    title = str(params.get("ehrentitel") or "")
    if title == "mit" or title.isdigit():
        from .honorary import current_awards, visible_orgs

        awards = current_awards().filter(
            person_id=OuterRef("person_id"), organization_id__in=visible_orgs(org)
        )
        if title.isdigit():
            awards = awards.filter(title_id=int(title))
        qs = qs.filter(Exists(awards))
    sort = params.get("sortierung") or "name"
    desc = sort.startswith("-")
    key = sort.lstrip("-")
    if key == "art":
        qs = qs.annotate(
            sort_key=Subquery(_current_type(today()).values("member_type__sort_order")[:1]),
            sort_name=F("current_type_name"),
        )
    elif key == "abteilung":
        first_dep = _current_departments(today()).order_by(
            "department__sort_order", "department__name"
        )
        qs = qs.annotate(
            sort_key=Subquery(first_dep.values("department__sort_order")[:1]),
            sort_name=Subquery(first_dep.values("department__name")[:1]),
        )
    elif key == "ehrentitel":
        from .honorary import current_awards, visible_orgs

        first_title = (
            current_awards()
            .filter(person_id=OuterRef("person_id"), organization_id__in=visible_orgs(org))
            .order_by("title__organization__type", "title__sort_order", "title__name")
        )
        qs = qs.annotate(
            sort_key=Subquery(first_title.values("title__sort_order")[:1]),
            sort_name=Subquery(first_title.values("title__name")[:1]),
        )
    if key in ("art", "abteilung", "ehrentitel"):
        # Ohne Mitgliedsart, Abteilung bzw. Ehrung stehen in beiden Richtungen am Ende.
        ordering = [
            getattr(F(f), "desc" if desc else "asc")(nulls_last=True)
            for f in ("sort_key", "sort_name")
        ] + ["person__last_name", "person__first_name"]
        return qs.order_by(*ordering, "pk")
    if key == "geburtsdatum":
        return _by_birth(qs, desc)
    ordering = {
        "name": ("person__last_name", "person__first_name"),
        "-name": ("-person__last_name", "-person__first_name"),
        "eintritt": ("entry_date", "person__last_name"),
        "-eintritt": ("-entry_date", "person__last_name"),
        "nummer": ("club_number",),
        "-nummer": ("-club_number",),
    }.get(sort, ("person__last_name", "person__first_name"))
    return qs.order_by(*ordering, "pk")


def _by_birth(qs, desc: bool):
    """Nach Geburtsdatum sortieren. Das Datum ist verschlüsselt, die Datenbank kann
    nicht danach sortieren: Reihenfolge in Python bilden, dann per array_position."""
    rows = list(qs.values_list("pk", "person__birth_date"))
    known = sorted((r for r in rows if r[1] is not None), key=lambda r: (r[1], r[0]))
    if desc:
        known.sort(key=lambda r: (r[1], -r[0]), reverse=True)
    ids = [pk for pk, _ in known] + sorted(pk for pk, birth in rows if birth is None)
    position = Func(
        Value(ids, output_field=ArrayField(BigIntegerField())),
        F("pk"),
        function="array_position",
        output_field=IntegerField(),
    )
    return qs.annotate(birth_position=position).order_by("birth_position")


def member_rows(memberships, org: Organization, full_names: bool = False) -> list[dict]:
    """Zeilen der Mitgliederliste; Kontakt und Abteilungen nur für diese Seite laden.

    Abteilungen stehen in der Liste mit Kurznamen, in Exporten (``full_names``)
    mit vollem Namen.
    """
    on = today()
    ids = [m.pk for m in memberships]
    person_ids = [m.person_id for m in memberships]
    contacts: dict[int, ContactDetails] = {}
    shared = services.shared_contacts()
    for c in ContactDetails.objects.filter(person_id__in=person_ids):
        own = c.organization_id == org.pk
        if c.organization_id is None or own:
            prefer = own != shared  # gemeinsam: gemeinsamer Datensatz zuerst
            if c.person_id not in contacts or prefer:
                contacts[c.person_id] = c
    from .photo_models import MemberPhoto

    photos = {
        p.membership_id: int(p.updated_at.timestamp())
        for p in MemberPhoto.objects.filter(membership_id__in=ids, status="approved")
    }
    departments: dict[int, list[str]] = {}
    for dm in (
        DepartmentMembership.objects.filter(membership_id__in=ids, valid_from__lte=on)
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
        .select_related("department")
        .order_by("department__sort_order", "department__name")
    ):
        departments.setdefault(dm.membership_id, []).append(
            dm.department.name if full_names else dm.department.display_name
        )
    from .honorary import titles_by_person

    titles = titles_by_person(person_ids, org, on)
    rows = []
    for m in memberships:
        c = contacts.get(m.person_id)
        fm = getattr(m.person, "federation", None)
        rows.append(
            {
                "id": m.pk,
                "last_name": m.person.last_name,
                "first_name": m.person.first_name,
                "birth_date": m.person.birth_date,
                "birth_year_only": m.person.birth_year_only,
                "gender": m.person.gender,
                "club_number": m.club_number,
                "member_number": fm.member_number if fm else None,
                "member_type": m.current_type_name,
                "status": "active" if m.is_current else "former",
                "entry_date": m.entry_date,
                "exit_date": None if m.is_current else m.exit_date,
                "departments": departments.get(m.pk, []),
                "honorary_titles": titles.get(m.person_id, []),
                "photo_url": (
                    f"/api/orgs/{m.organization_id}/members/{m.pk}/photo/"
                    f"?size=thumb&v={photos[m.pk]}"
                    if m.pk in photos
                    else None
                ),
                "email": c.email if c else "",
                "phone": c.phone if c else "",
                "street": c.street if c else "",
                "postal_code": c.postal_code if c else "",
                "city": c.city if c else "",
            }
        )
    return rows


class MemberListView(_ClubMixin, generics.GenericAPIView):
    pagination_class = MemberPagination

    @extend_schema(
        parameters=[
            OpenApiParameter("suche", str),
            OpenApiParameter("status", str, enum=["aktiv", "ehemalig", "alle"]),
            OpenApiParameter("art", int),
            OpenApiParameter("geschlecht", str, enum=[*Gender.values, "ohne"]),
            OpenApiParameter("abteilung", int),
            OpenApiParameter("ehrentitel", str, description="Nummer oder „mit“ (beliebiger)"),
            OpenApiParameter("sortierung", str),
        ]
    )
    def get(self, request, org_id: int):
        qs = filter_members(member_queryset(self.org), request.query_params, self.org)
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(member_rows(page, self.org))


class DuplicateView(_ClubMixin, APIView):
    read_permission = MEMBERS_EDIT

    def get(self, request, org_id: int):
        params = request.query_params
        try:
            birth_date = serializers.DateField().to_internal_value(params.get("geburtsdatum"))
        except serializers.ValidationError:
            return Response([])
        found = services.find_duplicates(
            self.org, params.get("name", ""), params.get("vorname", ""), birth_date
        )
        return Response(DuplicateSerializer(found, many=True, context={"org": self.org}).data)


class AdmitView(_ClubMixin, APIView):
    @transaction.atomic
    def post(self, request, org_id: int):
        data = AdmitSerializer(data=request.data, context={"org": self.org})
        data.is_valid(raise_exception=True)
        # Dieselbe Aufnahme erneut gesendet: keine zweite Person anlegen
        claim = idempotency.claim(request, f"members.admit.{self.org.pk}")
        if claim.done:
            membership = get_object_or_404(
                Membership.objects.select_related("person"),
                organization=self.org,
                pk=claim.result.get("membership", 0),
            )
            return Response(member_detail(membership, self.org), status=status.HTTP_200_OK)
        membership = services.admit(self.org, data.validated_data)
        claim.remember({"membership": membership.pk})
        record(
            self.org,
            request.user,
            "create",
            membership,
            {"Mitgliedsart": [None, data.validated_data["member_type"].name]},
            person=membership.person,
        )
        return Response(member_detail(membership, self.org), status=status.HTTP_201_CREATED)


class MemberDetailView(_ClubMixin, APIView):
    def get_membership(self) -> Membership:
        return get_object_or_404(
            Membership.objects.select_related("person"),
            organization=self.org,
            pk=self.kwargs["pk"],
        )

    def get(self, request, org_id: int, pk: int):
        return Response(member_detail(self.get_membership(), self.org))

    @transaction.atomic
    def patch(self, request, org_id: int, pk: int):
        # Gesperrt und frisch gelesen: gleichzeitige Änderungen anderer Felder bleiben
        membership = get_object_or_404(
            Membership.objects.select_related("person").select_for_update(),
            organization=self.org,
            pk=self.kwargs["pk"],
        )
        data = MemberUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        if membership.managed_by_id:
            locked = sorted(
                set(data.validated_data)
                & {"last_name", "first_name", "birth_date", "gender", *services.CONTACT_FIELDS}
            )
            if locked:
                raise serializers.ValidationError(
                    {
                        "detail": "Stammdaten und Kontakt pflegt die ausgegliederte Untereinheit "
                        "auf ihrer Instanz. Bitte eine Korrektur vorschlagen."
                    }
                )
        update_member(self.org, membership, data.validated_data, request.user)
        return Response(member_detail(membership, self.org))


def update_member(org: Organization, membership: Membership, values: dict, user) -> dict:
    """Ändert Name, Geburtsdatum, Vereinsnummer und Kontakt; schreibt das Protokoll."""
    person = membership.person
    if "birth_date" in values and values["birth_date"] != person.birth_date:
        check_birth_before_entries(person, values["birth_date"])
    before_person = snapshot(person)
    for field in ("last_name", "first_name", "birth_date", "gender"):
        if field in values:
            setattr(person, field, values[field])
    person.save()
    changes = diff(before_person, snapshot(person))

    if "club_number" in values and values["club_number"] != membership.club_number:
        changes[fill("Mitgliedsnummer {e_im}", membership.organization)] = [
            membership.club_number,
            values["club_number"],
        ]
        membership.club_number = values["club_number"]
        membership.save()

    if "pays_fee_self" in values and values["pays_fee_self"] != membership.pays_fee_self:
        changes["zahlt Beitrag selbst"] = [membership.pays_fee_self, values["pays_fee_self"]]
        membership.pays_fee_self = values["pays_fee_self"]
        membership.save()

    if "info_opt_out" in values and values["info_opt_out"] != (
        membership.info_opt_out_at is not None
    ):
        changes["Informationen per E-Mail"] = (
            ["erhalten", "abbestellt"] if values["info_opt_out"] else ["abbestellt", "erhalten"]
        )
        membership.info_opt_out_at = timezone.now() if values["info_opt_out"] else None
        membership.save()

    contact_values = {k: values[k] for k in services.CONTACT_FIELDS if k in values}
    if contact_values:
        old = services.contact_for(person, org)
        before = snapshot(old) if old else {}
        new = services.save_contact(person, org, contact_values)
        changes.update(diff(before, snapshot(new)))
    changes.pop("Verbandsbereich", None)
    changes.pop("person", None)
    if changes:
        record(org, user, "update", membership, changes, person=person)
    return changes


class _MemberChildMixin(_ClubMixin):
    """Unterobjekte einer Mitgliedschaft (Zeiträume, Abteilungen, Rollen)."""

    child_model = None

    def get_membership(self) -> Membership:
        return get_object_or_404(Membership, organization=self.org, pk=self.kwargs["member_pk"])

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if getattr(self, "org", None) is not None:
            ctx["membership"] = self.get_membership()
        return ctx

    def get_queryset(self):
        return self.child_model.objects.filter(
            organization=self.org, membership_id=self.kwargs["member_pk"]
        )

    def perform_create(self, serializer):
        membership = self.get_membership()
        instance = serializer.save(organization=self.org, membership=membership)
        record(
            self.org,
            self.request.user,
            "create",
            instance,
            diff({}, snapshot(instance)),
            person=membership.person,
        )

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        instance = serializer.save()
        changes = diff(before, snapshot(instance))
        if changes:
            record(
                self.org,
                self.request.user,
                "update",
                instance,
                changes,
                person=instance.membership.person,
            )

    def perform_destroy(self, instance):
        record(
            self.org,
            self.request.user,
            "delete",
            instance,
            diff(snapshot(instance), {}),
            person=instance.membership.person,
        )
        instance.delete()


class PeriodViewSet(_MemberChildMixin, viewsets.ModelViewSet):
    """Zeiträume nachtragen (Altdaten) und korrigieren."""

    serializer_class = PeriodSerializer
    child_model = MembershipPeriod
    http_method_names = ["get", "post", "patch", "delete", "options", "head"]

    @transaction.atomic
    def perform_create(self, serializer):
        # Person sperren wie die Fach-Workflows: zwei Nachträge gleichzeitig prüfen nicht
        # beide gegen denselben alten Stand (Audit 31.10. M31-04, M31-R01)
        membership = self.get_membership()
        Person.objects.select_for_update().filter(pk=membership.person_id).first()
        Membership.objects.select_for_update().filter(pk=membership.pk).first()
        fresh = self.get_serializer(data=self.request.data)
        fresh.is_valid(raise_exception=True)
        super().perform_create(fresh)

    def perform_destroy(self, instance):
        if instance.membership.periods.count() <= 1:
            raise serializers.ValidationError("Der einzige Zeitraum kann nicht gelöscht werden.")
        super().perform_destroy(instance)


class DepartmentMembershipViewSet(_MemberChildMixin, viewsets.ModelViewSet):
    serializer_class = DepartmentMembershipSerializer
    child_model = DepartmentMembership
    http_method_names = ["get", "post", "patch", "delete", "options", "head"]


class DepartmentRoleHolderViewSet(_MemberChildMixin, viewsets.ModelViewSet):
    serializer_class = DepartmentRoleHolderSerializer
    child_model = DepartmentRoleHolder
    http_method_names = ["get", "post", "patch", "delete", "options", "head"]


class FederationEntrySerializer(serializers.Serializer):
    manual_entry_date = serializers.DateField(allow_null=True)


class FederationEntryView(_ClubMixin, APIView):
    """Eintritt in den Dachverband von Hand setzen (Altdaten)."""

    def patch(self, request, org_id: int, pk: int):
        membership = get_object_or_404(Membership, organization=self.org, pk=pk)
        fm = FederationMember.objects.filter(person=membership.person).first()
        if fm is None:
            raise serializers.ValidationError("Die Person ist (noch) kein Verbandsmitglied.")
        data = FederationEntrySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        before = snapshot(fm)
        fm.manual_entry_date = data.validated_data["manual_entry_date"]
        fm.save()
        record(
            self.org,
            request.user,
            "update",
            fm,
            diff(before, snapshot(fm)),
            person=membership.person,
        )
        return Response(member_detail(membership, self.org))


class MemberHistoryView(_ClubMixin, APIView):
    """Reiter „Verlauf“: Änderungen an dieser Person in diesem Verein."""

    def get(self, request, org_id: int, pk: int):
        membership = get_object_or_404(Membership, organization=self.org, pk=pk)
        entries = AuditEntry.objects.filter(organization=self.org, person_id=membership.person_id)[
            :100
        ]
        from access.views import AuditEntrySerializer, change_set_map

        entries = list(entries)
        context = {"org": self.org, "change_sets": change_set_map(entries)}
        return Response(AuditEntrySerializer(entries, many=True, context=context).data)


class MemberDisclosureView(_ClubMixin, APIView):
    """Auskunft für dieses Mitglied als ZIP (Art. 15 DSGVO, Fachfrage 7 vom 31.10.b)."""

    read_permission = DATA_EXPORT

    def get(self, request, org_id: int, pk: int):
        from django.http import HttpResponse

        from .auskunft import build

        membership = get_object_or_404(
            Membership.objects.select_related("person"), organization=self.org, pk=pk
        )
        content = build(membership, self.org)
        record(
            self.org,
            request.user,
            "view",
            membership,
            {"Auskunft": [None, "als ZIP erstellt"]},
            person=membership.person,
        )
        name = f"auskunft-{membership.pk}-{timezone.localdate():%Y-%m-%d}.zip"
        response = HttpResponse(content, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response


class MemberErasureView(_ClubMixin, APIView):
    """Löschung auf Verlangen eines ehemaligen Mitglieds vor Ablauf der Löschfrist.

    Wie nach der Frist: nur Name, Geburtsjahr und Zeiträume bleiben; Rechnungen und
    Buchungen bleiben wegen der Aufbewahrungspflicht. Steht danach auf der Löschliste."""

    write_permission = MEMBERS_EDIT

    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        from rest_framework.exceptions import ValidationError

        from .workflows import purge_due_date, purge_membership

        membership = get_object_or_404(
            Membership.objects.select_related("person", "organization").select_for_update(),
            organization=self.org,
            pk=pk,
        )
        last = membership.periods.order_by("-exit_date").first()
        if (
            purge_due_date(membership) is None
            or last is None
            or last.exit_date is None
            or last.exit_date > today()
        ):
            raise ValidationError(
                {"detail": "Löschen geht nur bei ehemaligen Mitgliedern nach dem Austritt."}
            )
        purge_membership(membership, after_deadline=True)
        # Nach dem Löschen protokollieren (das Löschen leert ältere Einträge zur Person)
        record(
            self.org,
            request.user,
            "delete",
            membership,
            {"Daten": [None, "auf Verlangen gelöscht"]},
            person=membership.person,
        )
        membership.refresh_from_db()
        return Response(member_detail(membership, self.org))
