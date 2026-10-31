"""Verwaltung in der App, Schritt B2: Mitglieder, Freigaben, Ausweis prüfen.

Die meisten Endpunkte sind die Browser-Ansichten unter ``/api/app/v1/admin/u/<Einheit>/``
(``for_app``): dieselben Prüfungen, dasselbe Protokoll, dasselbe Rückgängig. Neu sind nur,
was der Browser so nicht braucht:

- ``members/<id>/preview/``: Folgen einer Änderung vorab (Bestätigungsseite in der App)
- ``members/<id>/move/``: Untereinheit wechseln in einem Schritt (ein Rückgängig)
- ``cards/check/``: gescannten Ausweis prüfen
- ``billing/mandates/``: IBAN nur gekürzt, ganz nur mit ``?voll=1``
"""

from __future__ import annotations

import datetime

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import MEMBERS_EDIT, MEMBERS_VIEW
from audit.log import diff, record, snapshot
from billing.views import MandateViewSet
from members.models import DepartmentMembership, ExitReason, Membership, MemberType
from members.serializers import DepartmentMembershipSerializer, member_detail
from members.views import _ClubMixin
from organizations.terms import fill

from .admin_api import for_app


def _euro(value) -> str:
    return f"{value:.2f}".replace(".", ",") + " €"


def _date(value: datetime.date) -> str:
    return value.strftime("%d.%m.%Y")


class PreviewSerializer(serializers.Serializer):
    action = serializers.ChoiceField(["change_type", "exit", "move", "fee_self", "bank"])
    member_type = serializers.IntegerField(required=False)
    valid_from = serializers.DateField(required=False)
    exit_date = serializers.DateField(required=False)
    exit_reason = serializers.CharField(required=False)
    department = serializers.IntegerField(required=False)
    pays_fee_self = serializers.BooleanField(required=False)


class _MemberMixin(_ClubMixin):
    def get_membership(self) -> Membership:
        return get_object_or_404(
            Membership.objects.select_related("person"),
            organization=self.org,
            pk=self.kwargs["pk"],
            purged_at__isnull=True,
        )


class MemberPreviewView(_MemberMixin, APIView):
    """Was eine folgenreiche Änderung bewirkt, ohne etwas zu ändern."""

    read_permission = MEMBERS_VIEW
    write_permission = MEMBERS_VIEW

    @extend_schema(request=PreviewSerializer, responses=dict)
    def post(self, request, org_id: int, pk: int):
        membership = self.get_membership()
        data = PreviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        handler = {
            "change_type": self._change_type,
            "exit": self._exit,
            "move": self._move,
            "fee_self": self._fee_self,
            "bank": self._bank,
        }[v["action"]]
        title, items = handler(membership, v)
        return Response({"title": title, "consequences": items})

    # --- einzelne Änderungen ---

    def _fee(self, membership, member_type, on):
        """Jahresbeitrag dieser Mitgliedsart (nur mit Beitragsmodul und Geburtsdatum)."""
        from billing.services import yearly_fee

        birth = membership.person.birth_date
        if "billing" not in (self.org.enabled_modules or []) or birth is None:
            return None
        return yearly_fee(self.org, member_type, birth, on.year)[0]

    def _change_type(self, membership, v):
        from members.services import federation_of

        new = MemberType.objects.filter(organization=self.org, pk=v.get("member_type") or 0).first()
        if new is None:
            raise serializers.ValidationError({"member_type": "Unbekannte Mitgliedsart."})
        on = v.get("valid_from") or timezone.localdate()
        assignment = membership.current_type(on)
        old = assignment.member_type if assignment else None
        items = [f"Ab {_date(on)}: {old.name if old else 'keine'} → {new.name}"]
        if old and old.active != new.active:
            items.append("Wird aktives Mitglied." if new.active else "Wird passives Mitglied.")
        federation = federation_of(self.org)
        if (
            federation
            and federation.pk != self.org.pk
            and (old is None or old.reported != new.reported)
        ):
            items.append(
                f"Wird an {federation.name} gemeldet."
                if new.reported
                else f"Wird nicht mehr an {federation.name} gemeldet."
            )
        if old and old.counts_for_duration != new.counts_for_duration:
            items.append(
                "Die Zeit zählt ab dann für die Mitgliedsdauer (Jubiläen)."
                if new.counts_for_duration
                else "Die Zeit zählt ab dann nicht mehr für die Mitgliedsdauer (Jubiläen)."
            )
        if membership.pays_fee_self:
            before = self._fee(membership, old, on) if old else None
            after = self._fee(membership, new, on)
            if after is not None and before != after:
                items.append(
                    f"Jahresbeitrag {_euro(after)}"
                    + (f" statt {_euro(before)}" if before is not None else "")
                )
        return "Mitgliedsart wechseln", items

    def _exit(self, membership, v):
        from billing.models import Invoice
        from cards.models import MemberCard
        from members.services import federation_of

        on = v.get("exit_date") or timezone.localdate()
        reason = v.get("exit_reason") or ""
        label = ExitReason(reason).label if reason in ExitReason.values else ""
        items = [f"Austritt zum {_date(on)}" + (f" ({label})" if label else "")]
        items.append("Die Person kommt danach ins Archiv (ehemalige Mitglieder).")
        current = membership.current_type(on)
        federation = federation_of(self.org)
        if current and current.member_type.reported and federation and federation.pk != self.org.pk:
            items.append(f"Wird bei {federation.name} abgemeldet.")
        open_until = DepartmentMembership.objects.filter(membership=membership).exclude(
            valid_until__lt=on
        )
        for dm in open_until.select_related("department"):
            items.append(f"Zugehörigkeit zu {dm.department.display_name} endet.")
        roles = membership.department_roles.exclude(valid_until__lt=on).select_related("role")
        for holder in roles:
            items.append(f"Amt „{holder.role.name}“ endet.")
        if MemberCard.objects.filter(membership=membership, revoked_at__isnull=True).exists():
            items.append("Der Mitgliedsausweis zeigt danach „keine gültige Mitgliedschaft“.")
        open_invoices = Invoice.objects.filter(
            membership=membership, status=Invoice.Status.OPEN
        ).count()
        if open_invoices:
            items.append(
                f"{open_invoices} offene Rechnung{'en' if open_invoices > 1 else ''} "
                "bleib{'en' if open_invoices > 1 else 't'} bestehen."
            )
        return "Austritt", items

    def _move(self, membership, v):
        from organizations.models import Department

        target = Department.objects.filter(
            organization=self.org, pk=v.get("department") or 0
        ).first()
        if target is None:
            raise serializers.ValidationError(
                {"department": fill("Unbekannt{adj} {sg}.", self.org)}
            )
        on = v.get("valid_from") or timezone.localdate()
        current = [
            dm
            for dm in membership.department_memberships.select_related("department")
            if dm.valid_from <= on and (dm.valid_until is None or dm.valid_until >= on)
        ]
        names = ", ".join(dm.department.display_name for dm in current)
        items = [
            f"Ab {_date(on)}: {names or 'keine'} → {target.display_name}",
        ]
        for dm in current:
            items.append(
                f"Zugehörigkeit zu {dm.department.display_name} endet am "
                f"{_date(on - datetime.timedelta(days=1))}."
            )
        old_ids = {dm.department_id for dm in current}
        for holder in membership.department_roles.exclude(valid_until__lt=on).select_related(
            "role__department"
        ):
            if holder.role.department_id in old_ids:
                items.append(
                    f"Amt „{holder.role.name}“ in {holder.role.department.display_name} "
                    "bleibt bestehen (bei Bedarf beenden)."
                )
        return fill("{Sg} wechseln", self.org), items

    def _fee_self(self, membership, v):
        pays = v.get("pays_fee_self")
        if pays is None:
            raise serializers.ValidationError({"pays_fee_self": "Bitte angeben."})
        items = [
            "Bekommt künftig eine eigene Beitragsrechnung."
            if pays
            else "Bekommt künftig keine eigene Beitragsrechnung (z. B. über die Familie)."
        ]
        return "Beitrag", items

    def _bank(self, membership, v):
        from billing.models import Mandate
        from billing.sepa import masked_iban

        items = ["Neues SEPA-Mandat (Papier) mit der neuen Bankverbindung."]
        for m in Mandate.objects.filter(membership=membership, status=Mandate.Status.ACTIVE):
            items.append(
                f"Das bisherige Mandat {m.reference} ({masked_iban(m.iban)}) wird widerrufen."
            )
        items.append("Künftige Lastschriften gehen von der neuen Bankverbindung ab.")
        return "Bankverbindung ändern", items


class MoveSerializer(serializers.Serializer):
    department = serializers.IntegerField()
    valid_from = serializers.DateField()


class MemberMoveView(_MemberMixin, APIView):
    """Untereinheit wechseln: bisherige endet am Vortag, neue beginnt (ein Änderungsschritt)."""

    read_permission = MEMBERS_VIEW
    write_permission = MEMBERS_EDIT

    @extend_schema(request=MoveSerializer, responses=dict)
    @transaction.atomic
    def post(self, request, org_id: int, pk: int):
        membership = self.get_membership()
        data = MoveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        on = data.validated_data["valid_from"]
        if not membership.current_period(on):
            raise serializers.ValidationError("Zu diesem Datum keine laufende Mitgliedschaft.")
        current = list(
            membership.department_memberships.select_for_update().filter(valid_from__lte=on)
        )
        current = [dm for dm in current if dm.valid_until is None or dm.valid_until >= on]
        if any(dm.department_id == data.validated_data["department"] for dm in current):
            raise serializers.ValidationError(fill("Ist bereits Mitglied {dieses}.", self.org))
        for dm in current:
            if dm.valid_from >= on:
                raise serializers.ValidationError(
                    "Die bisherige Zugehörigkeit beginnt erst an diesem Tag. Bitte ein späteres "
                    "Datum wählen oder im Browser korrigieren."
                )
            before = snapshot(dm)
            dm.valid_until = on - datetime.timedelta(days=1)
            dm.save()
            record(
                self.org,
                request.user,
                "update",
                dm,
                diff(before, snapshot(dm)),
                person=membership.person,
            )
        new = DepartmentMembershipSerializer(
            data={"department": data.validated_data["department"], "valid_from": on},
            context={"membership": membership, "org": self.org, "request": request},
        )
        new.is_valid(raise_exception=True)
        instance = new.save(organization=self.org, membership=membership)
        record(
            self.org,
            request.user,
            "create",
            instance,
            diff({}, snapshot(instance)),
            person=membership.person,
        )
        return Response(member_detail(membership, self.org))


class CardCheckSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=500)


def card_token(code: str) -> str:
    """Schlüssel aus dem gescannten QR-Code (Adresse …/ausweis/<Schlüssel> oder nur Schlüssel)."""
    code = code.strip()
    if "/ausweis/" in code:
        code = code.split("/ausweis/", 1)[1]
    return code.split("?", 1)[0].split("#", 1)[0].strip("/")


class CardCheckView(_ClubMixin, APIView):
    """Gescannten Ausweis prüfen: Angaben wie auf der Prüfseite, dazu die Akte, wenn sie zu
    dieser Einheit gehört."""

    read_permission = MEMBERS_VIEW
    write_permission = MEMBERS_VIEW

    @extend_schema(request=CardCheckSerializer, responses=dict)
    def post(self, request, org_id: int):
        from cards import services

        data = CardCheckSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        card = services.find_valid(card_token(data.validated_data["code"]))
        if card is None:
            return Response(
                {
                    "status": "unknown",
                    "status_label": "Unbekannter oder gesperrter Ausweis",
                    "membership": None,
                }
            )
        result = services.public_data(card)
        own = card.organization_id == self.org.pk
        result["membership"] = card.membership_id if own else None
        result.pop("imprint_key", None)
        return Response(result)


class AppMandateViewSet(for_app(MandateViewSet)):
    """SEPA-Mandate in der App: IBAN nur gekürzt, ganz nur auf ausdrücklichen Abruf."""

    def finalize_response(self, request, response, *args, **kwargs):
        if request.query_params.get("voll") != "1" and isinstance(
            getattr(response, "data", None), (dict, list)
        ):
            response.data = _mask(response.data)
        return super().finalize_response(request, response, *args, **kwargs)


def _mask(data):
    if isinstance(data, list):
        return [_mask(item) for item in data]
    if isinstance(data, dict):
        if "results" in data and isinstance(data["results"], list):
            return {**data, "results": _mask(data["results"])}
        if "iban" in data:
            return {**data, "iban": None}
    return data
