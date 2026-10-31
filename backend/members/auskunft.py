"""Auskunft für ein einzelnes Mitglied (Art. 15 DSGVO, Gesamtaudit 31.10.b, Frage 7).

Ein ZIP nur mit den Daten dieser Person in diesem Verein: Akte, Zusatzfelder, Rechnungen
(mit PDF), Lastschriftmandate, Zuwendungen, versandte Mails, Zugang und Geräte der App,
Rückmeldungen zu Terminen, Verbund-Empfänger und das Änderungsprotokoll. Daten anderer
Personen (z. B. wer etwas geändert hat) stehen nicht darin.
"""

from __future__ import annotations

import io
import json
import zipfile

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .models import Membership

README = """Auskunft über gespeicherte Daten (Art. 15 DSGVO)

Person: {name}
Verein: {org}
Erstellt: {when}

Inhalt
- akte.json: Stammdaten, Kontaktdaten, Mitgliedschaftszeiten, Mitgliedsarten, Zugehörigkeit zu
  Untereinheiten, Ämter, Ehrungen, Verbandsmeldung
- zusatzfelder.json: vom Verein festgelegte zusätzliche Angaben
- rechnungen.json / rechnungen.pdf: Rechnungen an die Person mit Zahlungen
- mandate.json: SEPA-Lastschriftmandate
- zuwendungen.json: Spenden und Zuwendungen
- mails.json: E-Mails, die der Verein über HUBIplan an die Person geschickt hat
- zugang.json: Mitgliederzugang, Anmeldekonto und verbundene Geräte der App
- termine.json: Zu- und Absagen zu Terminen
- verbund.json: Meldungen an andere HUBIplan-Instanzen (z. B. Dachverband)
- protokoll.json: Änderungen an den Daten der Person (ohne Namen der Bearbeitenden)
- foto.*: hinterlegtes Mitgliederfoto (falls vorhanden)

Zwecke: Mitgliederverwaltung, Beiträge und Kasse, Information der Mitglieder, Termine.
Empfänger: Vorstand und berechtigte Personen des Vereins; Meldungen an den Dachverband nur,
soweit die Mitgliedsart dafür vorgesehen ist. Rechnungen und Buchungen werden wegen der
steuerlichen Aufbewahrungsfrist aufbewahrt.
"""

# Felder, die nie in eine Auskunft gehören (Prüfsummen, Schlüssel, interne Verweise)
SECRET = {"token_hash", "previous_token_hash", "retired_hashes", "admin_token_hash"}


def _row(obj, exclude: set[str] | frozenset = frozenset()) -> dict:
    data = {}
    for field in obj._meta.concrete_fields:
        if field.name in exclude or field.name in SECRET:
            continue
        if isinstance(field, models.FileField):
            continue
        if isinstance(field, models.ForeignKey):
            data[field.attname] = getattr(obj, field.attname)
            continue
        data[field.name] = field.value_from_object(obj)
    return data


def _dump(value) -> str:
    return json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2)


def _org_ids(org) -> list[int]:
    """Verein und alle Einheiten darunter (Mails und Protokoll der Untereinheiten)."""
    from organizations.models import Organization

    ids, level = [org.pk], [org.pk]
    while level:
        level = list(Organization.objects.filter(parent_id__in=level).values_list("pk", flat=True))
        ids += level
    return ids


def _emails(membership: Membership, org) -> set[str]:
    from members.models import ContactDetails
    from portal.models import PortalAccess

    found = set()
    for c in ContactDetails.objects.filter(person=membership.person):
        if c.email:
            found.add(c.email.lower())
    for access in PortalAccess.objects.filter(membership=membership).select_related("user"):
        if access.user and access.user.email:
            found.add(access.user.email.lower())
    return found


def _invoices(membership: Membership):
    from billing.models import Invoice

    return list(
        Invoice.objects.filter(Q(membership=membership) | Q(lines__membership=membership))
        .distinct()
        .prefetch_related("lines", "payments")
        .order_by("date", "pk")
    )


def _invoice_rows(invoices) -> list[dict]:
    rows = []
    for inv in invoices:
        row = _row(inv, {"created_by"})
        row["positionen"] = [_row(line) for line in inv.lines.all()]
        row["zahlungen"] = [_row(p, {"created_by", "booking"}) for p in inv.payments.all()]
        rows.append(row)
    return rows


def build(membership: Membership, org) -> bytes:
    """ZIP mit allen Daten der Person in diesem Verein."""
    from audit.models import AuditEntry
    from billing.models import Mandate
    from customfields.models import FieldValue
    from devices.models import Device
    from events.models import EventResponse
    from finance.models import Donation
    from outbox.models import OutgoingMail
    from peering.models import RemoteMember
    from portal.models import PortalAccess

    from .serializers import member_detail

    person = membership.person
    org_ids = _org_ids(org)
    files: dict[str, str | bytes] = {}

    akte = member_detail(membership, org)
    for key in ("exit_reasons", "contact_shared", "photo", "other_memberships"):
        akte.pop(key, None)
    files["akte.json"] = _dump(akte)

    values = FieldValue.objects.filter(person=person, organization_id__in=org_ids)
    files["zusatzfelder.json"] = _dump(
        [
            {"feld": v.definition.label, "wert": v.value, "geändert": v.updated_at}
            for v in values.select_related("definition")
        ]
    )

    invoices = _invoices(membership)
    files["rechnungen.json"] = _dump(_invoice_rows(invoices))
    issued = [i for i in invoices if i.number]
    if issued:
        from billing import pdf

        files["rechnungen.pdf"] = pdf.render(issued)
    files["mandate.json"] = _dump([_row(m) for m in Mandate.objects.filter(membership=membership)])
    files["zuwendungen.json"] = _dump(
        [_row(d, {"created_by"}) for d in Donation.objects.filter(membership=membership)]
    )

    emails = _emails(membership, org)
    mails = []
    if emails:
        match = Q()
        for address in emails:
            match |= Q(to__icontains=address)
        for mail in OutgoingMail.objects.filter(match, organization_id__in=org_ids):
            # Nur Mails an diese Person (kein Teiltreffer in einer längeren Adresse)
            to = {a.strip().lower() for a in mail.to.replace(";", ",").split(",")}
            if to & emails:
                mails.append(
                    {
                        "an": mail.to,
                        "betreff": mail.subject,
                        "text": mail.body,
                        "anhänge": [a.get("name") for a in mail.attachments or []],
                        "status": mail.get_status_display(),
                        "erstellt": mail.created_at,
                    }
                )
    files["mails.json"] = _dump(mails)

    access_rows = []
    for access in PortalAccess.objects.filter(membership=membership).select_related("user"):
        user = access.user
        devices = Device.objects.filter(user=user) if user else Device.objects.none()
        access_rows.append(
            {
                "zugang_seit": access.created_at,
                "anmelde_email": user.email if user else None,
                "letzte_anmeldung": user.last_login if user else None,
                "geräte": [
                    {
                        "name": d.name,
                        "plattform": d.platform,
                        "app_version": d.app_version,
                        "verbunden": d.created_at,
                        "zuletzt_gesehen": d.last_seen_at,
                        "abgemeldet": d.revoked_at,
                        "benachrichtigungen": d.push_kind,
                    }
                    for d in devices
                ],
            }
        )
    files["zugang.json"] = _dump(access_rows)

    files["termine.json"] = _dump(
        [
            {"termin": r.event.title, **_row(r, {"event", "membership", "organization"})}
            for r in EventResponse.objects.filter(membership=membership).select_related("event")
        ]
    )

    files["verbund.json"] = _dump(
        [
            {
                "gegenstelle": rm.coupling.peer.base_url,
                "einheit": str(rm.coupling.remote_uuid),
                "verbandsnummer": rm.number,
                "status": rm.get_status_display(),
                "stand": rm.updated_at,
            }
            for rm in RemoteMember.objects.filter(membership=membership).select_related(
                "coupling__peer"
            )
        ]
    )

    entries = AuditEntry.objects.filter(organization_id__in=org_ids, person_id=person.pk)
    files["protokoll.json"] = _dump(
        [
            {
                "zeit": e.timestamp,
                "aktion": e.get_action_display(),
                "objekt": e.object_repr,
                "änderungen": e.changes,
            }
            for e in entries.order_by("timestamp")
        ]
    )

    photo = membership.photos.filter(status="approved").first()
    if photo is not None and photo.image:
        try:
            with photo.image.open("rb") as fh:
                suffix = photo.image.name.rsplit(".", 1)[-1] if "." in photo.image.name else "jpg"
                files[f"foto.{suffix}"] = fh.read()
        except OSError:
            pass

    files["LIESMICH.txt"] = README.format(
        name=f"{person.first_name} {person.last_name}".strip(),
        org=org.name,
        when=timezone.localtime().strftime("%d.%m.%Y %H:%M"),
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()
