"""Demo-Briefbögen für den Testserver (alle Angaben erfunden).

Ändert nur, was noch niemand gepflegt hat: Funktionsadressen nur, wenn leer,
Social-Media-Links nur, wenn die Einheit noch keine hat.
"""

from __future__ import annotations

from access.models import Role
from organizations.models import Organization, SocialLink

from .data import ensure

ROLE_MAILS = {
    "Vorstand": "vorstand@{slug}.test",
    "Kassierer": "kasse@{slug}.test",
    "Schriftführer": "schriftfuehrer@{slug}.test",
}

SOCIAL = [
    (SocialLink.Kind.FACEBOOK, "https://facebook.example.test/{slug}"),
    (SocialLink.Kind.INSTAGRAM, "https://instagram.example.test/{slug}"),
]


def seed_letterheads(orgs: dict[str, Organization]) -> None:
    for key in ("federation", "club"):
        org = orgs[key]
        slug = "dachverband-demo" if key == "federation" else "verein-demo"
        letterhead = ensure(org)
        if not letterhead.show_social:
            letterhead.show_social = True
            letterhead.save(update_fields=["show_social", "updated_at"])
        for role in Role.objects.filter(organization=org, name__in=ROLE_MAILS):
            if not role.contact_email:
                role.contact_email = ROLE_MAILS[role.name].format(slug=slug)
                role.save(update_fields=["contact_email"])
        Role.objects.filter(organization=org, name="Schriftführer").update(on_letterhead=True)
        if not org.social_links.exists():
            for position, (kind, url) in enumerate(SOCIAL):
                SocialLink.objects.create(
                    organization=org, kind=kind, url=url.format(slug=slug), position=position
                )
