"""Demo-Impressen für den Testserver (alle Angaben erfunden).

Füllt nur Impressen, die noch niemand gepflegt hat. Die Datenschutztexte
erzeugt ``imprint_generator`` aus den Einstellungen.
"""

from __future__ import annotations

from django.utils import timezone

from access.models import Role

from .imprint import ensure
from .imprint_generator import privacy_for
from .models import Imprint, Organization

DEMO = {
    "platform": {
        "name": "HUBIplan Testbetrieb (erfundene Angaben)",
        "legal_form": "Einzelunternehmen",
        "street": "Teststraße 1",
        "postal_code": "12345",
        "city": "Musterstadt",
        "email": "betrieb@hubiplan.test",
        "phone": "0123 4567890",
    },
    "federation": {
        "phone": "02131 000001",
        "registered": True,
        "register_court": "Amtsgericht Musterstadt (erfunden)",
        "register_number": "VR 0001",
    },
    "club": {
        "legal_form": "eingetragener Verein",
        "phone": "02131 000002",
        "registered": True,
        "register_court": "Amtsgericht Musterstadt (erfunden)",
        "register_number": "VR 0002",
    },
}

FILLED = ["name", "legal_form", "street", "phone", "register_number", "privacy_text"]


def _untouched(imprint: Imprint) -> bool:
    return not any(getattr(imprint, f) for f in FILLED)


def seed_imprints(orgs: dict[str, Organization]) -> None:
    # Vorstände vertreten die Einheiten (Rolle „Vorstand“ der Demodaten)
    Role.objects.filter(
        organization__in=[orgs["federation"], orgs["club"]], name="Vorstand"
    ).update(represents=True)
    for key in ("platform", "federation", "club"):
        org = orgs[key]
        imprint = ensure(org)
        if not _untouched(imprint):
            continue
        for field, value in DEMO[key].items():
            setattr(imprint, field, value)
        imprint.mode = Imprint.Mode.OWN
        imprint.save()
        # Erst nach dem Speichern erzeugen, damit der Text die Angaben enthält
        imprint.privacy_text = privacy_for(org)
        # Demodaten: gleich veröffentlicht
        imprint.privacy_published_text = imprint.privacy_text
        imprint.privacy_published_at = timezone.now()
        imprint.save(
            update_fields=[
                "privacy_text",
                "privacy_published_text",
                "privacy_published_at",
                "updated_at",
            ]
        )
