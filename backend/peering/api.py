"""Oberfläche des Verbunds: Einstellungen › Verbund (Vorstände mit „Verbund verwalten“)."""

from __future__ import annotations

import datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import (
    BILLING_EDIT,
    BILLING_VIEW,
    DATA_EXPORT,
    FINANCE_EDIT,
    MEMBERS_EDIT,
    MEMBERS_VIEW,
    PEERING_MANAGE,
)
from access.permissions import permissions_in
from core.api_base import OrgScopedMixin
from events.models import Event
from organizations.views import IsPlatformAdmin

from . import (
    identity,
    keys,
    packet_circulars,
    packet_invoices,
    packets,
    register,
    services,
    spinoff,
    transfers,
    transport,
)
from .models import (
    Coupling,
    Message,
    Peer,
    RemoteInvoice,
    RemoteMember,
    RemoteState,
    RemoteTransfer,
)


def _raise(exc: DjangoValidationError):
    raise ValidationError({"detail": " ".join(exc.messages)}) from exc


def coupling_data(c: Coupling, with_messages: bool = False, perms: set[str] | None = None) -> dict:
    """Kopplung zur Anzeige. ``perms``: Rechte des Betrachters in der Einheit.

    „Verbund verwalten“ allein zeigt keine Namen und keine Rechnungen: namentliche
    Klärfälle und Wechsel brauchen „Mitglieder ansehen“, Eingangsrechnungen „Beiträge/
    Rechnungen ansehen“ (Gesamtaudit 30.10.a, BSEC-V02).
    """
    remote = c.remote_unit
    names = perms is None or MEMBERS_VIEW in perms
    bills = perms is None or BILLING_VIEW in perms
    data = {
        "id": c.id,
        "direction": c.direction,
        "state": c.state,
        "state_label": c.get_state_display(),
        "remote": {
            "id": remote.id,
            "name": remote.name,
            "logo_url": remote.logo.url if remote.logo else None,
            "base_url": c.peer.base_url,
            "country": c.peer.country,
            "fingerprint": c.peer.fingerprint,
        },
        "send": services.packet_choices(c, c.packets or {}),
        "receive": [
            {
                "key": p.key,
                "label": p.label,
                "personal": p.personal,
                "value": (c.remote_packets or {}).get(p.key),
            }
            for p in packets.receivable(c)
        ],
        "last_sync_at": c.last_sync_at,
        "last_contact_at": c.last_contact_at,
        "last_error": c.last_error,
        "error_since": c.error_since,
        "queued": c.messages.filter(
            direction=Message.Direction.OUT, state=Message.State.QUEUED
        ).count(),
        "received": received_states(c),
        "register": register_data(c, names=names)
        if c.direction == Coupling.Direction.CHILD
        else None,
        "transfers": [
            transfers.transfer_data(t)
            for t in c.transfers.select_related("membership__person")[:50]
        ]
        if c.direction == Coupling.Direction.PARENT and names
        else [],
        "options": {
            k: v for k, v in (c.options or {}).items() if k not in ("move", "accept", "wants_more")
        },
        "move": _move_data(c),
        # Notfallwechsel der Gegenstelle wartet auf Bestätigung (Härtung H6)
        "keys": keys.pending_of(c),
        # Gegenseite möchte mehr senden, als hier angenommen ist (Härtung H4)
        "wants_more": services.wants_more(c),
        "keys_changed_at": c.peer.keys_changed_at,
        "circulars": [packet_circulars.circular_data(r) for r in c.circulars.all()[:30]],
        "invoices": [
            packet_invoices.invoice_data(r)
            for r in c.invoices.select_related("invoice", "coupling").order_by("-date", "-id")[:100]
        ]
        if bills
        else [],
        # Was wegen fehlender Rechte ausgeblendet ist (für einen Hinweis in der Oberfläche)
        "hidden": [k for k, ok in (("names", names), ("invoices", bills)) if not ok],
        "created_at": c.created_at,
        "activated_at": c.activated_at,
        "ended_at": c.ended_at,
    }
    if with_messages:
        data["messages"] = [
            {
                "direction": m.direction,
                "seq": m.seq,
                "kind": m.kind,
                "persons": m.persons,
                "state": m.state,
                "state_label": m.get_state_display(),
                "attempts": m.attempts,
                "last_error": m.last_error,
                "created_at": m.created_at,
                "done_at": m.done_at,
            }
            for m in c.messages.order_by("-created_at")[:50]
        ]
    return data


def _foreign_file(response):
    """Datei einer anderen Instanz: wie ein fremder Upload abgeschottet anzeigen."""
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox"
    response["Cache-Control"] = "private, max-age=3600"
    return response


def _move_data(c: Coupling) -> dict | None:
    move = (c.options or {}).get("move")
    if c.state != Coupling.State.MOVING or not move:
        return None
    return {
        "from": move.get("from", ""),
        "base_url": move.get("base_url", ""),
        "fingerprint": move.get("fingerprint", ""),
        "country": move.get("country", ""),
        "at": move.get("at"),
    }


def received_states(c: Coupling) -> dict:
    """Was die Gegenseite zur Anzeige übermittelt hat (Vorstand, Satzung)."""
    result: dict = {}
    for state in c.states.all():
        data = {k: v for k, v in (state.data or {}).items() if k != "level"}
        if state.file:
            data["download_url"] = (
                f"/api/orgs/{c.local_unit_id}/peering/couplings/{c.pk}/files/{state.key}/"
            )
        result[state.key] = data
    result["events"] = c.remote_unit and Event.objects.filter(organization=c.remote_unit).count()
    return result


def register_data(c: Coupling, names: bool = True) -> dict | None:
    """Namentliche Meldung eines fernen Vereins: Anzahl und Klärfälle (nur oben).

    Ohne ``names`` nur die Anzahlen (Recht „Mitglieder ansehen“ fehlt).
    """
    from members.models import Person

    entries = list(c.members.select_related("membership__person"))
    if not entries:
        return None
    counts = {s: 0 for s in RemoteMember.Status.values}
    for rm in entries:
        counts[rm.status] += 1
    if not names:
        return {"counts": counts, "unclear": [], "conflicts": [], "corrections": []}
    unclear = []
    candidate_ids = {pid for rm in entries for pid in (rm.data or {}).get("candidates", [])}
    persons = {
        p.pk: p
        for p in Person.objects.filter(pk__in=candidate_ids)
        .select_related("federation")
        .prefetch_related("memberships__organization")
    }
    for rm in entries:
        if rm.status != RemoteMember.Status.UNCLEAR:
            continue
        row = (rm.data or {}).get("row") or {}
        unclear.append(
            {
                "id": rm.pk,
                "last_name": row.get("last_name", ""),
                "first_name": row.get("first_name", ""),
                "birth_date": row.get("birth_date"),
                "candidates": [
                    {
                        "id": p.pk,
                        "name": f"{p.first_name} {p.last_name}",
                        "birth_date": p.birth_date,
                        "member_number": getattr(
                            getattr(p, "federation", None), "member_number", None
                        ),
                        "units": sorted({m.organization.name for m in p.memberships.all()}),
                    }
                    for pid in (rm.data or {}).get("candidates", [])
                    if (p := persons.get(pid)) is not None
                ],
            }
        )
    conflicts = [
        {
            "id": rm.pk,
            "name": str(rm.membership.person) if rm.membership else rm.uid,
            "active_elsewhere": rm.data["active_elsewhere"],
        }
        for rm in entries
        if (rm.data or {}).get("active_elsewhere")
    ]
    corrections = [
        {
            "id": rm.pk,
            "name": str(rm.membership.person),
            "current": {
                f: getattr(rm.membership.person, f)
                for f in ("last_name", "first_name", "birth_date")
            },
            "proposed": rm.data[register.CORRECTION],
        }
        for rm in entries
        if rm.membership_id and (rm.data or {}).get(register.CORRECTION)
    ]
    return {
        "counts": counts,
        "unclear": unclear,
        "conflicts": conflicts,
        "corrections": corrections,
    }


class _Peering(OrgScopedMixin, APIView):
    read_permission = PEERING_MANAGE
    write_permission = PEERING_MANAGE

    def couplings(self):
        return Coupling.objects.filter(local_unit=self.org).select_related("remote_unit", "peer")

    def coupling(self, pk: int) -> Coupling:
        return get_object_or_404(self.couplings(), pk=pk)

    def perms(self) -> set[str]:
        if not hasattr(self, "_perms"):
            self._perms = set(permissions_in(self.request.user, self.org))
        return self._perms

    def require(self, code: str, message: str) -> None:
        if code not in self.perms():
            raise PermissionDenied(message)

    def data(self, c: Coupling, with_messages: bool = False) -> dict:
        return coupling_data(c, with_messages=with_messages, perms=self.perms())


class OverviewView(_Peering):
    def get(self, request, org_id):
        on = services.enabled()
        ident = identity.identity() if on else None
        return Response(
            {
                "enabled": on,
                "can_offer": on and services.can_offer(self.org),
                "can_join": on and services.can_join(self.org),
                "instance": {"base_url": identity.base_url(), "fingerprint": ident.fingerprint}
                if ident
                else None,
                "couplings": [
                    self.data(c) for c in self.couplings().order_by("state", "remote_unit__name")
                ],
            }
        )


class CodeView(_Peering):
    def post(self, request, org_id):
        try:
            text, code = services.create_code(self.org, request.user)
        except DjangoValidationError as exc:
            _raise(exc)
        return Response({"code": text, "expires_at": code.expires_at}, status=201)


class InspectView(_Peering):
    def post(self, request, org_id):
        try:
            return Response(services.inspect_code(self.org, str(request.data.get("code", ""))))
        except DjangoValidationError as exc:
            _raise(exc)


class JoinView(_Peering):
    def post(self, request, org_id):
        try:
            coupling = services.request_coupling(
                self.org,
                str(request.data.get("code", "")),
                request.data.get("packets") or {},
                request.user,
            )
        except DjangoValidationError as exc:
            _raise(exc)
        return Response(self.data(coupling), status=201)


class CouplingView(_Peering):
    def get(self, request, org_id, pk):
        return Response(self.data(self.coupling(pk), with_messages=True))

    def patch(self, request, org_id, pk):
        coupling = self.coupling(pk)
        if not coupling.is_open and coupling.state != Coupling.State.PENDING:
            raise ValidationError({"detail": "Die Kopplung ist nicht aktiv."})
        if "options" in request.data:
            options = request.data.get("options") or {}
            coupling.options = {
                **(coupling.options or {}),
                "circulars_auto": bool(options.get("circulars_auto")),
            }
            coupling.save(update_fields=["options"])
            services._audit(
                coupling,
                request.user,
                "Rundschreiben von oben "
                + (
                    "automatisch weitergeben"
                    if coupling.options["circulars_auto"]
                    else "erst prüfen"
                ),
            )
        if "packets" not in request.data:
            return Response(self.data(coupling, with_messages=True))
        coupling = services.set_packets(coupling, request.data.get("packets") or {}, request.user)
        return Response(self.data(coupling, with_messages=True))

    def delete(self, request, org_id, pk):
        services.end(self.coupling(pk), request.user)
        return Response(status=204)


class CouplingActionView(_Peering):
    def post(self, request, org_id, pk, action):
        coupling = self.coupling(pk)
        try:
            if action == "accept":
                coupling = services.accept(coupling, request.user, request.data.get("packets"))
            elif action == "decline":
                services.decline(coupling, request.user)
            elif action == "pause":
                coupling = services.set_paused(coupling, True, request.user)
            elif action == "resume":
                coupling = services.set_paused(coupling, False, request.user)
            elif action == "move-confirm":
                from . import moving

                coupling = moving.confirm_move(
                    coupling, str(request.data.get("fingerprint") or ""), request.user
                )
            elif action == "move-decline":
                from . import moving

                moving.decline_move(coupling, request.user)
            elif action in ("more-accept", "more-decline"):
                coupling = services.decide_more(
                    coupling,
                    str(request.data.get("key") or ""),
                    action == "more-accept",
                    request.user,
                )
            elif action in ("keys-confirm", "keys-decline"):
                raise PermissionDenied(
                    "Einen Notfallwechsel der Schlüssel bestätigt die Plattformverwaltung, weil "
                    "er für alle Kopplungen mit dieser Instanz gilt."
                )
            elif action == "sync":
                services.sync(coupling)
                services.deliver(coupling.pk)
            else:
                raise NotFound()
        except DjangoValidationError as exc:
            _raise(exc)
        coupling.refresh_from_db()
        return Response(self.data(coupling, with_messages=True))


class CouplingFileView(_Peering):
    def get(self, request, org_id, pk, key):
        state = get_object_or_404(RemoteState, coupling=self.coupling(pk), key=key)
        if not state.file:
            raise NotFound()
        name = (state.data or {}).get("name") or f"{key}.pdf"
        return _foreign_file(
            FileResponse(
                state.file.open("rb"),
                content_type="application/pdf",
                filename=name,
                as_attachment=False,
            )
        )


_NEEDS_BILLING = "Eingangsrechnungen braucht das Recht „Beiträge/Rechnungen bearbeiten“."


class _Invoice(_Peering):
    def remote_invoice(self, pk: int, invoice_id: int) -> RemoteInvoice:
        return get_object_or_404(
            RemoteInvoice.objects.select_related("coupling", "invoice"),
            coupling=self.coupling(pk),
            pk=invoice_id,
        )


class InvoiceFileView(_Invoice):
    def get(self, request, org_id, pk, invoice_id):
        self.require(BILLING_EDIT, _NEEDS_BILLING)
        remote = self.remote_invoice(pk, invoice_id)
        if not remote.file:
            raise NotFound()
        return _foreign_file(
            FileResponse(
                remote.file.open("rb"),
                content_type="application/pdf",
                filename=f"Rechnung-{remote.number or remote.uid}.pdf",
                as_attachment=False,
            )
        )


class InvoicePaidView(_Invoice):
    """Eingangsrechnung als bezahlt melden, auf Wunsch mit Ausgabe in der Kasse."""

    def post(self, request, org_id, pk, invoice_id):
        import datetime

        from django.utils import timezone

        from finance.models import Account, Category

        self.require(BILLING_EDIT, _NEEDS_BILLING)
        remote = self.remote_invoice(pk, invoice_id)
        try:
            date = datetime.date.fromisoformat(str(request.data.get("date") or ""))
        except ValueError:
            date = timezone.localdate()
        account = category = None
        if request.data.get("account"):
            if FINANCE_EDIT not in permissions_in(request.user, self.org):
                raise PermissionDenied("Buchen in der Kasse braucht das Recht „Kasse führen“.")
            account = Account.objects.filter(
                organization=self.org, pk=request.data["account"]
            ).first()
            category = Category.objects.filter(
                organization=self.org, pk=request.data.get("category") or 0
            ).first()
            if account is None:
                raise ValidationError({"account": "Konto nicht gefunden."})
        try:
            packet_invoices.report_paid(
                remote, date=date, account=account, category=category, user=request.user
            )
        except DjangoValidationError as exc:
            _raise(exc)
        remote.refresh_from_db()
        return Response(packet_invoices.invoice_data(remote))


class RegisterResolveView(_Peering):
    """Klärfall entscheiden: dieselbe Person (``person``) oder eine andere (null)."""

    def post(self, request, org_id, pk, member_id):
        self.require(
            MEMBERS_EDIT, "Klärfälle entscheiden braucht das Recht, Mitglieder zu bearbeiten."
        )
        coupling = self.coupling(pk)
        rm = get_object_or_404(RemoteMember, coupling=coupling, pk=member_id)
        correction = request.data.get("correction")
        if correction in ("apply", "discard"):
            try:
                register.decide_correction(rm, correction == "apply")
            except DjangoValidationError as exc:
                _raise(exc)
            coupling.refresh_from_db()
            return Response(self.data(coupling, with_messages=True))
        person = request.data.get("person")
        from organizations.models import Organization

        from . import packet_unit_members

        resolve = (
            packet_unit_members.resolve
            if coupling.remote_unit.type == Organization.Type.UNIT
            else register.resolve
        )
        try:
            resolve(rm, int(person) if person else None)
        except (TypeError, ValueError):
            raise ValidationError({"person": "Ungültige Auswahl."}) from None
        except DjangoValidationError as exc:
            _raise(exc)
        coupling.refresh_from_db()
        return Response(self.data(coupling, with_messages=True))


class TransferCreateView(_Peering):
    """Unten: Wechselanfrage über den fernen Dachverband stellen."""

    def post(self, request, org_id, pk):
        if MEMBERS_EDIT not in permissions_in(request.user, self.org):
            raise PermissionDenied("Dafür braucht es das Recht, Mitglieder zu bearbeiten.")
        coupling = self.coupling(pk)
        try:
            transfers.request_transfer(coupling, request.data, request.user)
        except DjangoValidationError as exc:
            _raise(exc)
        coupling.refresh_from_db()
        return Response(self.data(coupling, with_messages=True), status=201)


class TransferDecideView(_Peering):
    """Unten: Wechselanfrage für eine eigene aktive Person entscheiden."""

    def post(self, request, org_id, pk, transfer_id):
        from members.models import MemberType

        if MEMBERS_EDIT not in permissions_in(request.user, self.org):
            raise PermissionDenied("Dafür braucht es das Recht, Mitglieder zu bearbeiten.")
        coupling = self.coupling(pk)
        rt = get_object_or_404(
            RemoteTransfer.objects.select_related("membership__person", "coupling"),
            coupling=coupling,
            pk=transfer_id,
        )
        new_type = None
        if request.data.get("member_type"):
            new_type = MemberType.objects.filter(
                organization=self.org, pk=request.data["member_type"]
            ).first()
        try:
            transfers.decide(
                rt,
                str(request.data.get("decision") or ""),
                request.user,
                new_type=new_type,
                response=str(request.data.get("response") or ""),
            )
        except DjangoValidationError as exc:
            _raise(exc)
        coupling.refresh_from_db()
        return Response(self.data(coupling, with_messages=True))


class RegisterSuggestView(OrgScopedMixin, APIView):
    """Dachverband: Korrektur zu einer namentlich gemeldeten Person vorschlagen (P6)."""

    allowed_org_types = ("federation", "club")
    read_permission = MEMBERS_EDIT
    write_permission = MEMBERS_EDIT

    def post(self, request, org_id, membership_id):
        from members.serializers import MemberUpdateSerializer

        rm = get_object_or_404(
            RemoteMember.objects.select_related("coupling", "membership__person"),
            coupling__local_unit=self.org,
            coupling__direction=Coupling.Direction.CHILD,
            membership_id=membership_id,
        )
        values = MemberUpdateSerializer(data=request.data, partial=True)
        values.is_valid(raise_exception=True)
        try:
            register.suggest(
                rm, values.validated_data, str(request.data.get("message") or ""), request.user
            )
        except DjangoValidationError as exc:
            _raise(exc)
        return Response({"detail": "Der Vorschlag ist an den Verein unterwegs."}, status=202)


class MoveView(_Peering):
    """Umzug dieser Einheit auf eine andere Instanz melden (nach Export und Import dort).

    Ohne Fingerabdruck: nur die neue Instanz prüfen und ihren Fingerabdruck zeigen."""

    def post(self, request, org_id):
        from . import moving

        base_url = str(request.data.get("base_url") or "")
        fingerprint = str(request.data.get("fingerprint") or "")
        try:
            if not fingerprint:
                info = moving.inspect_target(base_url)
                return Response({"base_url": info["base_url"], "fingerprint": info["fingerprint"]})
            return Response(moving.announce(self.org, base_url, fingerprint, request.user))
        except DjangoValidationError as exc:
            _raise(exc)
        except transport.PeerError as exc:
            raise ValidationError({"detail": f"Die neue Instanz antwortet nicht: {exc}"}) from exc


class PlatformPeeringView(APIView):
    """Plattform: eigene Selbstauskunft und alle Kopplungen der Instanz (Übersicht)."""

    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        ident = identity.identity()
        couplings = Coupling.objects.select_related("local_unit", "remote_unit", "peer").order_by(
            "local_unit__name"
        )
        return Response(
            {
                "enabled": services.enabled(),
                "instance": {
                    "instance_id": ident.instance_id,
                    "base_url": identity.base_url(),
                    "fingerprint": ident.fingerprint,
                },
                "keys": keys.status(),
                "pending_keys": keys.pending_peers(),
                "couplings": [
                    {
                        "id": c.id,
                        "local": c.local_unit.name,
                        "remote": c.remote_unit.name,
                        "base_url": c.peer.base_url,
                        "direction": c.direction,
                        "state": c.state,
                        "state_label": c.get_state_display(),
                        "last_contact_at": c.last_contact_at,
                        "last_error": c.last_error,
                    }
                    for c in couplings
                ],
            }
        )


class PlatformKeysView(APIView):
    """Plattform: Schlüssel der Instanz wechseln, geplant oder im Notfall (Härtung H6)."""

    permission_classes = [IsPlatformAdmin]

    def post(self, request):
        emergency = request.data.get("mode") == "emergency"
        if str(request.data.get("confirm") or "").strip().upper() != (
            "NOTFALL" if emergency else "WECHSELN"
        ):
            raise ValidationError({"detail": "Zum Bestätigen bitte das angezeigte Wort eintippen."})
        keys.rotate(request.user, emergency=emergency)
        return Response(keys.status())


class PlatformPeerKeysView(APIView):
    """Plattform: Notfallwechsel einer Gegenstelle bestätigen oder ablehnen (FQ-11)."""

    permission_classes = [IsPlatformAdmin]

    def post(self, request, pk):
        peer = get_object_or_404(Peer, pk=pk)
        try:
            if request.data.get("action") == "confirm":
                keys.confirm(peer, str(request.data.get("fingerprint") or ""), request.user)
            elif request.data.get("action") == "decline":
                keys.decline(peer, request.user)
            else:
                raise ValidationError({"action": "confirm oder decline"})
        except DjangoValidationError as exc:
            _raise(exc)
        return Response({"pending_keys": keys.pending_peers()})


# --- Ausgliedern (Schritt 8c) ---


def spin_off_data(s) -> dict:
    job = s.export_job
    return {
        "id": s.id,
        "unit": {"id": s.unit_id, "name": s.unit.name},
        "way": s.way,
        "way_label": s.get_way_display(),
        "cutoff": s.cutoff,
        "state": s.state,
        "state_label": s.get_state_display(),
        "export_job": {"id": job.pk, "status": job.status, "has_file": bool(job.file)}
        if job
        else None,
        "coupling": s.coupling_id,
        "code_expires_at": s.code.expires_at if s.code_id else None,
        "created_at": s.created_at,
        "done_at": s.done_at,
        "exited_at": s.exited_at,
        "exited_count": s.exited_count,
    }


class SpinOffsView(_Peering):
    """Untereinheit auf eigene Instanz ausgliedern: nur der Vorstand (Fachfrage 1)."""

    def get(self, request, org_id):
        from .models import SpinOff

        return Response(
            {
                "checklist": {
                    way: [{"key": k, "label": t} for k, t in items.items()]
                    for way, items in spinoff.CHECKLIST.items()
                },
                "spin_offs": [
                    spin_off_data(s)
                    for s in SpinOff.objects.filter(organization=self.org).select_related(
                        "unit", "export_job", "code"
                    )
                ],
            }
        )

    def post(self, request, org_id):
        from organizations.models import Organization

        self.require(DATA_EXPORT, "Ausgliedern braucht das Recht für den vollständigen Export.")
        if self.org.type != Organization.Type.CLUB:
            raise ValidationError(
                {"detail": "Nur Einheiten mit eigenem Datenbereich gliedern aus."}
            )
        unit = Organization.objects.filter(
            pk=request.data.get("unit"), organization=self.org, type=Organization.Type.UNIT
        ).first()
        if unit is None:
            raise ValidationError({"unit": "Unbekannte Untereinheit."})
        try:
            cutoff = datetime.date.fromisoformat(str(request.data.get("cutoff") or ""))
        except ValueError:
            raise ValidationError({"cutoff": "Bitte einen Stichtag angeben."}) from None
        try:
            spin = spinoff.prepare(
                self.org,
                unit,
                request.user,
                way=str(request.data.get("way") or ""),
                cutoff=cutoff,
                checklist=request.data.get("checklist") or {},
                with_files=bool(request.data.get("with_files", True)),
            )
        except DjangoValidationError as exc:
            _raise(exc)
        spin = type(spin).objects.select_related("unit", "export_job", "code").get(pk=spin.pk)
        return Response(spin_off_data(spin), status=201)


class SpinOffCancelView(_Peering):
    def post(self, request, org_id, pk):
        from .models import SpinOff

        spin = get_object_or_404(SpinOff, organization=self.org, pk=pk)
        try:
            spinoff.cancel(spin, request.user)
        except DjangoValidationError as exc:
            _raise(exc)
        return Response(spin_off_data(spin))


class SpinOffExitView(_Peering):
    """Weg B: Vorschau (GET) und Ausführung (POST) des Sammelaustritts zum Stichtag."""

    def spin(self, pk):
        from .models import SpinOff

        return get_object_or_404(
            SpinOff.objects.select_related("unit", "export_job", "code"),
            organization=self.org,
            pk=pk,
        )

    def get(self, request, org_id, pk):
        self.require(MEMBERS_EDIT, "Dafür braucht es das Recht, Mitglieder zu bearbeiten.")
        return Response({"members": spinoff.exit_candidates(self.spin(pk))})

    def post(self, request, org_id, pk):
        self.require(MEMBERS_EDIT, "Dafür braucht es das Recht, Mitglieder zu bearbeiten.")
        spin = self.spin(pk)
        exclude = [int(x) for x in request.data.get("exclude") or [] if str(x).isdigit()]
        try:
            spinoff.collective_exit(spin, request.user, exclude)
        except DjangoValidationError as exc:
            _raise(exc)
        spin.refresh_from_db()
        return Response(spin_off_data(spin))
