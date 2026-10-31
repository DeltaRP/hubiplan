"""Erfundene Demo-Satzungen für die Pilotorganisationen (selbst erzeugte PDFs)."""

from __future__ import annotations

import datetime
import io

from django.core.files.base import ContentFile

from .models import Kind, StatutePublication, StatuteVersion

PARAGRAPHS = [
    (
        "§ 1 Name und Sitz",
        "Der Verein führt den oben genannten Namen und hat seinen Sitz in Neuss.",
    ),
    ("§ 2 Zweck", "Zweck des Vereins ist die Pflege des Schützenwesens und des Brauchtums."),
    (
        "§ 3 Mitgliedschaft",
        "Mitglied kann jede Person werden, die die Ziele des Vereins unterstützt.",
    ),
    ("§ 4 Beiträge", "Die Höhe der Beiträge beschließt die Mitgliederversammlung."),
    ("§ 5 Organe", "Organe des Vereins sind die Mitgliederversammlung und der Vorstand."),
]


def demo_pdf(title: str, version_label: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=A4)
    pdf.setTitle(f"Satzung {title}")
    width, height = A4
    y = height - 72
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(56, y, "Satzung")
    y -= 22
    pdf.setFont("Helvetica", 11)
    pdf.drawString(56, y, title)
    y -= 16
    pdf.drawString(56, y, version_label)
    y -= 26
    pdf.setFont("Helvetica-Oblique", 10)
    pdf.drawString(56, y, "Demodaten: erfundener Platzhaltertext, keine echte Satzung.")
    y -= 32
    for heading, text in PARAGRAPHS:
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(56, y, heading)
        y -= 16
        pdf.setFont("Helvetica", 10)
        pdf.drawString(56, y, text)
        y -= 28
    pdf.showPage()
    pdf.save()
    return buf.getvalue()


def seed_statutes(orgs) -> None:
    plan = [
        (orgs["federation"], [(datetime.date(2012, 3, 15), "Neufassung")], False),
        (
            orgs["club"],
            [
                (datetime.date(1998, 4, 20), "Neufassung"),
                (datetime.date(2019, 11, 8), "Änderung § 4 (Beiträge)"),
            ],
            True,
        ),
    ]
    for org, versions, public in plan:
        if StatuteVersion.objects.filter(
            organization=org, department=None, kind=Kind.STATUTE
        ).exists():
            continue
        for valid_from, note in versions:
            label = f"Fassung vom {valid_from:%d.%m.%Y} ({note})"
            content = demo_pdf(org.name, label)
            version = StatuteVersion(
                organization=org,
                valid_from=valid_from,
                note=note,
                name=f"Satzung-{valid_from:%Y-%m-%d}.pdf",
                size=len(content),
            )
            version.file.save(version.name, ContentFile(content), save=False)
            version.save()
        StatutePublication.objects.get_or_create(
            organization=org,
            department=None,
            kind=Kind.STATUTE,
            defaults={"is_public": public, "public_key": StatutePublication.new_key()},
        )
