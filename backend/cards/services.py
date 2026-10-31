"""Mitgliedsausweise: Schlüssel anlegen, öffentliche Angaben, QR-Code und PDF."""

from __future__ import annotations

import io
from collections.abc import Iterable

from django.db.models import Q
from django.utils import timezone
from reportlab.graphics import renderSVG
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from core.tenancy import rls_bypass
from members.models import DepartmentMembership, Membership, MembershipPeriod
from members.photo_models import MemberPhoto
from organizations.theme import effective_theme

from .models import MemberCard, new_token


def ensure_card(membership: Membership, user=None) -> MemberCard:
    """Ausweis der Mitgliedschaft; legt ihn beim ersten Mal an."""
    card = MemberCard.objects.filter(membership=membership).first()
    if card is None:
        card, _ = MemberCard.objects.get_or_create(
            membership=membership,
            defaults={
                "organization_id": membership.organization_id,
                "created_by": user if user is not None and user.is_authenticated else None,
            },
        )
    return card


def renew(card: MemberCard) -> MemberCard:
    card.token = new_token()
    card.issued_at = timezone.now()
    card.revoked_at = None
    card.save(update_fields=["token", "issued_at", "revoked_at"])
    return card


def card_info(card: MemberCard | None) -> dict:
    """Angaben für Vorstand und Mitgliederbereich."""
    if card is None:
        return {"state": "none"}
    return {
        "state": "revoked" if card.revoked_at else "active",
        "url": card.url,
        "token": card.token,
        "issued_at": card.issued_at,
        "revoked_at": card.revoked_at,
    }


def current_departments(memberships: Iterable[int]) -> dict[int, list[str]]:
    on = timezone.localdate()
    result: dict[int, list[str]] = {}
    for dm in (
        DepartmentMembership.objects.filter(membership_id__in=list(memberships), valid_from__lte=on)
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=on))
        .select_related("department")
        .order_by("department__sort_order", "department__name")
    ):
        result.setdefault(dm.membership_id, []).append(dm.department.name)
    return result


def has_public_photo(membership: Membership) -> MemberPhoto | None:
    if not membership.photo_consent_at:
        return None
    return MemberPhoto.objects.filter(membership=membership, status="approved").first()


def find_valid(token: str) -> MemberCard | None:
    """Gültigen Ausweis zum Schlüssel suchen (öffentlich, deshalb ohne RLS)."""
    if not token or len(token) > 64:
        return None
    with rls_bypass():
        card = (
            MemberCard.objects.select_related("membership__person", "organization__parent__parent")
            .filter(token=token, revoked_at__isnull=True)
            .first()
        )
    # Deaktivierte Organisation: Ausweis gilt nicht mehr, keine Daten zeigen (Audit B-V05)
    if card is None or card.membership.purged_at or not card.organization.is_active:
        return None
    return card


def imprint_key(org) -> str:
    from organizations.imprint import ensure

    return ensure(org).public_key


def public_data(card: MemberCard) -> dict:
    """Was die Seite nach dem Scan zeigt – bewusst nur das Nötigste."""
    membership = card.membership
    club = card.organization
    on = timezone.localdate()
    with rls_bypass():
        current = membership.current_period(on)
        if current:
            status, label = "active", "Gültige Mitgliedschaft"
        elif MembershipPeriod.objects.filter(membership=membership, entry_date__gt=on).exists():
            status, label = "future", "Mitgliedschaft beginnt später"
        else:
            status, label = "inactive", "Keine gültige Mitgliedschaft"
        member_type = membership.current_type(on) if current else None
        departments = current_departments([membership.pk]).get(membership.pk, []) if current else []
        photo = has_public_photo(membership) if current else None
    theme = effective_theme(club.ancestors())
    federation = club.parent if club.parent and club.parent.type == "federation" else None
    person = membership.person
    return {
        "first_name": person.first_name,
        "last_name": person.last_name,
        "status": status,
        "status_label": label,
        "member_type": member_type.member_type.name if member_type else None,
        "club": club.name,
        "club_label": club.kind_label,
        "imprint_key": imprint_key(club),
        "federation": federation.name if federation else None,
        "federation_label": federation.kind_label if federation else None,
        "department_label": (
            club.department_label_plural if len(departments) > 1 else club.department_label
        ),
        "departments": departments,
        "photo_url": (
            f"/api/public/card/{card.token}/photo/?v={int(photo.updated_at.timestamp())}"
            if photo
            else None
        ),
        "logo_url": theme["logo_url"],
        "theme": {k: theme[k] for k in ("primary", "on_primary", "accent", "on_accent")},
        "checked_at": timezone.now(),
    }


# --- QR-Code ---


def _qr_drawing(url: str, size: float) -> Drawing:
    widget = QrCodeWidget(url, barLevel="M")
    x1, y1, x2, y2 = widget.getBounds()
    w, h = x2 - x1, y2 - y1
    drawing = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    drawing.add(widget)
    return drawing


def qr_svg(url: str) -> str:
    return renderSVG.drawToString(_qr_drawing(url, 240))


# --- PDF zum Drucken: Scheckkartenformat, 10 Ausweise je A4-Seite ---

CARD_W, CARD_H = 85.6 * mm, 54 * mm
COLS, ROWS = 2, 5


def _hex(color: str) -> colors.Color:
    try:
        return colors.HexColor(color)
    except (ValueError, TypeError):
        return colors.HexColor("#1f4e79")


def _image(field) -> ImageReader | None:
    if not field:
        return None
    try:
        with field.open("rb") as fh:
            return ImageReader(io.BytesIO(fh.read()))
    except (OSError, ValueError):
        return None


def _fit(c: canvas.Canvas, text: str, font: str, size: float, width: float) -> float:
    while size > 6 and c.stringWidth(text, font, size) > width:
        size -= 0.5
    return size


def _draw_card(c, x: float, y: float, entry: dict) -> None:
    primary = _hex(entry["primary"])
    on_primary = _hex(entry["on_primary"])
    # Schnittkante
    c.setStrokeColor(colors.HexColor("#b0b0b0"))
    c.setLineWidth(0.3)
    c.roundRect(x, y, CARD_W, CARD_H, 3 * mm, stroke=1, fill=0)
    # Kopfzeile mit Vereinsname
    band = 11 * mm
    c.saveState()
    path = c.beginPath()
    path.roundRect(x, y, CARD_W, CARD_H, 3 * mm)
    c.clipPath(path, stroke=0, fill=0)
    c.setFillColor(primary)
    c.rect(x, y + CARD_H - band, CARD_W, band, stroke=0, fill=1)
    c.restoreState()
    text_x = x + 3 * mm
    logo = entry.get("logo")
    if logo is not None:
        c.drawImage(
            logo,
            x + 2.5 * mm,
            y + CARD_H - band + 1.5 * mm,
            8 * mm,
            8 * mm,
            preserveAspectRatio=True,
            mask="auto",
        )
        text_x = x + 12 * mm
    c.setFillColor(on_primary)
    head_w = x + CARD_W - 3 * mm - text_x
    size = _fit(c, entry["club"], "Helvetica-Bold", 9, head_w)
    c.setFont("Helvetica-Bold", size)
    c.drawString(text_x, y + CARD_H - 5.5 * mm, entry["club"])
    c.setFont("Helvetica", 6.5)
    c.drawString(text_x, y + CARD_H - 9 * mm, "Mitgliedsausweis")
    # Foto
    body_top = y + CARD_H - band - 3 * mm
    content_x = x + 3 * mm
    photo = entry.get("photo")
    if photo is not None:
        ph_w, ph_h = 21 * mm, 28 * mm
        c.drawImage(
            photo, content_x, body_top - ph_h, ph_w, ph_h, preserveAspectRatio=True, anchor="n"
        )
        content_x += ph_w + 3 * mm
    # QR-Code rechts
    qr_size = 27 * mm
    qr_x = x + CARD_W - qr_size - 2 * mm
    qr_y = y + 4.5 * mm
    from reportlab.graphics import renderPDF

    renderPDF.draw(_qr_drawing(entry["url"], qr_size), c, qr_x, qr_y)
    c.setFillColor(colors.HexColor("#555555"))
    c.setFont("Helvetica", 5.5)
    c.drawCentredString(qr_x + qr_size / 2, y + 2.5 * mm, "Gültigkeit per QR-Code prüfen")
    # Name und Angaben
    text_w = qr_x - content_x - 2 * mm
    c.setFillColor(colors.black)
    line_y = body_top - 4 * mm
    for text, font, size in (
        (entry["first_name"], "Helvetica", 9),
        (entry["last_name"], "Helvetica-Bold", 11),
    ):
        c.setFont(font, _fit(c, text, font, size, text_w))
        c.drawString(content_x, line_y, text)
        line_y -= 4.8 * mm
    c.setFont("Helvetica", 7)
    line_y -= 1 * mm
    for label, value in entry["lines"]:
        if not value:
            continue
        c.setFillColor(colors.HexColor("#555555"))
        c.setFont("Helvetica", 5.5)
        c.drawString(content_x, line_y, label)
        line_y -= 3 * mm
        c.setFillColor(colors.black)
        c.setFont("Helvetica", _fit(c, value, "Helvetica", 7.5, text_w))
        c.drawString(content_x, line_y, value)
        line_y -= 4 * mm


def card_entries(cards: list[MemberCard]) -> list[dict]:
    """Daten für den Druck; muss im passenden RLS-Kontext laufen."""
    ids = [card.membership_id for card in cards]
    departments = current_departments(ids)
    photos = {
        p.membership_id: p
        for p in MemberPhoto.objects.filter(
            membership_id__in=ids, status="approved", membership__photo_consent_at__isnull=False
        )
    }
    themes: dict[int, dict] = {}
    logos: dict[int, ImageReader | None] = {}
    entries = []
    for card in cards:
        m = card.membership
        club = card.organization
        if club.pk not in themes:
            themes[club.pk] = effective_theme(club.ancestors())
            logo_field = next((o.logo for o in club.ancestors() if o.logo), None)
            logos[club.pk] = _image(logo_field)
        theme = themes[club.pk]
        depts = departments.get(m.pk, [])
        photo = photos.get(m.pk)
        entries.append(
            {
                "club": club.name,
                "first_name": m.person.first_name,
                "last_name": m.person.last_name,
                "url": card.url,
                "primary": theme["primary"],
                "on_primary": theme["on_primary"],
                "logo": logos[club.pk],
                "photo": _image(photo.image) if photo else None,
                "lines": [
                    (
                        club.department_label_plural if len(depts) > 1 else club.department_label,
                        ", ".join(depts),
                    ),
                    ("Mitgliedsnummer", m.club_number),
                ],
            }
        )
    return entries


def render_pdf(entries: list[dict]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Mitgliedsausweise")
    page_w, page_h = A4
    margin_x = (page_w - COLS * CARD_W) / 2
    margin_y = (page_h - ROWS * CARD_H) / 2
    if not entries:
        c.setFont("Helvetica", 11)
        c.drawString(margin_x, page_h - margin_y, "Keine Mitglieder für Ausweise gefunden.")
    per_page = COLS * ROWS
    for i, entry in enumerate(entries):
        if i and i % per_page == 0:
            c.showPage()
        slot = i % per_page
        col, row = slot % COLS, slot // COLS
        x = margin_x + col * CARD_W
        y = page_h - margin_y - (row + 1) * CARD_H
        _draw_card(c, x, y, entry)
    c.showPage()
    c.save()
    return buf.getvalue()
