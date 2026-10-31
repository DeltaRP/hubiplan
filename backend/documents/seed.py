"""Erfundene Demo-Dokumente für die Pilotorganisationen (selbst erzeugte PDFs)."""

from __future__ import annotations

import datetime
import io

from django.core.files.base import ContentFile

from .models import Document, DocumentVersion, Folder

V = Folder.Visibility


def demo_pdf(title: str, owner: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.setTitle(title)
    _, height = A4
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(56, height - 72, title)
    pdf.setFont("Helvetica", 11)
    pdf.drawString(56, height - 94, owner)
    pdf.setFont("Helvetica-Oblique", 10)
    pdf.drawString(56, height - 120, "Demodaten: erfundener Platzhaltertext.")
    pdf.showPage()
    pdf.save()
    return buf.getvalue()


PLAN = {
    "federation": [
        ("Rundschreiben an die Vereine", V.CLUBS, [("Meldebogen Schützenfest", "2026-03-01")]),
        ("Vorstandsprotokolle", V.BOARD, [("Protokoll Vorstandssitzung März", "2026-03-12")]),
    ],
    "club": [
        (
            "Protokolle",
            V.BOARD,
            [
                ("Protokoll Jahreshauptversammlung", "2026-02-14"),
                ("Protokoll Vorstandssitzung", "2026-04-02"),
            ],
        ),
        ("Formulare", V.MEMBERS, [("Antrag auf Uniformzuschuss", "2025-11-01")]),
        ("Aufnahme", V.PUBLIC, [("Aufnahmeantrag", "2024-01-15")]),
    ],
}


def seed_documents(orgs) -> None:
    for key, folders in PLAN.items():
        org = orgs[key]
        if Folder.objects.filter(organization=org).exists():
            continue
        for name, visibility, docs in folders:
            folder = Folder.objects.create(
                organization=org, name=name, visibility=visibility, public_key=Folder.new_key()
            )
            for title, day in docs:
                doc = Document.objects.create(
                    organization=org,
                    folder=folder,
                    title=title,
                    date=datetime.date.fromisoformat(day),
                )
                content = demo_pdf(title, org.name)
                version = DocumentVersion(
                    organization=org,
                    document=doc,
                    name=f"{title.replace(' ', '-')}.pdf",
                    size=len(content),
                    content_type="application/pdf",
                )
                version.file.save(version.name, ContentFile(content), save=False)
                version.save()
