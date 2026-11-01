"""Rundschreiben zur Weitergabe nach unten (P10).

Ein Rundschreiben des Dachverbands an „Mitglieder“ erreicht Vereine auf anderen
Instanzen, ohne dass der Dachverband Mailadressen bekommt: Das Paket enthält
Betreff, Text (mit Platzhaltern), Anhänge und die Zielgruppe. Die Instanz des
Vereins legt daraus ein eigenes Rundschreiben an („im Auftrag von …“) und
verschickt es selbst, automatisch oder nach Freigabe durch den Vorstand. Zurück
kommt nur die Zahl der versandten und fehlgeschlagenen Mails.
"""

from __future__ import annotations

import base64

from django.core.files.base import ContentFile
from django.db import transaction

from circulars.models import MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS
from core import virenscan

from .models import Coupling, RemoteCircular, RemoteState
from .packets import DOWN, Packet, register

KEY = "circulars"
ATTACHMENTS_LIMIT = 10 * 1024 * 1024


# --- oben ---


def remote_targets(circular) -> list[Coupling]:
    """Kopplungen zu fernen Vereinen, an die ein Rundschreiben weitergegeben wird."""
    from circulars.models import Circular
    from circulars.recipients import as_ints, nobody_selected

    if circular.audience != Circular.Audience.MEMBERS or circular.department_id:
        return []
    filters = circular.filters or {}
    if nobody_selected(filters):
        return []
    wanted = set(as_ints(filters.get("clubs")))
    result = []
    for coupling in Coupling.objects.filter(
        local_unit_id=circular.organization_id,
        direction=Coupling.Direction.CHILD,
        state=Coupling.State.ACTIVE,
    ).select_related("remote_unit"):
        if not coupling.level(KEY):
            continue
        if wanted and coupling.remote_unit_id not in wanted:
            continue
        result.append(coupling)
    return result


def _attachments(circular) -> list[dict]:
    items, total = [], 0
    for a in circular.attachments.all():
        content = None
        try:
            a.file.open("rb")
            content = a.file.read()
        except OSError:
            continue
        finally:
            try:
                a.file.close()
            except OSError:
                pass
        total += len(content)
        if total > ATTACHMENTS_LIMIT:
            break
        items.append({"name": a.name, "data": base64.b64encode(content).decode()})
    return items


def forward(circular) -> int:
    """Beim Versand oben: an alle passenden fernen Vereine weitergeben."""
    from . import services

    targets = remote_targets(circular)
    if not targets:
        return 0
    attachments = _attachments(circular)
    for coupling in targets:
        rc = RemoteCircular.objects.create(
            coupling=coupling, circular=circular, subject=circular.subject[:200]
        )
        services.enqueue(
            coupling,
            "circular.forward",
            {
                "uid": str(rc.uid),
                "subject": circular.subject,
                "body": circular.body,
                "kind": circular.kind,
                "reply_to": circular.reply_to,
                "reported_only": bool((circular.filters or {}).get("reported")),
                "attachments": attachments,
            },
        )
    return len(targets)


def receive_report(coupling: Coupling, data: dict) -> None:
    rc = RemoteCircular.objects.filter(coupling=coupling, uid=str(data.get("uid") or "")).first()
    if rc is None:
        return
    status = str(data.get("status") or "")
    if status in RemoteCircular.Status.values:
        rc.status = status
    report = {}
    for key in ("mail", "sent", "failed", "letter"):
        try:
            report[key] = max(0, int(data.get(key) or 0))
        except (TypeError, ValueError):
            report[key] = 0
    rc.report = report
    rc.save(update_fields=["status", "report", "updated_at"])


# --- unten ---


def _file_name(value) -> str:
    """Dateiname der Gegenseite bereinigen: ohne Pfad und Steuerzeichen, immer .pdf."""
    name = str(value or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*').strip(" .")
    if not name:
        name = "Anhang"
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return name[-200:]


def _reply_to(coupling: Coupling, value) -> str:
    """Antwortadresse nur, wenn sie zu den gemeldeten Adressen der fernen Einheit gehört."""
    address = str(value or "").strip()[:254]
    if not address:
        return ""
    known = {str(coupling.remote_unit.contact_email or "").lower()}
    board = RemoteState.objects.filter(coupling=coupling, key="board").first()
    for role in ((board.data or {}).get("roles") or []) if board else []:
        known.add(str(role.get("email") or "").lower())
    known.discard("")
    return address if address.lower() in known else ""


def receive_forward(coupling: Coupling, data: dict) -> None:
    from circulars.models import Circular, CircularAttachment
    from members.models import MemberType

    from . import services

    if coupling.direction != Coupling.Direction.PARENT:
        return
    uid = str(data.get("uid") or "")
    if RemoteCircular.objects.filter(coupling=coupling, uid=uid).exists():
        return
    club = coupling.local_unit
    sender = coupling.remote_unit.name
    subject = str(data.get("subject") or "").strip()[:200]
    body = str(data.get("body") or "")[:20000]
    filters = {}
    if data.get("reported_only"):
        filters["member_types"] = list(
            MemberType.objects.filter(organization=club, reported=True).values_list("pk", flat=True)
        )
    kind = data.get("kind") if data.get("kind") in Circular.Kind.values else Circular.Kind.INFO
    circular = Circular.objects.create(
        organization=club,
        kind=kind,
        audience=Circular.Audience.MEMBERS,
        subject=subject,
        body=f"Im Auftrag von {sender}:\n\n{body}",
        reply_to=_reply_to(coupling, data.get("reply_to")),
        filters=filters,
    )
    total = 0
    for item in (data.get("attachments") or [])[:MAX_ATTACHMENTS]:
        # Wie ein Upload behandeln: nur PDF, dieselben Grenzen wie beim Hochladen
        try:
            content = base64.b64decode(str(item.get("data") or ""), validate=True)
        except (ValueError, TypeError, AttributeError):
            continue
        if not content.startswith(b"%PDF-") or len(content) > MAX_ATTACHMENT_BYTES:
            continue
        if total + len(content) > 2 * MAX_ATTACHMENT_BYTES:
            break
        name = _file_name(item.get("name"))
        if not virenscan.inbound_ok(content, name, "Rundschreiben aus dem Verbund"):
            continue
        total += len(content)
        CircularAttachment.objects.create(
            organization=club,
            circular=circular,
            file=ContentFile(content, name=name),
            name=name,
            size=len(content),
        )
    rc = RemoteCircular.objects.create(
        coupling=coupling,
        uid=uid,
        circular=circular,
        subject=subject,
        status=RemoteCircular.Status.DRAFT,
    )
    if (coupling.options or {}).get("circulars_auto"):
        transaction.on_commit(lambda: _send_automatically(rc.pk))
    else:
        services._notify_circular(coupling, circular)
        _report(rc)


def _send_automatically(rc_id: int) -> None:
    from circulars import services as circular_services
    from core.tenancy import rls_bypass

    with rls_bypass(), transaction.atomic():
        rc = RemoteCircular.objects.select_related("coupling", "circular").get(pk=rc_id)
        try:
            circular_services.start_sending(rc.circular, None)
        except Exception:  # noqa: BLE001 - dann bleibt es ein Entwurf
            from . import services

            services._notify_circular(rc.coupling, rc.circular)
            _report(rc)


def _report(rc: RemoteCircular) -> None:
    from circulars.models import CircularRecipient

    from . import services

    counts = {"mail": 0, "sent": 0, "failed": 0, "letter": 0}
    status = RemoteCircular.Status.DRAFT
    circular = rc.circular
    if circular is None:
        status = RemoteCircular.Status.DISCARDED
    elif not circular.is_draft:
        status = RemoteCircular.Status.SENT
        for value in circular.recipients.values_list("status", flat=True):
            if value == CircularRecipient.Status.SENT:
                counts["sent"] += 1
            elif value == CircularRecipient.Status.FAILED:
                counts["failed"] += 1
            elif value == CircularRecipient.Status.LETTER:
                counts["letter"] += 1
            if value != CircularRecipient.Status.LETTER:
                counts["mail"] += 1
    if rc.status == status and rc.report == counts:
        return
    rc.status = status
    rc.report = counts
    rc.save(update_fields=["status", "report", "updated_at"])
    if rc.coupling.is_open:
        services.enqueue(
            rc.coupling, "circular.report", {"uid": str(rc.uid), "status": status, **counts}
        )


def after_sending(circular) -> None:
    """Unten: Nach dem Versand eines weitergegebenen Rundschreibens die Zahlen melden."""
    rc = RemoteCircular.objects.filter(circular=circular).select_related("coupling").first()
    if rc is not None and rc.coupling.direction == Coupling.Direction.PARENT:
        with transaction.atomic():
            _report(rc)


def circular_data(rc: RemoteCircular) -> dict:
    return {
        "id": rc.id,
        "subject": rc.subject,
        "status": rc.status,
        "status_label": rc.get_status_display(),
        "report": rc.report,
        "circular_id": rc.circular_id,
        "created_at": rc.created_at,
    }


register(
    Packet(
        KEY,
        "Rundschreiben zur Weitergabe an die Mitglieder der Einheit darunter",
        (DOWN,),
        personal="keiner (die Einheit darunter verschickt selbst)",
        default="on",
    )
)
