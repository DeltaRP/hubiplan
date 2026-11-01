"""SEPA-Basislastschrift: Mandate, Lastschriftläufe und die Datei pain.008 für die Bank."""

from __future__ import annotations

import datetime
import re
import unicodedata
import uuid
from decimal import Decimal
from xml.etree import ElementTree as ET

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext

from finance.models import iban_valid

from .models import DebitItem, DebitRun, Invoice, Mandate
from .services import ZERO, add_payment, settings_for

NS = "urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"
# Mandate verfallen, wenn 36 Monate keine Lastschrift darauf eingezogen wurde
EXPIRY_MONTHS = 36

_TRANSLIT = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}
)
_ALLOWED = re.compile(r"[^A-Za-z0-9/?:().,'+\- ]")

# Ort der Lastschrift-Einstellungen in der Oberfläche (für Fehlermeldungen)
SETTINGS_PATH = "Finanzen › Einrichtung › Rechnung & Zahlung"


def sepa_text(text: str, length: int) -> str:
    """Auf den SEPA-Zeichensatz bringen (Umlaute umschreiben, Rest weglassen)."""
    text = (text or "").translate(_TRANSLIT)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = _ALLOWED.sub(" ", text.replace("\n", " "))
    return re.sub(r"\s+", " ", text).strip()[:length]


def clean_iban(value: str) -> str:
    return (value or "").replace(" ", "").upper()


def creditor_id_valid(value: str) -> bool:
    """Gläubiger-ID prüfen, z. B. DE98ZZZ09999999999 (Prüfziffer wie bei der IBAN)."""
    value = (value or "").replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{3}[A-Z0-9]{1,28}", value):
        return False
    national = value[7:] + value[:2] + "00"
    digits = "".join(str(int(c, 36)) for c in national)
    return 98 - int(digits) % 97 == int(value[2:4])


def mandate_expired(mandate: Mandate, on: datetime.date | None = None) -> bool:
    on = on or timezone.localdate()
    last = mandate.last_used_on or mandate.signed_on
    # Taggenau: 36 volle Monate nach dem letzten Einzug (31.01.2023 → ab 31.01.2026)
    return on >= last + relativedelta(months=EXPIRY_MONTHS)


# Prüfliste: so viele Monate vor dem Verfall auf ein Mandat hinweisen
EXPIRY_WARN_MONTHS = 3


def expiring_soon(org, on: datetime.date | None = None) -> int:
    """Aktive Mandate, die in den nächsten Monaten verfallen, weil nichts eingezogen wurde."""
    on = on or timezone.localdate()
    count = 0
    for mandate in Mandate.objects.filter(organization=org, status=Mandate.Status.ACTIVE).only(
        "last_used_on", "signed_on"
    ):
        last = mandate.last_used_on or mandate.signed_on
        expires = last + relativedelta(months=EXPIRY_MONTHS)
        if expires - relativedelta(months=EXPIRY_WARN_MONTHS) <= on < expires:
            count += 1
    return count


def mandate_usable(mandate: Mandate, on: datetime.date | None = None) -> bool:
    return mandate.status == Mandate.Status.ACTIVE and not mandate_expired(mandate, on)


def next_reference(org, membership=None, club=None) -> str:
    """Mandatsreferenz: MITGL-<Mitgliedsnummer>-<n> bzw. VEREIN-<Nr>-<n>."""
    if membership is not None:
        key = membership.club_number or str(membership.pk)
        prefix = f"MITGL-{sepa_text(key, 20).replace(' ', '')}"
    else:
        prefix = f"VEREIN-{club.pk}"
    n = Mandate.objects.filter(organization=org, reference__startswith=prefix + "-").count() + 1
    while Mandate.objects.filter(organization=org, reference=f"{prefix}-{n}").exists():
        n += 1
    return f"{prefix}-{n}"


def validate_mandate_data(holder: str, iban: str, bic: str) -> dict:
    errors = {}
    iban = clean_iban(iban)
    bic = (bic or "").replace(" ", "").upper()
    if not holder.strip():
        errors["holder"] = "Bitte den Kontoinhaber angeben."
    if not iban_valid(iban):
        errors["iban"] = "Die IBAN ist ungültig."
    elif not iban.startswith(SEPA_COUNTRIES):
        errors["iban"] = "Die IBAN gehört nicht zum SEPA-Raum."
    if bic and not re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?", bic):
        errors["bic"] = "Der BIC ist ungültig."
    if errors:
        raise ValidationError(errors)
    return {"holder": holder.strip()[:70], "iban": iban, "bic": bic}


SEPA_COUNTRIES = tuple(
    "AT BE BG CH CY CZ DE DK EE ES FI FR GB GI GR HR HU IE IS IT LI LT LU LV MC MT NL NO PL "
    "PT RO SE SI SK SM VA AD".split()
)


def create_mandate(org, *, membership=None, club=None, signed_on, source, user, **data) -> Mandate:
    clean = validate_mandate_data(data.get("holder", ""), data.get("iban", ""), data.get("bic", ""))
    # Ein Zahler hat höchstens ein gültiges Mandat: ein neues ersetzt das alte
    payer = Q(membership=membership) if membership is not None else Q(club=club)
    Mandate.objects.filter(payer, organization=org, status=Mandate.Status.ACTIVE).update(
        status=Mandate.Status.REVOKED, revoked_on=timezone.localdate()
    )
    return Mandate.objects.create(
        organization=org,
        membership=membership,
        club=club,
        reference=next_reference(org, membership, club),
        signed_on=signed_on,
        source=source,
        created_by=user,
        **clean,
    )


def revoke(mandate: Mandate, on: datetime.date | None = None) -> None:
    if mandate.status != Mandate.Status.ACTIVE:
        raise ValidationError(gettext("Das Mandat ist schon widerrufen."))
    mandate.status = Mandate.Status.REVOKED
    mandate.revoked_on = on or timezone.localdate()
    mandate.save(update_fields=["status", "revoked_on"])


def mandate_text(org, creditor_id: str, reference: str) -> str:
    return (
        f"Ich ermächtige {org.name}, Zahlungen von meinem Konto mittels Lastschrift "
        f"einzuziehen. Zugleich weise ich mein Kreditinstitut an, die von {org.name} auf "
        f"mein Konto gezogenen Lastschriften einzulösen. Hinweis: Ich kann innerhalb von "
        f"acht Wochen, beginnend mit dem Belastungsdatum, die Erstattung des belasteten "
        f"Betrages verlangen. Es gelten dabei die mit meinem Kreditinstitut vereinbarten "
        f"Bedingungen. Gläubiger-Identifikationsnummer: {creditor_id or '(noch nicht hinterlegt)'}"
        f" · Mandatsreferenz: {reference}"
    )


# --- Zahler und Vorschläge ---


def payer_mandate(invoice: Invoice, on: datetime.date | None = None) -> Mandate | None:
    if invoice.recipient_kind == Invoice.Recipient.MEMBER and invoice.membership_id:
        payer = Q(membership_id=invoice.membership_id)
    elif invoice.recipient_kind == Invoice.Recipient.CLUB and invoice.club_id:
        payer = Q(club_id=invoice.club_id)
    else:
        return None
    mandate = (
        Mandate.objects.filter(payer, organization=invoice.organization)
        .filter(status=Mandate.Status.ACTIVE)
        .order_by("-signed_on", "-pk")
        .first()
    )
    return mandate if mandate and mandate_usable(mandate, on) else None


def pending_invoice_ids(org) -> set[int]:
    """Rechnungen, die schon in einem noch nicht gebuchten Lauf stecken."""
    return set(
        DebitItem.objects.filter(organization=org, run__status=DebitRun.Status.CREATED).values_list(
            "invoice_id", flat=True
        )
    )


def proposals(org, on: datetime.date | None = None) -> list[tuple[Invoice, Mandate]]:
    pending = pending_invoice_ids(org)
    result = []
    invoices = (
        Invoice.objects.filter(organization=org, status=Invoice.Status.OPEN)
        .filter(recipient_kind__in=[Invoice.Recipient.MEMBER, Invoice.Recipient.CLUB])
        .exclude(pk__in=pending)
        .select_related("organization", "membership__person", "club")
        .order_by("due_date", "number")
    )
    for invoice in invoices:
        if invoice.outstanding <= 0:
            continue
        mandate = payer_mandate(invoice, on)
        if mandate is not None:
            result.append((invoice, mandate))
    return result


def earliest_collection(org, today: datetime.date | None = None) -> datetime.date:
    today = today or timezone.localdate()
    days = max(settings_for(org).prenotification_days, 2)
    return today + datetime.timedelta(days=days)


# --- Lastschriftlauf ---


def create_run(org, invoice_ids: list[int], collection_date: datetime.date, user) -> DebitRun:
    cfg = settings_for(org)
    errors = {}
    if not creditor_id_valid(cfg.creditor_id):
        errors["creditor_id"] = (
            f"Bitte unter {SETTINGS_PATH} eine gültige Gläubiger-Identifikationsnummer eintragen."
        )
    account = cfg.account
    if account is None or not account.iban:
        errors["account"] = f"Bitte unter {SETTINGS_PATH} ein Konto mit IBAN für den Einzug wählen."
    if cfg.category is None:
        errors["category"] = f"Bitte unter {SETTINGS_PATH} eine Kategorie für Zahlungen wählen."
    earliest = earliest_collection(org)
    if collection_date < earliest:
        errors["collection_date"] = (
            f"Frühestens am {earliest:%d.%m.%Y}: Die Zahler müssen "
            f"{cfg.prenotification_days} Tage vorher benachrichtigt werden."
        )
    if collection_date.weekday() >= 5:
        errors["collection_date"] = "Der Einzug muss auf einen Bankarbeitstag fallen."
    if errors:
        raise ValidationError(errors)
    # Gewählte Rechnungen sperren (in fester Reihenfolge) und danach erst prüfen: Eine
    # gleichzeitige Zahlung, Stornierung oder ein zweiter Lauf mit derselben Rechnung
    # wartet so auf diesen Lauf bzw. dieser auf sie und sieht dann deren Ergebnis.
    list(
        Invoice.objects.select_for_update()
        .filter(organization=org, pk__in=invoice_ids)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    chosen = [(i, m) for i, m in proposals(org, collection_date) if i.pk in set(invoice_ids)]
    if not chosen:
        raise ValidationError(
            gettext("Bitte mindestens eine Rechnung mit gültigem Mandat auswählen.")
        )
    run = DebitRun.objects.create(
        organization=org,
        collection_date=collection_date,
        account=account,
        message_id=f"HUBI-{uuid.uuid4().hex[:24].upper()}",
        created_by=user,
    )
    used = set(
        DebitItem.objects.filter(organization=org, run__status=DebitRun.Status.BOOKED)
        .values_list("mandate_id", flat=True)
        .distinct()
    )
    total = ZERO
    for invoice, mandate in chosen:
        first = mandate.last_used_on is None and mandate.pk not in used
        DebitItem.objects.create(
            organization=org,
            run=run,
            invoice=invoice,
            mandate=mandate,
            amount=invoice.outstanding,
            sequence=DebitItem.Sequence.FIRST if first else DebitItem.Sequence.RECURRING,
            end_to_end_id=sepa_text(f"{invoice.display_number}-{run.pk}", 35),
        )
        total += invoice.outstanding
    run.total = total
    run.save(update_fields=["total"])
    return run


def run_problems(run: DebitRun) -> list[str]:
    """Was einen noch nicht gebuchten Lauf ungültig macht (Gesamtaudit B-V01).

    Zwischen Erstellen und Einreichen bei der Bank kann ein Mandat widerrufen oder
    eine Rechnung anders bezahlt bzw. storniert werden. Dann darf die alte Datei
    nicht mehr heraus: lieber den Lauf verwerfen und neu erstellen."""
    if run.status != DebitRun.Status.CREATED:
        return []
    problems = []
    for item in run.items.select_related("invoice", "mandate").order_by("pk"):
        invoice, mandate = item.invoice, item.mandate
        if mandate.status != Mandate.Status.ACTIVE:
            problems.append(f"{invoice.display_number}: Mandat {mandate.reference} widerrufen")
        elif mandate_expired(mandate, run.collection_date):
            problems.append(f"{invoice.display_number}: Mandat {mandate.reference} verfallen")
        if invoice.status != Invoice.Status.OPEN:
            problems.append(f"{invoice.display_number}: Rechnung {invoice.get_status_display()}")
        elif invoice.outstanding < item.amount:
            problems.append(f"{invoice.display_number}: inzwischen teilweise bezahlt")
    return problems


def cancel_run(run: DebitRun) -> None:
    # Sperren und frisch lesen: ein gleichzeitig gebuchter Lauf wird nicht verworfen
    run.status = (
        DebitRun.objects.select_for_update().values_list("status", flat=True).get(pk=run.pk)
    )
    if run.status != DebitRun.Status.CREATED:
        raise ValidationError(gettext("Nur noch nicht gebuchte Läufe lassen sich verwerfen."))
    run.status = DebitRun.Status.CANCELLED
    run.save(update_fields=["status"])


def book_run(run: DebitRun, user) -> int:
    """Nach dem Einzug: Zahlungen und Buchungen in der Kasse anlegen."""
    # Sperre gegen gleichzeitiges zweites Buchen desselben Laufs
    locked = DebitRun.objects.select_for_update().get(pk=run.pk)
    if locked.status != DebitRun.Status.CREATED:
        raise ValidationError(gettext("Der Lauf ist schon gebucht oder verworfen."))
    items = list(run.items.select_related("invoice__organization", "mandate"))
    # Gebucht wird genau der Betrag aus der Bankdatei. Passt eine Rechnung nicht mehr
    # dazu, lieber gar nichts buchen als Bank und Kasse auseinanderlaufen lassen.
    problems = [
        item.invoice.display_number
        for item in items
        if item.invoice.status != Invoice.Status.OPEN or item.invoice.outstanding < item.amount
    ]
    if problems:
        raise ValidationError(
            gettext(
                "Diese Rechnungen passen nicht mehr zum Betrag in der Lastschriftdatei "
                "(schon bezahlt oder storniert): {x}. Bitte prüfen; der Lauf wurde nicht "
                "gebucht."
            ).format(x=", ".join(problems))
        )
    booked = 0
    for item in items:
        invoice = item.invoice
        payment = add_payment(
            invoice,
            date=run.collection_date,
            amount=item.amount,
            method="debit",
            account=run.account,
            user=user,
            debit=True,
        )
        item.payment = payment
        item.save(update_fields=["payment"])
        mandate = item.mandate
        if not mandate.last_used_on or mandate.last_used_on < run.collection_date:
            mandate.last_used_on = run.collection_date
            mandate.save(update_fields=["last_used_on"])
        booked += 1
    run.status = DebitRun.Status.BOOKED
    run.booked_at = timezone.now()
    run.save(update_fields=["status", "booked_at"])
    return booked


# --- Datei für die Bank ---


def _sub(parent, tag: str, text: str | None = None, **attrs) -> ET.Element:
    el = ET.SubElement(parent, tag, attrs)
    if text is not None:
        el.text = text
    return el


def _agent(parent, tag: str, bic: str) -> None:
    fin = _sub(_sub(parent, tag), "FinInstnId")
    if bic:
        _sub(fin, "BICFI", bic)
    else:
        _sub(_sub(fin, "Othr"), "Id", "NOTPROVIDED")


def _amount(value: Decimal) -> str:
    return f"{value:.2f}"


def pain008(run: DebitRun) -> bytes:
    """SEPA-XML (pain.008.001.08, Basislastschrift CORE) für den Upload ins Online-Banking."""
    org = run.organization
    cfg = settings_for(org)
    items = list(run.items.select_related("invoice", "mandate").order_by("sequence", "pk"))
    ET.register_namespace("", NS)
    doc = ET.Element("Document", xmlns=NS)
    root = _sub(doc, "CstmrDrctDbtInitn")
    head = _sub(root, "GrpHdr")
    _sub(head, "MsgId", run.message_id)
    _sub(head, "CreDtTm", timezone.localtime(run.created_at).strftime("%Y-%m-%dT%H:%M:%S"))
    _sub(head, "NbOfTxs", str(len(items)))
    _sub(head, "CtrlSum", _amount(sum((i.amount for i in items), ZERO)))
    _sub(_sub(head, "InitgPty"), "Nm", sepa_text(org.name, 70))

    for seq in (DebitItem.Sequence.FIRST, DebitItem.Sequence.RECURRING):
        group = [i for i in items if i.sequence == seq]
        if not group:
            continue
        info = _sub(root, "PmtInf")
        _sub(info, "PmtInfId", sepa_text(f"{run.message_id}-{seq}", 35))
        _sub(info, "PmtMtd", "DD")
        _sub(info, "BtchBookg", "true")
        _sub(info, "NbOfTxs", str(len(group)))
        _sub(info, "CtrlSum", _amount(sum((i.amount for i in group), ZERO)))
        tp = _sub(info, "PmtTpInf")
        _sub(_sub(tp, "SvcLvl"), "Cd", "SEPA")
        _sub(_sub(tp, "LclInstrm"), "Cd", "CORE")
        _sub(tp, "SeqTp", seq)
        _sub(info, "ReqdColltnDt", run.collection_date.isoformat())
        _sub(_sub(info, "Cdtr"), "Nm", sepa_text(org.name, 70))
        _sub(_sub(_sub(info, "CdtrAcct"), "Id"), "IBAN", clean_iban(run.account.iban))
        _agent(info, "CdtrAgt", run.account.bic)
        _sub(info, "ChrgBr", "SLEV")
        other = _sub(_sub(_sub(_sub(info, "CdtrSchmeId"), "Id"), "PrvtId"), "Othr")
        _sub(other, "Id", cfg.creditor_id.replace(" ", "").upper())
        _sub(_sub(other, "SchmeNm"), "Prtry", "SEPA")
        for item in group:
            tx = _sub(info, "DrctDbtTxInf")
            _sub(_sub(tx, "PmtId"), "EndToEndId", item.end_to_end_id)
            _sub(tx, "InstdAmt", _amount(item.amount), Ccy="EUR")
            mandate_info = _sub(_sub(tx, "DrctDbtTx"), "MndtRltdInf")
            _sub(mandate_info, "MndtId", item.mandate.reference)
            _sub(mandate_info, "DtOfSgntr", item.mandate.signed_on.isoformat())
            _agent(tx, "DbtrAgt", item.mandate.bic)
            _sub(_sub(tx, "Dbtr"), "Nm", sepa_text(item.mandate.holder, 70))
            _sub(_sub(_sub(tx, "DbtrAcct"), "Id"), "IBAN", item.mandate.iban)
            purpose = f"{item.invoice.display_number} {item.invoice.subject}"
            _sub(_sub(tx, "RmtInf"), "Ustrd", sepa_text(purpose, 140))
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(doc, encoding="utf-8")


def masked_iban(iban: str) -> str:
    return f"{iban[:4]} **** {iban[-4:]}" if len(iban) > 8 else iban
