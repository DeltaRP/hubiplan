"""Demodaten der Webseite für den Testserver (alles erfunden).

Schaltet das Modul „Webseite“ für den Demoverein frei, richtet die Webseite im
Wartungsmodus ein (Domain auf .test), legt Begrüßung und Geschichte, Vorstandsrollen
für die Webseite und eine erfundene Königsliste an. Wiederholbar: Vorhandenes bleibt.
"""

from __future__ import annotations

import datetime

from django.utils import timezone

from access.models import Role, RoleAssignment
from members.models import Membership
from organizations.models import Department, DepartmentRole, SocialLink

from . import privacy
from .content_models import WebsiteText
from .models import Website, WebsiteDomain

DEMO_DOMAIN = "www.hubertus-grimlinghausen.test"

GREETING = (
    "Herzlich willkommen beim Hubertus-Schützenverein! Wir pflegen seit über hundert Jahren "
    "Brauchtum, Geselligkeit und Zusammenhalt im Ort.\n\n"
    "Hier findet ihr unsere Termine, den Vorstand, die Züge und unsere Majestäten. "
    "*Alle Angaben auf dieser Testseite sind erfunden.*"
)
HISTORY = (
    "## Von der Gründung bis heute\n\n"
    "Der Verein wurde 1920 von einigen Schützenbrüdern gegründet. In den folgenden "
    "Jahrzehnten kamen nach und nach die heutigen Züge hinzu.\n\n"
    "Diese Chronik ist ein **erfundener Beispieltext** für den Testserver. Im Echtbetrieb "
    "schreibt der Verein hier seine eigene Chronik."
)

# Erfundene Namen für frühere Majestäten (vor HUBIplan)
OLD_KINGS = [
    "Heinrich Alt",
    "Wilhelm Früher",
    "Josef Damals",
    "Peter Vorzeit",
    "Karl Einst",
    "Johann Gestern",
    "Franz Ehemals",
    "Theodor Vormals",
]
QUEENS = ["Maria", "Anna", "Gertrud", "Elisabeth", "Hildegard", "Margarete", "Helene", "Käthe"]


def seed_website(orgs) -> None:
    club = orgs["club"]
    if "website" not in (club.enabled_modules or []):
        club.enabled_modules = [*(club.enabled_modules or []), "website"]
        club.save(update_fields=["enabled_modules"])
    website = Website.objects.filter(organization=club).first()
    if website is None:
        website = Website.objects.create(organization=club, public_key=Website.new_key())
    if not WebsiteDomain.objects.filter(hostname=DEMO_DOMAIN).exists():
        WebsiteDomain.objects.create(
            organization=club, website=website, hostname=DEMO_DOMAIN, is_primary=True
        )
    _texts(website)
    _social(club)
    _social_posts(website)
    _board(club)
    _honors(club)
    if not website.privacy_text:
        privacy.generate(website)
        # Demodaten: gleich veröffentlicht
        website.privacy_published_text = website.privacy_text
        website.privacy_published_at = timezone.now()
        website.save()


def _texts(website: Website) -> None:
    now = timezone.now()
    for kind, slug, title, body, position in (
        (WebsiteText.Kind.GREETING, "", "Willkommen", GREETING, 0),
        (WebsiteText.Kind.PAGE, "geschichte", "Chronik", HISTORY, 1),
    ):
        if WebsiteText.objects.filter(website=website, kind=kind, slug=slug).exists():
            continue
        WebsiteText.objects.create(
            organization=website.organization,
            website=website,
            kind=kind,
            slug=slug,
            menu_position=position,
            title=title,
            body=body,
            published_title=title,
            published_body=body,
            published_at=now,
        )


# Erfundene Kanäle, damit die Webseite alle vorgesehenen Netzwerke zeigt
SOCIAL = [
    (SocialLink.Kind.INSTAGRAM, "https://instagram.example.test/verein-demo"),
    (SocialLink.Kind.FACEBOOK, "https://facebook.example.test/verein-demo"),
    (SocialLink.Kind.TIKTOK, "https://tiktok.example.test/@verein-demo"),
    (SocialLink.Kind.X, "https://x.example.test/verein-demo"),
]


def _social(club) -> None:
    existing = set(club.social_links.values_list("kind", flat=True))
    position = club.social_links.count()
    for kind, url in SOCIAL:
        if kind not in existing:
            SocialLink.objects.create(organization=club, kind=kind, url=url, position=position)
            position += 1


# Erfundene Beiträge für „Aktuelles“: Kanäle ohne Zugang (kein Abruf bei Meta)
DEMO_POSTS = [
    ("instagram", "Was für ein Schützenfest! Danke an alle, die dabei waren.", "#2e7d32", 2),
    ("instagram", "Probe für den großen Umzug am Sonntag.", "#1565c0", 1),
    ("instagram", "Unser neues Zelt steht.", "#ef6c00", 1),
    ("facebook", "Einladung zur Jahreshauptversammlung im Vereinsheim.", None, 0),
    ("facebook", "Frühschoppen mit Musik – schön war's.", "#6a1b9a", 1),
]


def _demo_image(color: str) -> bytes:
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1200, 900), color)
    draw = ImageDraw.Draw(img)
    draw.rectangle((100, 100, 1100, 800), outline="white", width=12)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _social_posts(website: Website) -> None:
    from django.core.files.base import ContentFile

    from .social_models import SocialFeed, SocialPost, SocialPostImage

    if SocialFeed.objects.filter(website=website).exists():
        return
    feeds = {
        kind: SocialFeed.objects.create(
            organization=website.organization,
            website=website,
            kind=kind,
            status=SocialFeed.Status.OK,
            account_name="verein_demo" if kind == "instagram" else "Verein Demo",
            is_active=False,
        )
        for kind in ("instagram", "facebook")
    }
    now = timezone.now()
    for index, (kind, text, color, images) in enumerate(DEMO_POSTS):
        post = SocialPost.objects.create(
            organization=website.organization,
            feed=feeds[kind],
            external_id=f"demo-{index}",
            media_type=SocialPost.MediaType.ALBUM
            if images > 1
            else (SocialPost.MediaType.IMAGE if images else SocialPost.MediaType.TEXT),
            text=text,
            permalink="",
            published_at=now - datetime.timedelta(days=3 * index + 1),
        )
        for position in range(images):
            image = SocialPostImage(
                organization=website.organization,
                post=post,
                position=position,
                key=SocialPostImage.new_key(),
                width=1200,
                height=900,
                alt_text="Erfundenes Beispielbild",
            )
            data = _demo_image(color)
            image.file.save("bild.jpg", ContentFile(data), save=False)
            image.small.save("bild-klein.jpg", ContentFile(data), save=False)
            image.save()


def _members(club) -> list[Membership]:
    return list(
        Membership.objects.filter(organization=club, purged_at__isnull=True)
        .select_related("person")
        .order_by("pk")
    )


def _board(club) -> None:
    members = _members(club)
    if len(members) < 6:
        return
    positions = [
        ("1. Brudermeister", members[1], True),
        ("2. Brudermeister", members[2], False),
        ("Geschäftsführer", members[3], False),
        ("Schatzmeister", members[4], False),
    ]
    for index, (name, membership, chronicle) in enumerate(positions, start=1):
        role, created = Role.objects.get_or_create(
            organization=club,
            name=name,
            defaults={"on_website": True, "website_position": index, "in_chronicle": chronicle},
        )
        if created:
            RoleAssignment.objects.create(
                organization=club,
                role=role,
                person=membership.person,
                valid_from=datetime.date(2020, 4, 1),
            )
    # Ein früherer Brudermeister für die Chronik (nur Historie, ohne Zugang)
    chair = Role.objects.get(organization=club, name="1. Brudermeister")
    if chair.assignments.count() == 1:
        RoleAssignment.objects.create(
            organization=club,
            role=chair,
            person=members[5].person,
            valid_from=datetime.date(2008, 4, 1),
            valid_until=datetime.date(2020, 3, 31),
        )
    # Oberleutnant der Züge erscheint auf den Zugseiten
    DepartmentRole.objects.filter(organization=club, name="Oberleutnant").update(on_website=True)


def _honors(club) -> None:
    from honors.models import Companion, Dignity, Reign

    if Dignity.objects.filter(organization=club).exists():
        return
    king = Dignity.objects.create(organization=club, name="König", sort_order=1)
    prince = Dignity.objects.create(organization=club, name="Prinz", sort_order=2)
    pupil = Dignity.objects.create(organization=club, name="Schülerprinz", sort_order=3)
    members = _members(club)
    year = timezone.localdate().year
    # Frühere Könige als Namen, die letzten Jahre als Mitglieder
    for i, name in enumerate(OLD_KINGS):
        reign = Reign.objects.create(organization=club, dignity=king, year=1960 + i * 5, name=name)
        Companion.objects.create(
            organization=club,
            reign=reign,
            label="Königin",
            name=f"{QUEENS[i]} {name.split()[-1]}",
        )
    for offset in range(1, 6):
        if len(members) <= 10 + offset:
            break
        holder = members[10 + offset].person
        reign = Reign.objects.create(
            organization=club,
            dignity=king,
            year=year - offset + 1,
            person=holder,
            name=f"{holder.first_name} {holder.last_name}",
        )
        Companion.objects.create(
            organization=club,
            reign=reign,
            label="Königin",
            name=f"{QUEENS[offset]} {holder.last_name}",
        )
    for offset in range(1, 4):
        if len(members) <= 20 + offset:
            break
        p = members[20 + offset].person
        Reign.objects.create(
            organization=club,
            dignity=prince,
            year=year - offset + 1,
            person=p,
            name=f"{p.first_name} {p.last_name}",
        )
    Reign.objects.create(organization=club, dignity=pupil, year=year, name="Lukas Beispiel")
    zug = Department.objects.filter(organization=club, name="Herolde").first()
    if zug is not None:
        zk = Dignity.objects.create(organization=club, unit=zug, name="Zugkönig", sort_order=4)
        Reign.objects.create(organization=club, dignity=zk, year=year, name="Moritz Zugmann")
