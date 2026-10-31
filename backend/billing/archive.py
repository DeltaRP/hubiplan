"""Ausgegebene Rechnungen als PDF ablegen (Fachfrage 4, Audit 31.10.).

Eine festgeschriebene Rechnung wird beim ersten Versand bzw. Abruf einmal erzeugt und
gespeichert; danach gilt immer diese Fassung, auch wenn sich Briefkopf, Bankverbindung
oder Vorlage ändern. Entwürfe und stornierte Rechnungen werden weiter frisch erzeugt.
"""

from __future__ import annotations

import hashlib

from django.core.files.base import ContentFile
from django.db import transaction

from . import pdf
from .models import Invoice

ARCHIVED = (Invoice.Status.OPEN, Invoice.Status.PAID)


def archived_pdf(invoice: Invoice) -> bytes:
    """PDF der Rechnung in der ausgegebenen Fassung (legt sie beim ersten Mal ab)."""
    if invoice.status not in ARCHIVED or invoice.number is None:
        return pdf.render([invoice])
    if invoice.issued_pdf:
        with invoice.issued_pdf.open("rb") as fh:
            return fh.read()
    with transaction.atomic():
        locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if locked.issued_pdf:
            with locked.issued_pdf.open("rb") as fh:
                return fh.read()
        content = pdf.render([locked])
        locked.issued_pdf_sha256 = hashlib.sha256(content).hexdigest()
        locked.issued_pdf.save(pdf.filename(locked), ContentFile(content), save=False)
        locked.save(update_fields=["issued_pdf", "issued_pdf_sha256", "updated_at"])
    invoice.issued_pdf = locked.issued_pdf
    invoice.issued_pdf_sha256 = locked.issued_pdf_sha256
    return content


def archive_missing(limit: int = 200) -> int:
    """Noch nicht abgelegte festgeschriebene Rechnungen nachträglich ablegen
    (z. B. Postversand über den Sammel-PDF eines Beitragslaufs)."""
    from core.tenancy import rls_bypass

    done = 0
    with rls_bypass():
        ids = list(
            Invoice.objects.filter(status__in=ARCHIVED, number__isnull=False, issued_pdf="")
            .order_by("pk")
            .values_list("pk", flat=True)[:limit]
        )
        for pk in ids:
            invoice = Invoice.objects.select_related("organization").get(pk=pk)
            archived_pdf(invoice)
            done += 1
    return done
