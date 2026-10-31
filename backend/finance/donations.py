"""Zuwendungsbestätigungen (Spendenbescheinigungen) nach amtlichem Muster.

Für jede Einheit mit Kasse, die steuerbegünstigt ist und einen eigenen Bescheid hat
(Schalter in den Einstellungen; der Registereintrag spielt keine Rolle). Ablauf:
Zuwendungen erfassen oder aus Einnahmen einer Spenden-Kategorie übernehmen →
Einzel- oder Sammelbestätigung ausstellen (PDF, das Doppel bleibt gespeichert,
§ 50 Abs. 7 EStDV) → bei Fehlern stornieren und neu ausstellen.

Regeln:
- Ausstellen nur mit vollständigen Angaben zum Bescheid. Liegt der
  Freistellungsbescheid mehr als 5 Jahre bzw. der Feststellungsbescheid nach § 60a AO
  mehr als 3 Jahre zurück, wird nichts ausgestellt (§ 63 Abs. 5 AO).
- Mitgliedsbeiträge nur, wenn eingeschaltet (bei Sport-, Kultur-, Heimat- und
  Brauchtumsvereinen sind sie meist nicht abziehbar, § 10b Abs. 1 Satz 8 EStG).
- Sachzuwendungen nur einzeln, nie in einer Sammelbestätigung.
- Eine Sammelbestätigung umfasst Zuwendungen eines Zuwendenden aus einem Kalenderjahr.
- Bestätigte Zuwendungen lassen sich nicht ändern oder löschen; erst stornieren.
"""

from __future__ import annotations

import datetime
import hashlib
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import connection, transaction
from django.db.models import Max
from django.utils import timezone

from .models import Booking, Donation, DonationSettings, DonationStatement

EXEMPTION_YEARS = 5
STATUTE_YEARS = 3


def available(org) -> bool:
    """Der Bereich steht jeder Einheit außer der Plattform offen."""
    from organizations.models import Organization

    return org.type != Organization.Type.PLATFORM


def is_enabled(org) -> bool:
    """Schalter „steuerbegünstigt mit eigenem Bescheid“ der Einheit."""
    return (
        available(org) and DonationSettings.objects.filter(organization=org, enabled=True).exists()
    )


def settings_for(org) -> DonationSettings:
    cfg = DonationSettings.objects.filter(organization=org).first()
    if cfg is None:
        cfg = DonationSettings(organization=org)
        # Steuernummer aus den Rechnungseinstellungen vorschlagen
        from billing.models import BillingSettings

        billing = BillingSettings.objects.filter(organization=org).first()
        if billing is not None and billing.tax_number:
            cfg.tax_number = billing.tax_number
        cfg.place = (getattr(org, "city", "") or "")[:100]
    return cfg


def _add_years(day: datetime.date, years: int) -> datetime.date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29. Februar
        return day.replace(year=day.year + years, day=28)


def notice_valid_until(cfg: DonationSettings) -> datetime.date | None:
    if cfg.notice_date is None:
        return None
    years = EXEMPTION_YEARS if cfg.notice == DonationSettings.Notice.EXEMPTION else STATUTE_YEARS
    return _add_years(cfg.notice_date, years)


def problems(cfg: DonationSettings, on: datetime.date | None = None) -> list[str]:
    """Was fehlt, damit Bestätigungen ausgestellt werden dürfen (leer = alles gut)."""
    on = on or timezone.localdate()
    if not cfg.enabled:
        return [
            "Die Einheit ist nicht als steuerbegünstigt mit eigenem Bescheid eingetragen "
            "(Schalter in den Einstellungen)."
        ]
    gaps = []
    if not cfg.purposes.strip():
        gaps.append("begünstigte Zwecke")
    if not cfg.tax_office.strip():
        gaps.append("Finanzamt")
    if not cfg.tax_number.strip():
        gaps.append("Steuernummer")
    if cfg.notice_date is None:
        gaps.append("Datum des Bescheids")
    if cfg.notice == DonationSettings.Notice.EXEMPTION and not cfg.assessment_period.strip():
        gaps.append("letzter Veranlagungszeitraum")
    result = [f"Es fehlt: {', '.join(gaps)}."] if gaps else []
    until = notice_valid_until(cfg)
    if until is not None and on > until:
        years = (
            EXEMPTION_YEARS if cfg.notice == DonationSettings.Notice.EXEMPTION else STATUTE_YEARS
        )
        result.append(
            f"Der Bescheid vom {cfg.notice_date:%d.%m.%Y} ist älter als {years} Jahre. "
            "Mit ihm dürfen keine Zuwendungsbestätigungen mehr ausgestellt werden "
            "(§ 63 Abs. 5 AO). Bitte den neuen Bescheid eintragen."
        )
    if cfg.notice_date is not None and cfg.notice_date > on:
        result.append("Das Datum des Bescheids liegt in der Zukunft.")
    return result


def donor_key(donation: Donation) -> str:
    """Wer zusammen in eine Sammelbestätigung gehört: das Mitglied oder Name und Anschrift."""
    if donation.membership_id:
        return f"m:{donation.membership_id}"
    name = " ".join(donation.donor_name.lower().split())
    address = " ".join(donation.donor_address.lower().split())
    return f"n:{name}|{address}"


def check_donation(org, donation: Donation, cfg: DonationSettings | None = None) -> None:
    """Prüfung beim Erfassen und Ändern."""
    cfg = cfg or settings_for(org)
    errors: dict[str, str] = {}
    if donation.amount is None or donation.amount <= 0:
        errors["amount"] = "Bitte einen Betrag größer als 0 angeben."
    elif donation.amount > MAX_AMOUNT:
        # Der Betrag steht in Worten auf der Bestätigung (Audit 31.10. FIN31-R04)
        errors["amount"] = "Der Betrag ist zu groß für eine Zuwendungsbestätigung."
    if not donation.donor_name.strip():
        errors["donor_name"] = "Bitte den Namen des Zuwendenden angeben."
    if donation.kind == Donation.Kind.FEE and not cfg.fees_allowed:
        errors["kind"] = (
            "Mitgliedsbeiträge werden nicht bestätigt. Das lässt sich unter "
            "„Zuwendungsbestätigungen › Einstellungen“ einschalten, wenn die Beiträge "
            "abziehbar sind."
        )
    if donation.kind == Donation.Kind.GOODS:
        if not donation.goods_description.strip():
            errors["goods_description"] = (
                "Bitte die Sache genau bezeichnen (Alter, Zustand, Kaufpreis)."
            )
        if not donation.goods_origin:
            errors["goods_origin"] = "Bitte angeben, woher die Sache stammt."
        if donation.waiver:
            errors["waiver"] = "Der Verzicht auf Aufwendungsersatz ist eine Geldzuwendung."
    if donation.date and donation.date > timezone.localdate():
        errors["date"] = "Das Datum liegt in der Zukunft."
    if errors:
        raise ValidationError(errors)


# Betrag in Worten geht bis unter eine Milliarde (finance/words.py)
MAX_AMOUNT = Decimal("999999999.99")


UNKNOWN_DONOR = "Unbekannt"


def incomplete(donation: Donation) -> str:
    """Warum diese Zuwendung noch nicht bestätigt werden kann (leer = vollständig).

    Fachfrage 5 (Audit 31.10.): vor dem Ausstellen vollständiger Name und Anschrift;
    „Unbekannt“ aus dem Kassenimport sperrt das Ausstellen."""
    name = " ".join(donation.donor_name.split())
    if not name or name.casefold() == UNKNOWN_DONOR.casefold():
        return "Name des Zuwendenden fehlt"
    if not donation.donor_address.strip():
        return "Anschrift des Zuwendenden fehlt"
    return ""


def ensure_editable(donation: Donation) -> None:
    if donation.statement_id:
        raise ValidationError(
            f"Die Zuwendung ist in der Bestätigung {donation.statement.number} enthalten. "
            "Bitte erst die Bestätigung stornieren."
        )


def donor_from_membership(org, membership) -> tuple[str, str]:
    from billing.services import member_recipient

    data = member_recipient(org, membership)
    return data["recipient_name"], data["recipient_address"]


@transaction.atomic
def import_bookings(org, year: int, user) -> list[Donation]:
    """Einnahmen aus Spenden-Kategorien eines Kalenderjahrs als Zuwendungen übernehmen."""
    bookings = (
        Booking.objects.filter(
            organization=org,
            kind=Booking.Kind.INCOME,
            category__donations=True,
            date__year=year,
            donation__isnull=True,
            # Stornierte Buchungen sind keine Zuwendung
            cancellation__isnull=True,
        )
        .select_related("membership__person")
        .order_by("date", "pk")
    )
    created = []
    for booking in bookings:
        if booking.membership_id:
            name, address = donor_from_membership(org, booking.membership)
        else:
            name, address = booking.counterparty.strip(), ""
        created.append(
            Donation.objects.create(
                organization=org,
                date=booking.date,
                kind=Donation.Kind.MONEY,
                amount=booking.amount,
                membership=booking.membership,
                donor_name=(name or UNKNOWN_DONOR)[:200],
                donor_address=address[:500],
                booking=booking,
                note=booking.text[:300],
                created_by=user,
            )
        )
    return created


def _next_seq(org, year: int) -> int:
    """Nächste Bestätigungsnummer. Eigene Sperre je Verein und Jahr (Audit 31.10. FIN31-R02):
    Ein FOR UPDATE auf das Maximum sperrt keine Zeile, beim ersten Beleg des Jahres gar
    nichts. Schlüsselbereich 300000 + Jahr, getrennt von Buchungen und Rechnungen."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [org.pk, 300000 + year])
    top = DonationStatement.objects.filter(organization=org, year=year).aggregate(m=Max("seq"))["m"]
    return (top or 0) + 1


def _item(d: Donation) -> dict:
    return {
        "id": d.pk,
        "date": d.date.isoformat(),
        "kind": d.kind,
        "amount": str(d.amount),
        "waiver": d.waiver,
        "goods_description": d.goods_description,
        "goods_origin": d.goods_origin,
        "goods_documents": d.goods_documents,
    }


@transaction.atomic
def issue(org, donations: list[Donation], user, *, signer_name: str = "") -> DonationStatement:
    """Eine Bestätigung für die übergebenen Zuwendungen eines Zuwendenden ausstellen."""
    from . import donation_pdf

    if not is_enabled(org):
        raise ValidationError(
            "Zuwendungsbestätigungen gibt es nur für steuerbegünstigte Einheiten mit eigenem "
            "Bescheid."
        )
    cfg = settings_for(org)
    if issues := problems(cfg):
        raise ValidationError(" ".join(issues))
    ids = [d.pk for d in donations]
    donations = list(
        Donation.objects.select_for_update().filter(organization=org, pk__in=ids).order_by("date")
    )
    if not donations:
        raise ValidationError("Bitte mindestens eine Zuwendung wählen.")
    if any(d.statement_id for d in donations):
        raise ValidationError("Mindestens eine Zuwendung ist schon bestätigt.")
    if len({donor_key(d) for d in donations}) > 1:
        raise ValidationError("Eine Bestätigung gilt immer nur für einen Zuwendenden.")
    if reason := next((r for d in donations if (r := incomplete(d))), ""):
        raise ValidationError(f"{reason}. Bitte zuerst in der Zuwendung ergänzen.")
    if len({d.date.year for d in donations}) > 1:
        raise ValidationError("Eine Sammelbestätigung umfasst nur Zuwendungen eines Jahres.")
    if sum((d.amount for d in donations), Decimal("0")) > MAX_AMOUNT:
        raise ValidationError("Die Summe ist zu groß für eine Zuwendungsbestätigung.")
    goods = [d for d in donations if d.kind == Donation.Kind.GOODS]
    if goods and len(donations) > 1:
        raise ValidationError("Sachzuwendungen werden einzeln bestätigt, nicht gesammelt.")
    if not cfg.fees_allowed and any(d.kind == Donation.Kind.FEE for d in donations):
        raise ValidationError("Mitgliedsbeiträge werden nach den Einstellungen nicht bestätigt.")
    first = donations[0]
    today = timezone.localdate()
    year = first.date.year
    statement = DonationStatement(
        organization=org,
        year=today.year,
        seq=_next_seq(org, today.year),
        kind=(
            DonationStatement.Kind.SINGLE
            if len(donations) == 1
            else DonationStatement.Kind.COLLECTIVE
        ),
        goods=bool(goods),
        membership=first.membership,
        donor_name=first.donor_name,
        donor_address=first.donor_address,
        total=sum((d.amount for d in donations), Decimal("0")),
        period_from=(
            first.date if len(donations) == 1 else max(datetime.date(year, 1, 1), first.date)
        ),
        period_to=donations[-1].date,
        items=[_item(d) for d in donations],
        issued_on=today,
        issued_by=user,
        signer_name=(signer_name or (user.get_full_name() or "")).strip()[:200],
    )
    if statement.kind == DonationStatement.Kind.COLLECTIVE:
        statement.period_from = datetime.date(year, 1, 1)
        statement.period_to = datetime.date(year, 12, 31)
    statement.save()
    content = donation_pdf.render(statement, cfg)
    statement.file.save(donation_pdf.filename(statement), ContentFile(content), save=False)
    statement.pdf_sha256 = hashlib.sha256(content).hexdigest()
    statement.save(update_fields=["file", "pdf_sha256"])
    Donation.objects.filter(pk__in=[d.pk for d in donations]).update(statement=statement)
    return statement


def year_end_groups(org, year: int) -> list[list[Donation]]:
    """Offene Geld- und Beitragszuwendungen eines Jahres, nach Zuwendendem gruppiert."""
    groups: dict[str, list[Donation]] = {}
    for d in Donation.objects.filter(
        organization=org, date__year=year, statement__isnull=True
    ).exclude(kind=Donation.Kind.GOODS):
        groups.setdefault(donor_key(d), []).append(d)
    return sorted(groups.values(), key=lambda g: g[0].donor_name.lower())


def year_checks(org, year: int) -> dict:
    """Offene Zuwendungen eines Jahres für die Prüfliste vor den Jahresbestätigungen."""
    cfg = settings_for(org)
    open_ = Donation.objects.filter(organization=org, date__year=year, statement__isnull=True)
    goods = open_.filter(kind=Donation.Kind.GOODS)
    return {
        "open": open_.count(),
        "without_address": open_.filter(donor_address__regex=r"^\s*$").count(),
        "goods_without_documents": goods.filter(goods_documents=False).count(),
        "goods_open": goods.count(),
        "fees_skipped": 0 if cfg.fees_allowed else open_.filter(kind=Donation.Kind.FEE).count(),
    }


@transaction.atomic
def issue_year_end(org, year: int, user, *, signer_name: str = "") -> list[DonationStatement]:
    cfg = settings_for(org)
    groups = year_end_groups(org, year)
    if not cfg.fees_allowed:
        groups = [[d for d in g if d.kind != Donation.Kind.FEE] for g in groups]
        groups = [g for g in groups if g]
    # Unvollständige Zuwendende bleiben offen (Vorschau nennt sie)
    groups = [g for g in groups if not any(incomplete(d) for d in g)]
    return [issue(org, g, user, signer_name=signer_name) for g in groups]


@transaction.atomic
def cancel(statement: DonationStatement, user, reason: str) -> DonationStatement:
    """Storno: die Bestätigung bleibt als Doppel erhalten, die Zuwendungen werden wieder frei."""
    statement = DonationStatement.objects.select_for_update().get(pk=statement.pk)
    if statement.cancelled_at:
        raise ValidationError("Die Bestätigung ist schon storniert.")
    reason = " ".join((reason or "").split())
    if len(reason) < 3:
        raise ValidationError({"reason": "Bitte einen Grund für das Storno angeben."})
    statement.cancelled_at = timezone.now()
    statement.cancelled_by = user
    statement.cancel_reason = reason[:300]
    statement.save(update_fields=["cancelled_at", "cancelled_by", "cancel_reason"])
    Donation.objects.filter(statement=statement).update(statement=None)
    return statement
