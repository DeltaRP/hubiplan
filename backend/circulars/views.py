"""API der Rundschreiben.

Zugänge:

- Vorstand eines Vereins oder Dachverbands: ``/api/orgs/<org_id>/circulars/…``
- Abteilungsrolle: ``/api/depts/<dept_id>/circulars/…`` (nur an die eigene Abteilung)
- Mitgliederbereich: ``/api/portal/<access_id>/circulars/…`` (empfangene lesen, abmelden)
- Abmeldelink aus der Mail: ``/api/public/circulars/optout/<token>/``
"""

from __future__ import annotations

from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from access.catalog import CIRCULARS_SEND, DEPT_CIRCULARS_SEND
from access.models import Role
from audit.log import record
from core.api_base import OrgScopedMixin
from core.files import delete_on_commit
from core.tenancy import rls_bypass, scope_of, set_rls
from members.models import Membership, MemberType
from organizations.imprint import ensure as ensure_imprint
from organizations.models import Department, DepartmentRole, Organization
from organizations.terms import fill
from portal.views import DepartmentScopedMixin, _portal_access

from . import recipients as rcp
from . import services, text
from .models import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS,
    MAX_BODY,
    MAX_SHORT_BODY,
    Circular,
    CircularAttachment,
    CircularRecipient,
    CircularTemplate,
    InboundMail,
    MailingList,
)

FILTER_LIST_KEYS = (
    "member_types",
    "departments",
    "roles",
    "clubs",
    "honorary_titles",
    "club_roles",
)
FILTER_KEY_LISTS = ("include", "exclude", "role_names")
FILTER_INT_KEYS = ("age_min", "age_max", "jubilee_year")
FILTER_BOOL_KEYS = ("board", "reported")


def user_name(user) -> str:
    if user is None:
        return ""
    return user.get_full_name() or user.email


def clean_filters(value) -> dict:
    """Nur bekannte Angaben in der erwarteten Form übernehmen."""
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise serializers.ValidationError("Ungültige Empfängerauswahl.")
    out: dict = {}
    for key in FILTER_LIST_KEYS:
        if key in value:
            out[key] = sorted(set(rcp.as_ints(value[key])))
    for key in FILTER_KEY_LISTS:
        if key in value:
            items = value[key] if isinstance(value[key], list) else []
            out[key] = sorted({str(k)[:100] for k in items if isinstance(k, str | int)})[:5000]
    for key in FILTER_INT_KEYS:
        if key in value:
            number = rcp.as_int(value[key])
            if number is not None and not 0 <= number <= 2200:
                raise serializers.ValidationError({key: "Ungültiger Wert."})
            out[key] = number
    for key in FILTER_BOOL_KEYS:
        if key in value:
            out[key] = bool(value[key])
    if "selected" in value:
        # Listen im Modus „nur ausgewählte“ (UI-Audit NMF-06)
        items = value["selected"] if isinstance(value["selected"], list) else []
        allowed = (*FILTER_LIST_KEYS, "role_names")
        out["selected"] = sorted({k for k in items if k in allowed})
    age_min, age_max = out.get("age_min"), out.get("age_max")
    if age_min is not None and age_max is not None and age_max < age_min:
        raise serializers.ValidationError(
            {"age_max": "Das Höchstalter liegt unter dem Mindestalter."}
        )
    return out


class CircularWriteSerializer(serializers.ModelSerializer):
    filters = serializers.JSONField(required=False)
    body = serializers.CharField(required=False, allow_blank=True, max_length=MAX_BODY)

    class Meta:
        model = Circular
        fields = [
            "kind",
            "audience",
            "subject",
            "body",
            "reply_to",
            "via_app",
            "also_mail",
            "filters",
            "mailing_list",
        ]

    def validate_mailing_list(self, value):
        if value is None:
            return None
        if self.instance is not None and hasattr(self.instance, "list_pattern"):
            raise serializers.ValidationError("Das Muster eines Verteilers hat keinen Verteiler.")
        ok = value.organization_id == self.context["org"].pk and value.department_id == getattr(
            self.context.get("dept"), "pk", None
        )
        if not ok:
            raise serializers.ValidationError("Verteiler nicht gefunden.")
        return value

    def validate(self, attrs):
        kind = attrs.get("kind", getattr(self.instance, "kind", None))
        body = attrs.get("body", getattr(self.instance, "body", ""))
        if kind == Circular.Kind.SHORT and len(body or "") > MAX_SHORT_BODY:
            raise serializers.ValidationError(
                {"body": f"Eine Kurzmitteilung hat höchstens {MAX_SHORT_BODY} Zeichen."}
            )
        ml = attrs.get("mailing_list")
        if ml is not None:
            # Empfänger kommen aus dem Muster des Verteilers
            attrs["audience"] = ml.pattern.audience
            attrs["filters"] = dict(ml.pattern.filters or {})
        return attrs

    def validate_filters(self, value):
        return clean_filters(value)

    def validate_audience(self, value):
        org = self.context["org"]
        if org.type != Organization.Type.FEDERATION:
            # Abteilungen schreiben nur an ihre Mitglieder
            if value in (
                Circular.Audience.DEPARTMENTS,
                Circular.Audience.ROLES,
            ) and not self.context.get("dept"):
                return value
            return Circular.Audience.MEMBERS
        if value in (Circular.Audience.DEPARTMENTS, Circular.Audience.ROLES):
            raise serializers.ValidationError("Ungültiger Empfängerkreis.")
        if value == Circular.Audience.MEMBERS and org.federation_member_access in (
            "",
            "none",
            None,
        ):
            raise serializers.ValidationError(
                fill("An Mitglieder der {pl} nur mit Zugriff auf die Mitgliedsdaten.", org)
            )
        return value


class TemplateSerializer(serializers.ModelSerializer):
    body = serializers.CharField(required=False, allow_blank=True, max_length=MAX_BODY)

    class Meta:
        model = CircularTemplate
        fields = ["id", "name", "kind", "subject", "body"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Bitte einen Namen eingeben.")
        return value


# --- Darstellung ---


def attachment_data(att: CircularAttachment, base: str) -> dict:
    return {
        "id": att.pk,
        "name": att.name,
        "size": att.size,
        "url": f"{base}attachments/{att.pk}/",
    }


def sent_counts(circular: Circular) -> dict[str, int]:
    counts = {
        "app": 0,
        "mail": 0,
        "letter": 0,
        "portal": 0,
        "failed": 0,
        "pending": 0,
        "unclear": 0,
        "sent": 0,
    }
    now = timezone.now()
    for r in circular.recipients.only("channel", "status", "sent_at"):
        counts[r.channel] = counts.get(r.channel, 0) + 1
        if r.channel in (CircularRecipient.Channel.LETTER, CircularRecipient.Channel.PORTAL):
            continue
        if r.status == CircularRecipient.Status.FAILED:
            counts["failed"] += 1
        elif services.is_unclear(r, now):
            counts["unclear"] += 1
        elif r.status in (CircularRecipient.Status.PENDING, CircularRecipient.Status.SENDING):
            counts["pending"] += 1
        elif r.status == CircularRecipient.Status.SENT:
            # An den Mailserver bzw. die App übergeben; kein Nachweis, dass es gelesen wurde
            counts["sent"] += 1
    return counts


def summary_data(c: Circular) -> dict:
    return {
        "id": c.pk,
        "subject": c.subject,
        "kind": c.kind,
        "kind_label": c.get_kind_display(),
        "audience": c.audience,
        "status": c.status,
        "status_label": c.get_status_display(),
        "department": (
            {"id": c.department_id, "name": c.department.display_name} if c.department_id else None
        ),
        "created_by": user_name(c.created_by),
        "created_at": c.created_at,
        "updated_at": c.updated_at,
        "sent_at": c.sent_at,
        "sent_by": user_name(c.sent_by),
    }


def circular_data(c: Circular, base: str) -> dict:
    data = summary_data(c)
    item_base = f"{base}{c.pk}/"
    data.update(
        {
            "body": c.body,
            "reply_to": c.reply_to,
            "via_app": c.via_app,
            "also_mail": c.also_mail,
            "filters": c.filters or {},
            "mailing_list": c.mailing_list_id,
            "can_edit": c.is_draft,
            "attachments": [attachment_data(a, item_base) for a in c.attachments.all()],
            "counts": None if c.is_draft else sent_counts(c),
        }
    )
    return data


def candidate_data(c: rcp.Candidate) -> dict:
    return {
        "key": c.key,
        "first_name": c.first_name,
        "last_name": c.last_name,
        "club": c.club.display_name,
        "email": c.email,
        "departments": c.departments,
        "channel": c.channel,
        "note": c.note,
        "excluded": c.excluded,
        "included": c.included,
        "opted_out": c.opted_out,
    }


def recipient_data(r: CircularRecipient) -> dict:
    return {
        "key": f"r{r.pk}",
        "first_name": r.first_name,
        "last_name": r.last_name,
        "club": r.club.display_name,
        "email": r.email,
        "channel": r.channel,
        "status": "unclear" if services.is_unclear(r) else r.status,
        "status_label": "Versand unklar" if services.is_unclear(r) else r.get_status_display(),
        "error": r.error,
        "sent_at": r.sent_at,
    }


# --- Zugänge ---


class _CircularMixin:
    """Gemeinsame Hilfen; ``org``, ``dept`` und ``base_url`` setzen die Zugänge."""

    org: Organization
    dept: Department | None
    base_url: str

    def circulars(self):
        qs = Circular.objects.filter(organization=self.org).select_related(
            "department", "created_by", "sent_by"
        )
        if self.dept is not None:
            qs = qs.filter(department=self.dept)
        return qs

    def get_circular(self, pk: int) -> Circular:
        circular = self.circulars().prefetch_related("attachments").filter(pk=pk).first()
        if circular is None:
            raise NotFound()
        return circular

    def is_pattern(self, circular: Circular) -> bool:
        return MailingList.objects.filter(pattern=circular).exists()

    def get_draft(self, pk: int) -> Circular:
        circular = self.get_circular(pk)
        if not circular.is_draft:
            raise serializers.ValidationError(
                "Ein versendetes Rundschreiben lässt sich nicht mehr ändern."
            )
        return circular

    def check_audience(self, circular: Circular) -> None:
        if (
            circular.audience == Circular.Audience.MEMBERS
            and self.org.type == Organization.Type.FEDERATION
            and self.org.federation_member_access in ("", "none", None)
        ):
            raise PermissionDenied(
                fill("{e_Nom} hat keinen Zugriff auf die Mitgliedsdaten der {pl}.", self.org)
            )

    def audit(self, action: str, instance, changes: dict) -> None:
        record(self.org, self.request.user, action, instance, changes)

    def templates(self):
        qs = CircularTemplate.objects.filter(organization=self.org)
        if self.dept is not None:
            qs = qs.filter(department=self.dept)
        else:
            qs = qs.filter(department__isnull=True)
        return qs


class OrgCircularMixin(_CircularMixin, OrgScopedMixin):
    read_permission = CIRCULARS_SEND
    write_permission = CIRCULARS_SEND
    allowed_org_types = (Organization.Type.FEDERATION, Organization.Type.CLUB)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.dept = None
        self.base_url = f"/api/orgs/{self.org.pk}/circulars/"


class DeptCircularMixin(_CircularMixin, DepartmentScopedMixin):
    read_permission = DEPT_CIRCULARS_SEND
    write_permission = DEPT_CIRCULARS_SEND

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.base_url = f"/api/depts/{self.dept.pk}/circulars/"


# --- Ansichten (Vorstand und Abteilung) ---


class _Options(APIView):
    """Auswahlmöglichkeiten für Empfänger, Platzhalter und Vorgaben."""

    def get(self, request, **kwargs):
        org = self.org
        data: dict = {
            "org_type": org.type,
            "department": (
                {"id": self.dept.pk, "name": self.dept.display_name} if self.dept else None
            ),
            "kinds": [{"value": v, "label": label} for v, label in Circular.Kind.choices],
            "placeholders": [{"name": k, "label": v} for k, v in text.PLACEHOLDERS.items()],
            "reply_to": request.user.email,
            "max_attachments": MAX_ATTACHMENTS,
            "max_attachment_mb": MAX_ATTACHMENT_BYTES // (1024 * 1024),
            "max_short_body": MAX_SHORT_BODY,
            # „An“: die Verteiler dieser Einheit (ohne Verteiler die freie Auswahl wie bisher)
            "lists": [
                {"id": m.pk, "name": m.name, "audience": m.pattern.audience}
                for m in MailingList.objects.filter(
                    organization=org, department=self.dept
                ).select_related("pattern")
            ],
        }
        if org.type == Organization.Type.FEDERATION:
            member_access = org.federation_member_access not in ("", "none", None)
            data["audiences"] = [
                {"value": Circular.Audience.BOARDS, "label": fill("Vorstände der {pl}", org)},
                *(
                    [
                        {
                            "value": Circular.Audience.MEMBERS,
                            "label": fill("Mitglieder der {pl}", org),
                        }
                    ]
                    if member_access
                    else []
                ),
            ]
            data["clubs"] = [
                {"id": c.pk, "name": c.display_name}
                for c in org.children.filter(type="club", is_active=True).order_by("name")
            ]
            data["honorary_titles"] = _honorary_options(org)
            return Response(data)
        data["member_types"] = [
            {"id": t.pk, "name": t.name}
            for t in MemberType.objects.filter(organization=org, is_archived=False)
        ]
        data["honorary_titles"] = _honorary_options(org)
        depts = Department.objects.filter(organization=org, is_active=True)
        roles = DepartmentRole.objects.filter(department__organization=org).select_related(
            "department"
        )
        if self.dept is not None:
            depts = depts.filter(pk=self.dept.pk)
            roles = roles.filter(department=self.dept)
        data["departments"] = [{"id": d.pk, "name": d.display_name} for d in depts]
        data["roles"] = [
            {"id": r.pk, "name": r.name, "department": r.department.display_name}
            for r in roles.order_by("department__sort_order", "department__name", "name")
        ]
        if self.dept is None:
            data["audiences"] = [
                {"value": Circular.Audience.MEMBERS, "label": "Mitglieder"},
                {
                    "value": Circular.Audience.DEPARTMENTS,
                    "label": fill("Rolleninhaber in den {pl_dat}", org),
                },
                {"value": Circular.Audience.ROLES, "label": "Rolleninhaber im Verein"},
            ]
            data["club_roles"] = [
                {"id": r.pk, "name": r.name, "is_board": r.is_board}
                for r in Role.objects.filter(organization=org, department__isnull=True).order_by(
                    "position", "name"
                )
            ]
            data["role_names"] = sorted({r.name for r in roles})
        return Response(data)


def _honorary_options(org: Organization) -> list[dict]:
    """Ehrungen zur Auswahl: eigene, im Verein auch die des Dachverbands."""
    from members.honorary import visible_orgs
    from members.models import HonoraryTitle

    titles = (
        HonoraryTitle.objects.filter(organization_id__in=visible_orgs(org), is_archived=False)
        .select_related("organization")
        .order_by("organization__type", "sort_order", "name")
    )
    return [
        {
            "id": t.pk,
            "name": t.name
            if t.organization_id == org.pk
            else f"{t.name} ({t.organization.display_name})",
        }
        for t in titles
    ]


class _List(APIView):
    """GET: Rundschreiben · POST: neuen Entwurf anlegen (optional aus Vorlage oder Kopie)."""

    def get(self, request, **kwargs):
        # Muster der Verteiler erscheinen nur beim Verteiler
        qs = self.circulars().filter(list_pattern__isnull=True)
        state = request.query_params.get("status")
        if state == "draft":
            qs = qs.filter(status=Circular.Status.DRAFT)
        elif state == "sent":
            qs = qs.exclude(status=Circular.Status.DRAFT)
        return Response([summary_data(c) for c in qs[:300]])

    @transaction.atomic
    def post(self, request, **kwargs):
        initial: dict = {}
        template_id = rcp.as_int(request.data.get("template"))
        copy_id = rcp.as_int(request.data.get("copy_of"))
        if template_id:
            tpl = self.templates().filter(pk=template_id).first()
            if tpl is None:
                raise serializers.ValidationError({"template": "Vorlage nicht gefunden."})
            initial = {"kind": tpl.kind, "subject": tpl.subject, "body": tpl.body}
        elif copy_id:
            src = self.circulars().filter(pk=copy_id).first()
            if src is None:
                raise serializers.ValidationError({"copy_of": "Rundschreiben nicht gefunden."})
            initial = {
                "kind": src.kind,
                "audience": src.audience,
                "subject": src.subject,
                "body": src.body,
                "filters": {k: v for k, v in (src.filters or {}).items() if k != "exclude"},
                "mailing_list": src.mailing_list_id,
            }
        payload = {
            **initial,
            **{k: v for k, v in request.data.items() if k in CircularWriteSerializer.Meta.fields},
        }
        if self.org.type == Organization.Type.FEDERATION:
            payload.setdefault("audience", Circular.Audience.BOARDS)
        ser = CircularWriteSerializer(data=payload, context={"org": self.org, "dept": self.dept})
        ser.is_valid(raise_exception=True)
        circular = ser.save(
            organization=self.org,
            department=self.dept,
            created_by=request.user,
            reply_to=ser.validated_data.get("reply_to") or "",
        )
        self.audit("create", circular, {"Betreff": [None, circular.subject]})
        return Response(circular_data(circular, self.base_url), status=status.HTTP_201_CREATED)


class _Detail(APIView):
    def get(self, request, pk: int, **kwargs):
        return Response(circular_data(self.get_circular(pk), self.base_url))

    @transaction.atomic
    def patch(self, request, pk: int, **kwargs):
        circular = self.get_draft(pk)
        ser = CircularWriteSerializer(
            circular, data=request.data, partial=True, context={"org": self.org, "dept": self.dept}
        )
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(circular_data(self.get_circular(pk), self.base_url))

    @transaction.atomic
    def delete(self, request, pk: int, **kwargs):
        circular = self.get_draft(pk)
        if self.is_pattern(circular):
            raise serializers.ValidationError("Bitte den Verteiler selbst löschen.")
        self.audit("delete", circular, {"Betreff": [circular.subject, None]})
        for att in circular.attachments.all():
            delete_on_commit(att.file)
        circular.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class _Recipients(APIView):
    """Entwurf: Vorschau der Empfänger · versendet: Versandprotokoll."""

    def get(self, request, pk: int, **kwargs):
        circular = self.get_circular(pk)
        if circular.is_draft:
            services.apply_list(circular)
            self.check_audience(circular)
            selection = rcp.select(circular)
            return Response(
                {
                    "counts": selection.counts(),
                    "items": [candidate_data(c) for c in selection.candidates],
                }
            )
        rows = circular.recipients.select_related("club")
        return Response(
            {"counts": sent_counts(circular), "items": [recipient_data(r) for r in rows]}
        )


class _Search(APIView):
    """Mitglieder suchen, um sie einzeln hinzuzufügen (``?suche=``)."""

    def get(self, request, pk: int, **kwargs):
        circular = self.get_draft(pk)
        self.check_audience(circular)
        query = (request.query_params.get("suche") or "").strip()
        if len(query) < 2 or circular.audience != Circular.Audience.MEMBERS:
            return Response([])
        if self.org.type == Organization.Type.FEDERATION:
            from members.federation_views import federation_queryset, filter_federation

            qs = filter_federation(
                federation_queryset(self.org).filter(is_current=True), {"suche": query}
            )
        else:
            from members.views import filter_members

            qs = filter_members(
                rcp.club_base(self.org, self.dept), {"suche": query, "status": "alle"}, self.org
            )
        return Response(
            [
                {
                    "key": f"m{m.pk}",
                    "first_name": m.person.first_name,
                    "last_name": m.person.last_name,
                    "club": m.organization.display_name,
                }
                for m in qs.select_related("organization")[:20]
            ]
        )


class _Send(APIView):
    def post(self, request, pk: int, **kwargs):
        circular = self.get_draft(pk)
        if self.is_pattern(circular):
            raise serializers.ValidationError("Das ist die Empfängerauswahl eines Verteilers.")
        services.apply_list(circular)
        self.check_audience(circular)
        counts = services.start_sending(circular, request.user)
        circular = self.get_circular(pk)
        self.audit(
            "update",
            circular,
            {"versendet": [None, sent_text(counts)]},
        )
        return Response({**circular_data(circular, self.base_url), "sent": counts})


def sent_text(counts: dict[str, int]) -> str:
    parts = [f"{counts.get('mail', 0)} E-Mails", f"{counts.get('letter', 0)} Briefe"]
    if counts.get("app"):
        parts.insert(0, f"{counts['app']} per App")
    if counts.get("portal"):
        parts.append(f"{counts['portal']} nur im Mitgliederbereich")
    return ", ".join(parts)


class _Resend(APIView):
    """Fehlgeschlagene und unklare Mails eines versendeten Rundschreibens erneut senden."""

    def post(self, request, pk: int, **kwargs):
        circular = self.get_circular(pk)
        if circular.is_draft:
            raise serializers.ValidationError("Das Rundschreiben ist noch nicht versendet.")
        self.check_audience(circular)
        count = services.resend(circular)
        if count:
            self.audit("update", circular, {"erneut versendet": [None, f"{count} Empfänger"]})
        circular = self.get_circular(pk)
        return Response({**circular_data(circular, self.base_url), "resent": count})


class _Test(APIView):
    def post(self, request, pk: int, **kwargs):
        circular = self.get_circular(pk)
        self.check_audience(circular)
        return Response({"sent_to": services.send_test(circular, request.user)})


class _Letters(APIView):
    """Serienbrief als PDF (``?vorschau=1``: ein Beispielbrief)."""

    def get(self, request, pk: int, **kwargs):
        circular = self.get_circular(pk)
        self.check_audience(circular)
        preview = request.query_params.get("vorschau") == "1"
        content = services.letters_pdf(circular, preview=preview)
        response = HttpResponse(content, content_type="application/pdf")
        name = "Vorschau" if preview else "Briefe"
        response["Content-Disposition"] = (
            f'inline; filename="Rundschreiben-{name}-{circular.pk}.pdf"'
        )
        return response


def _safe_name(name: str) -> str:
    name = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    keep = "".join(c if c.isalnum() or c in ".-_" else "_" for c in name)
    return keep[-80:] or "anhang.pdf"


class _AttachmentList(APIView):
    parser_classes = [MultiPartParser, FormParser]

    @transaction.atomic
    def post(self, request, pk: int, **kwargs):
        circular = self.get_draft(pk)
        if circular.kind == Circular.Kind.SHORT:
            raise serializers.ValidationError({"file": "Kurzmitteilungen haben keine Anhänge."})
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": "Bitte eine Datei wählen."})
        mb = MAX_ATTACHMENT_BYTES // (1024 * 1024)
        if upload.size > MAX_ATTACHMENT_BYTES:
            raise serializers.ValidationError({"file": f"Die Datei ist größer als {mb} MB."})
        if circular.attachments.count() >= MAX_ATTACHMENTS:
            raise serializers.ValidationError(
                {"file": f"Höchstens {MAX_ATTACHMENTS} Anhänge je Rundschreiben."}
            )
        total = sum(a.size for a in circular.attachments.all()) + upload.size
        if total > 2 * MAX_ATTACHMENT_BYTES:
            raise serializers.ValidationError(
                {"file": f"Alle Anhänge zusammen höchstens {2 * mb} MB."}
            )
        head = upload.read(5)
        upload.seek(0)
        if head != b"%PDF-":
            raise serializers.ValidationError({"file": "Bitte eine PDF-Datei hochladen."})
        name = upload.name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:200]
        att = CircularAttachment(circular=circular, name=name, size=upload.size)
        att.file.save(_safe_name(upload.name), upload, save=False)
        att.save()
        self.audit("update", circular, {"Anhang": [None, att.name]})
        return Response(circular_data(self.get_circular(pk), self.base_url), status=201)


class _Attachment(APIView):
    def get(self, request, pk: int, att_id: int, **kwargs):
        circular = self.get_circular(pk)
        att = get_object_or_404(CircularAttachment, circular=circular, pk=att_id)
        return _file_response(att, request)

    @transaction.atomic
    def delete(self, request, pk: int, att_id: int, **kwargs):
        circular = self.get_draft(pk)
        att = get_object_or_404(CircularAttachment, circular=circular, pk=att_id)
        self.audit("update", circular, {"Anhang": [att.name, None]})
        delete_on_commit(att.file)
        att.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _file_response(att: CircularAttachment, request) -> FileResponse:
    response = FileResponse(
        att.file.open("rb"),
        content_type="application/pdf",
        as_attachment=request.query_params.get("download") == "1",
        filename=att.name,
    )
    response["Cache-Control"] = "private, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response


class _Templates(APIView):
    def get(self, request, **kwargs):
        return Response(TemplateSerializer(self.templates(), many=True).data)

    @transaction.atomic
    def post(self, request, **kwargs):
        ser = TemplateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tpl = ser.save(organization=self.org, department=self.dept)
        self.audit("create", tpl, {"Name": [None, tpl.name]})
        return Response(TemplateSerializer(tpl).data, status=status.HTTP_201_CREATED)


class _Template(APIView):
    def get_template(self, pk: int) -> CircularTemplate:
        tpl = self.templates().filter(pk=pk).first()
        if tpl is None:
            raise NotFound()
        return tpl

    @transaction.atomic
    def patch(self, request, tpl_id: int, **kwargs):
        tpl = self.get_template(tpl_id)
        ser = TemplateSerializer(tpl, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    @transaction.atomic
    def delete(self, request, tpl_id: int, **kwargs):
        tpl = self.get_template(tpl_id)
        self.audit("delete", tpl, {"Name": [tpl.name, None]})
        tpl.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Mailverteiler ---


class MailingListSerializer(serializers.ModelSerializer):
    senders = serializers.ListField(child=serializers.IntegerField(), required=False)

    class Meta:
        model = MailingList
        fields = ["name", "local_part", "aliases", "mode", "is_active", "open_senders", "senders"]
        # Eindeutigkeit prüft clean_local_part über alle Vereine (RLS verbirgt fremde)
        extra_kwargs = {"local_part": {"validators": []}}

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Bitte einen Namen eingeben.")
        return value

    def validate_senders(self, value):
        from . import inbound

        if self.instance is None:
            return []
        allowed = {u.pk for u in inbound.eligible_senders(self.instance)}
        wanted = set(value)
        if wanted - allowed:
            raise serializers.ValidationError(
                "Nur Personen mit dem Recht „Rundschreiben versenden“ sind möglich."
            )
        return sorted(wanted)

    def update(self, instance, validated_data):
        senders = validated_data.pop("senders", None)
        instance = super().update(instance, validated_data)
        if senders is not None:
            instance.senders.set(senders)
        return instance

    def create(self, validated_data):
        validated_data.pop("senders", None)
        return super().create(validated_data)

    def validate_local_part(self, value):
        from . import inbound

        try:
            return inbound.clean_local_part(value, self.instance)
        except serializers.ValidationError as exc:
            raise serializers.ValidationError(exc.detail["local_part"]) from exc

    def validate(self, attrs):
        from . import inbound

        if "aliases" in attrs or "local_part" in attrs:
            main = attrs.get("local_part") or getattr(self.instance, "local_part", "")
            aliases = attrs.get("aliases", getattr(self.instance, "aliases", None) or [])
            attrs["aliases"] = inbound.clean_aliases(aliases, self.instance, main)
        return attrs


def inbound_data(e: InboundMail) -> dict:
    return {
        "id": e.pk,
        "received_at": e.received_at,
        "sender": e.sender,
        "subject": e.subject,
        "status": e.status,
        "status_label": e.get_status_display(),
        "reason": e.reason,
        "circular_id": e.circular_id,
    }


def mailing_list_data(ml: MailingList) -> dict:
    from . import inbound

    pattern = ml.pattern
    last = ml.inbound.order_by("-received_at", "-pk").first()
    return {
        "id": ml.pk,
        "name": ml.name,
        "local_part": ml.local_part,
        "address": inbound.address_of(ml),
        "aliases": list(ml.aliases or []),
        "alias_addresses": inbound.alias_addresses(ml),
        "mode": ml.mode,
        "mode_label": ml.get_mode_display(),
        "is_active": ml.is_active,
        "department": (
            {"id": ml.department_id, "name": ml.department.display_name}
            if ml.department_id
            else None
        ),
        "pattern_id": pattern.pk,
        "kind": pattern.kind,
        "kind_label": pattern.get_kind_display(),
        "audience": pattern.audience,
        "open_senders": ml.open_senders,
        "senders": sorted(ml.senders.values_list("pk", flat=True)),
        "last_inbound": inbound_data(last) if last else None,
    }


def sender_options(ml: MailingList) -> list[dict]:
    from . import inbound

    return [
        {"id": u.pk, "name": user_name(u), "email": u.email} for u in inbound.eligible_senders(ml)
    ]


def inbound_settings() -> dict:
    from django.conf import settings

    from . import inbound

    found = inbound.domains()
    return {
        "domain": found[0] if found else "",
        "receiving": bool(settings.INBOUND_IMAP_HOST),
        "simulation": bool(settings.INBOUND_SIMULATION),
    }


class _ListsMixin:
    def lists(self):
        qs = MailingList.objects.filter(organization=self.org).select_related(
            "department", "pattern"
        )
        if self.dept is not None:
            qs = qs.filter(department=self.dept)
        return qs

    def get_list(self, list_id: int) -> MailingList:
        ml = self.lists().filter(pk=list_id).first()
        if ml is None:
            raise NotFound()
        return ml


class _Lists(_ListsMixin, APIView):
    """GET: Verteiler und Einstellungen · POST: neuen Verteiler anlegen."""

    def get(self, request, **kwargs):
        return Response(
            {
                "settings": inbound_settings(),
                "items": [
                    # Empfänger nach der aktuellen Auswahl im Muster (ohne Abgemeldete)
                    {**mailing_list_data(m), "recipients": len(rcp.select(m.pattern).chosen)}
                    for m in self.lists()
                ],
            }
        )

    @transaction.atomic
    def post(self, request, **kwargs):
        ser = MailingListSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        audience = (
            Circular.Audience.BOARDS
            if self.org.type == Organization.Type.FEDERATION
            else Circular.Audience.MEMBERS
        )
        pattern = Circular.objects.create(
            organization=self.org,
            department=self.dept,
            kind=Circular.Kind.INFO,
            audience=audience,
            subject=f"Verteiler {ser.validated_data['name']}"[:200],
            created_by=request.user,
        )
        ml = ser.save(organization=self.org, department=self.dept, pattern=pattern)
        self.audit("create", ml, {"Verteiler": [None, ml.local_part]})
        return Response(mailing_list_data(ml), status=status.HTTP_201_CREATED)


class _ListDetail(_ListsMixin, APIView):
    def get(self, request, list_id: int, **kwargs):
        ml = self.get_list(list_id)
        return Response({**mailing_list_data(ml), "sender_options": sender_options(ml)})

    @transaction.atomic
    def patch(self, request, list_id: int, **kwargs):
        ml = self.get_list(list_id)
        before = {
            "local_part": ml.local_part,
            "aliases": list(ml.aliases or []),
            "is_active": ml.is_active,
            "open_senders": ml.open_senders,
        }
        senders_before = sorted(ml.senders.values_list("email", flat=True))
        ser = MailingListSerializer(ml, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ml = ser.save()
        changes = {k: [v, getattr(ml, k)] for k, v in before.items() if getattr(ml, k) != v}
        senders_after = sorted(ml.senders.values_list("email", flat=True))
        if senders_after != senders_before:
            changes["Absender"] = [
                ", ".join(senders_before) or "alle mit dem Recht",
                ", ".join(senders_after) or "alle mit dem Recht",
            ]
        if changes:
            self.audit("update", ml, changes)
        ml = self.get_list(list_id)
        return Response({**mailing_list_data(ml), "sender_options": sender_options(ml)})

    @transaction.atomic
    def delete(self, request, list_id: int, **kwargs):
        ml = self.get_list(list_id)
        self.audit("delete", ml, {"Verteiler": [ml.local_part, None]})
        # Mit dem Muster geht auch der Verteiler (CASCADE)
        ml.pattern.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class _ListInbound(_ListsMixin, APIView):
    """Die letzten Eingänge eines Verteilers."""

    def get(self, request, list_id: int, **kwargs):
        ml = self.get_list(list_id)
        rows = InboundMail.objects.filter(mailing_list=ml).order_by("-received_at", "-pk")[:50]
        return Response([inbound_data(e) for e in rows])


class _ListProbe(_ListsMixin, APIView):
    """Probe-Eingang ohne Sammelpostfach: als käme eine Mail vom angemeldeten Benutzer."""

    def post(self, request, list_id: int, **kwargs):
        from django.conf import settings

        from . import inbound

        if not settings.INBOUND_SIMULATION:
            raise PermissionDenied("Probe-Eingänge gibt es nur ohne Sammelpostfach.")
        ml = self.get_list(list_id)
        if not ml.is_active:
            raise serializers.ValidationError("Der Verteiler ist ausgeschaltet.")
        subject = str(request.data.get("subject") or "").strip()[:200]
        body = str(request.data.get("body") or "")[: MAX_BODY + 1]
        entry = inbound.simulate(ml, request.user, subject, body)
        if entry is None:
            raise serializers.ValidationError("Diese Mail wurde schon verarbeitet.")
        data = inbound_data(entry)
        if entry.status == InboundMail.Status.WAITING:
            data["confirm_url"] = inbound.confirm_url(entry)
        return Response(data, status=status.HTTP_201_CREATED)


def _views(mixin, prefix: str) -> dict:
    """Erzeugt die Ansichten für einen Zugang (Vorstand bzw. Abteilung)."""
    bases = {
        "Options": _Options,
        "List": _List,
        "Detail": _Detail,
        "Recipients": _Recipients,
        "Search": _Search,
        "Send": _Send,
        "Resend": _Resend,
        "Test": _Test,
        "Letters": _Letters,
        "AttachmentList": _AttachmentList,
        "Attachment": _Attachment,
        "Templates": _Templates,
        "Template": _Template,
        "Lists": _Lists,
        "ListDetail": _ListDetail,
        "ListInbound": _ListInbound,
        "ListProbe": _ListProbe,
    }
    return {name: type(f"{prefix}{name}View", (mixin, base), {}) for name, base in bases.items()}


ORG_VIEWS = _views(OrgCircularMixin, "OrgCircular")


# --- Empfangen: Rundschreiben des Dachverbands an die Vorstände des Vereins ---


class ReceivedMixin(OrgScopedMixin):
    """Jede Rolle des Vereins sieht, was der Dachverband an seine Vorstände schickte."""

    read_permission = None
    write_permission = "-"  # nur lesen
    allowed_org_types = (Organization.Type.CLUB,)

    def received(self):
        rows = (
            CircularRecipient.objects.filter(
                club=self.org, circular__audience=Circular.Audience.BOARDS
            )
            .exclude(circular__organization=self.org)
            .select_related("circular", "circular__organization", "circular__department")
            .order_by("-circular__sent_at", "-pk")
        )
        # je Rundschreiben eine Zeile, bevorzugt die an den angemeldeten Benutzer
        by_circular: dict[int, CircularRecipient] = {}
        for r in rows:
            if r.circular_id not in by_circular or r.user_id == self.request.user.pk:
                by_circular[r.circular_id] = r
        return sorted(
            by_circular.values(),
            key=lambda r: r.circular.sent_at or r.circular.created_at,
            reverse=True,
        )

    def get_received(self, pk: int) -> CircularRecipient:
        found = next((r for r in self.received() if r.circular_id == pk), None)
        if found is None:
            raise NotFound()
        return found


class ReceivedListView(ReceivedMixin, APIView):
    def get(self, request, org_id: int):
        base = f"/api/orgs/{org_id}/circulars/received/"
        return Response([portal_item(r, base) for r in self.received()[:200]])


class ReceivedDetailView(ReceivedMixin, APIView):
    def get(self, request, org_id: int, pk: int):
        base = f"/api/orgs/{org_id}/circulars/received/"
        return Response(portal_item(self.get_received(pk), base, full=True))


class ReceivedAttachmentView(ReceivedMixin, APIView):
    def get(self, request, org_id: int, pk: int, att_id: int):
        r = self.get_received(pk)
        att = get_object_or_404(CircularAttachment, circular=r.circular, pk=att_id)
        return _file_response(att, request)


DEPT_VIEWS = _views(DeptCircularMixin, "DeptCircular")


# --- Mitgliederbereich ---


class PortalCircularMixin:
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        access = _portal_access(request.user, kwargs["access_id"])
        self.access = access
        self.club = access.organization
        set_rls(self.club.pk, request.user.pk, scope_id=scope_of(self.club.pk))

    def received(self):
        return (
            CircularRecipient.objects.filter(
                membership_id=self.access.membership_id, club=self.club
            )
            .select_related("circular", "circular__organization", "circular__department")
            .order_by("-circular__sent_at", "-pk")
        )

    def get_received(self, pk: int) -> CircularRecipient:
        r = self.received().filter(circular_id=pk).first()
        if r is None:
            raise NotFound()
        return r


def portal_item(r: CircularRecipient, base: str, full: bool = False) -> dict:
    c = r.circular
    data = {
        "id": c.pk,
        "subject": text.fill(c.subject, r.values),
        "sender": services.sender_name(c),
        "kind_label": c.get_kind_display(),
        "sent_at": c.sent_at,
        "channel": r.channel,
    }
    if full:
        data["body"] = text.fill(c.body, r.values)
        data["attachments"] = [attachment_data(a, f"{base}{c.pk}/") for a in c.attachments.all()]
    return data


class PortalCircularListView(PortalCircularMixin, APIView):
    def get(self, request, access_id: int):
        base = f"/api/portal/{access_id}/circulars/"
        return Response([portal_item(r, base) for r in self.received()[:200]])


class PortalCircularDetailView(PortalCircularMixin, APIView):
    def get(self, request, access_id: int, pk: int):
        base = f"/api/portal/{access_id}/circulars/"
        return Response(portal_item(self.get_received(pk), base, full=True))


class PortalCircularAttachmentView(PortalCircularMixin, APIView):
    def get(self, request, access_id: int, pk: int, att_id: int):
        r = self.get_received(pk)
        att = get_object_or_404(CircularAttachment, circular=r.circular, pk=att_id)
        return _file_response(att, request)


class PortalCircularSettingsView(PortalCircularMixin, APIView):
    """Informationen per Mail: GET Stand · PUT ``{"info_opt_out": true|false}``."""

    def membership(self) -> Membership:
        return Membership.objects.get(pk=self.access.membership_id)

    def get(self, request, access_id: int):
        m = self.membership()
        return Response({"info_opt_out": m.info_opt_out_at is not None, "since": m.info_opt_out_at})

    @transaction.atomic
    def put(self, request, access_id: int):
        m = self.membership()
        wanted = bool(request.data.get("info_opt_out"))
        set_opt_out(m, wanted, request.user, self.club)
        return Response({"info_opt_out": m.info_opt_out_at is not None, "since": m.info_opt_out_at})


def set_opt_out(m: Membership, wanted: bool, user, club) -> None:
    if wanted == (m.info_opt_out_at is not None):
        return
    m.info_opt_out_at = timezone.now() if wanted else None
    m.save(update_fields=["info_opt_out_at", "updated_at"])
    record(
        club,
        user,
        "update",
        m,
        {
            "Informationen per E-Mail": ["erhalten", "abbestellt"]
            if wanted
            else ["abbestellt", "erhalten"]
        },
        person=m.person,
    )


# --- Abmeldelink ohne Anmeldung ---


class PublicOptOutView(APIView):
    """GET: Stand · POST ``{"info_opt_out": true|false}`` (Standard: abmelden)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get_membership(self, token: str) -> Membership:
        pk = services.opt_out_membership(token)
        if pk is None:
            raise NotFound("Dieser Link ist ungültig.")
        with rls_bypass():
            m = (
                Membership.objects.select_related("person", "organization")
                .filter(pk=pk, purged_at__isnull=True)
                .first()
            )
        if m is None:
            raise NotFound("Dieser Link ist ungültig.")
        return m

    def data(self, m: Membership) -> dict:
        return {
            "club": m.organization.name,
            "imprint_key": ensure_imprint(m.organization).public_key,
            "first_name": m.person.first_name,
            "info_opt_out": m.info_opt_out_at is not None,
        }

    def get(self, request, token: str):
        return Response(self.data(self.get_membership(token)))

    @transaction.atomic
    def post(self, request, token: str):
        m = self.get_membership(token)
        wanted = request.data.get("info_opt_out", True)
        with rls_bypass():
            set_opt_out(m, bool(wanted), None, m.organization)
        return Response(self.data(m))


# --- Bestätigungslink aus der Mail an den Absender eines Verteilers ---


class PublicConfirmView(APIView):
    """GET: was verschickt würde · POST ``{"action": "send"|"discard"}``.

    Erst der Klick auf „Jetzt versenden“ (POST) versendet; das bloße Öffnen des
    Links (Virenscanner im Mailprogramm laden Links vorab) tut nichts.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get_entry(self, token: str) -> InboundMail:
        from . import inbound

        entry = inbound.entry_from_token(token)
        if entry is None:
            raise NotFound("Dieser Link ist ungültig oder abgelaufen.")
        return entry

    def data(self, entry: InboundMail) -> dict:
        from . import inbound

        ml = entry.mailing_list
        out: dict = {
            "status": entry.status,
            "status_label": entry.get_status_display(),
            "subject": entry.subject,
            "list": ml.name if ml else "",
            "address": inbound.address_of(ml) if ml else "",
            "organization": entry.organization.name if entry.organization else "",
            "body": "",
            "attachments": [],
            "counts": None,
        }
        circular = entry.circular
        if circular is not None:
            with rls_bypass():
                out["body"] = circular.body
                out["attachments"] = [a.name for a in circular.attachments.all()]
                if entry.status == InboundMail.Status.WAITING and circular.is_draft:
                    out["counts"] = rcp.select(circular).counts()
                elif not circular.is_draft:
                    out["counts"] = sent_counts(circular)
        return out

    def get(self, request, token: str):
        return Response(self.data(self.get_entry(token)))

    def post(self, request, token: str):
        from . import inbound

        entry = self.get_entry(token)
        action = request.data.get("action", "send")
        if action == "discard":
            inbound.discard(entry)
        elif action == "send":
            counts = inbound.confirm(entry)
            with rls_bypass():
                record(
                    entry.organization,
                    entry.user,
                    "update",
                    entry.circular,
                    {"versendet über Verteiler": [None, sent_text(counts)]},
                )
        else:
            raise serializers.ValidationError("Unbekannte Aktion.")
        return Response(self.data(self.get_entry(token)))
