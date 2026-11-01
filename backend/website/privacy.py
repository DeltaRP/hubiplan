"""Datenschutzhinweise der Webseite (Art. 13 DSGVO) und Prüfliste vor „öffentlich“.

Erzeugt nur die Abschnitte, die auf die Webseite tatsächlich zutreffen. Was
HUBIplan nicht wissen kann, steht in eckigen Klammern. Ein Vorschlag, keine
Rechtsberatung.
"""

from __future__ import annotations

import hashlib
import json

from django.db.models import Q
from django.utils import timezone

from access.models import Role
from core.tenancy import rls_bypass
from organizations import imprint as imprint_service
from organizations.imprint_generator import (
    _address,
    _bullets,
    _contact,
    _platform_name,
    _representatives,
)
from organizations.models import Imprint, SocialLink

from . import services
from .content_models import WebsiteText
from .models import Website


def _section(title: str, *parts: str) -> str:
    """Abschnitt als Markdown, wie ihn die Webseite und der Editor zeigen:
    Zwischenüberschrift, darunter Absätze; mehrzeilige Angaben (z. B. Anschrift)
    behalten ihre Zeilen."""
    body = []
    for part in parts:
        if not part:
            continue
        body.append(part if part.lstrip().startswith("- ") else part.replace("\n", "\\\n"))
    return "\n\n".join([f"## {title}", *body])


# Aufsichtsbehörde für den Hinweis aufs Beschwerderecht (bisher nur NRW hinterlegt)
LDI_NRW = "Landesbeauftragte für Datenschutz und Informationsfreiheit Nordrhein-Westfalen (LDI NRW)"
# Postleitzahl-Bereiche (grob) → Bundesland; im Zweifel bleibt ein Platzhalter
PLZ_NRW = [
    (32000, 33829),
    (40000, 48739),
    (50000, 53359),
    (53600, 53949),
    (57000, 57489),
    (58000, 59969),
]


def _authority(postal_code: str) -> str:
    try:
        plz = int((postal_code or "").strip()[:5])
    except ValueError:
        return "[zuständige Aufsichtsbehörde]"
    if any(lo <= plz <= hi for lo, hi in PLZ_NRW):
        return LDI_NRW
    return "[zuständige Aufsichtsbehörde des Bundeslands]"


def facts(website: Website) -> dict:
    """Was die Webseite zeigt und tut (bestimmt den Text)."""
    org = website.organization
    with rls_bypass():
        # Rollen der Einheit und ihrer Untereinheiten (bei einer Untereinheit: ihre
        # eigenen, die im Datenbereich darüber und die der Untereinheiten darunter)
        roles = Q(organization=org)
        if services.is_unit_site(org):
            below = list(services.units_below(org).values_list("pk", flat=True))
            roles |= Q(department_id__in=[org.pk, *below])
        has_function_mail = (
            Role.all_objects.filter(roles, on_website=True).exclude(contact_email="").exists()
        )
        social = (
            sorted({s.get_kind_display() for s in SocialLink.objects.filter(organization=org)})
            if website.block_on("social")
            else []
        )
        has_pages = WebsiteText.objects.filter(website=website).exclude(published_at=None).exists()
        from .social_models import SocialFeed

        posts = (
            sorted(
                {
                    f.get_kind_display()
                    for f in SocialFeed.objects.filter(website=website).exclude(access_token="")
                }
            )
            if website.block_on("posts")
            else []
        )
    return {
        "board": website.block_on("board"),
        "units": website.block_on("units") and website.units_mode != Website.Units.NONE,
        "events": website.block_on("events"),
        # Würdenträger und frühere Amtsinhaber (Ämter) stehen im selben Absatz
        "honors": website.block_on("honors")
        or website.block_on("offices")
        or website.block_on("honorary"),
        "contact": website.block_on("contact"),
        # Wettbewerbsergebnisse (nur mit Modul Wettbewerbe)
        "results": website.block_on("results") and "competitions" in (org.enabled_modules or []),
        "function_mail": has_function_mail,
        "social": social,
        "pages": has_pages,
        "posts": posts,
        # Wettbewerbsergebnisse (nur mit Modul Wettbewerbe); nur wenn zutreffend im Stand,
        # damit bestehende Texte nicht als veraltet gelten
        **(
            {"results": True}
            if website.block_on("results") and "competitions" in (org.enabled_modules or [])
            else {}
        ),
    }


def facts_hash(website: Website) -> str:
    return hashlib.sha256(json.dumps(facts(website), sort_keys=True).encode()).hexdigest()


def is_outdated(website: Website) -> bool:
    return (
        website.privacy_mode == "text"
        and bool(website.privacy_facts)
        and website.privacy_facts != facts_hash(website)
    )


def website_privacy(website: Website) -> str:
    org = website.organization
    owner, imprint = imprint_service.owner_of(org)
    if imprint.mode != Imprint.Mode.OWN:
        owner, imprint = org, imprint_service.ensure(org)
    d = imprint_service.details(owner, imprint)
    f = facts(website)
    host = "[Hosting-Anbieter, Standort des Rechenzentrums]"
    operator = _platform_name()
    operator = (
        "dem Betreiber von HUBIplan"
        if operator == "HUBIplan"
        else f"{operator} (Betreiber von HUBIplan)"
    )
    n = 0

    def nr() -> str:
        nonlocal n
        n += 1
        return f"{n}."

    sections = [
        f"Datenschutzhinweise für die Webseite von {d['name']}",
        "Dieser Text wurde von HUBIplan aus den Einstellungen der Webseite erzeugt. Bitte prüfen "
        "und ergänzen; er ersetzt keine rechtliche Beratung.",
        _section(
            f"{nr()} Verantwortlich",
            "\n".join([_address(d), f"Vertreten durch: {_representatives(d)}", _contact(d)]),
        ),
    ]
    if d["data_protection_officer"]:
        sections.append(_section("Datenschutzbeauftragte(r)", d["data_protection_officer"]))
    sections.append(
        _section(
            f"{nr()} Hosting",
            f"Die Webseite und die Vereinsverwaltung HUBIplan, aus der sie ihre Inhalte bezieht, "
            f"laufen bei {operator} auf einem Server bei {host}. Mit dem Betreiber besteht ein "
            "Vertrag zur Auftragsverarbeitung (Art. 28 DSGVO).",
        )
    )
    sections.append(
        _section(
            f"{nr()} Aufruf der Webseite",
            "Beim Aufruf verarbeitet der Server technisch notwendige Daten (IP-Adresse, Zeitpunkt, "
            "aufgerufene Seite, Browserkennung), um die Seite auszuliefern und vor Missbrauch zu "
            "schützen (Art. 6 Abs. 1 lit. f DSGVO). Zugriffsprotokolle werden nach [Anzahl] Tagen "
            "gelöscht. IP-Adressen werden außerdem kurzzeitig im Arbeitsspeicher gehalten, um zu "
            "viele Anfragen zu begrenzen.",
        )
    )
    sections.append(
        _section(
            f"{nr()} Cookies",
            "Die Webseite setzt keine Cookies für Besucher, keine Analyse- oder Werbe-Cookies und "
            "lädt keine Inhalte von Dritten (keine eingebetteten Videos, Karten oder Schriften "
            "fremder Anbieter). Ein Cookie gibt es nur für Personen, die eine nicht öffentliche "
            "Vorschau der Webseite ansehen (technisch notwendig, § 25 Abs. 2 TDDDG); es läuft nach "
            "wenigen Stunden ab.",
        )
    )
    if f["contact"] or f["function_mail"]:
        lines = []
        if f["contact"]:
            lines.append(
                "Über das Kontaktformular schicken Sie uns Name, E-Mail-Adresse, Betreff und "
                "Nachricht. Wir leiten sie per E-Mail an die gewählte Funktion weiter (die "
                "aktuelle Inhaberin bzw. den aktuellen Inhaber oder die Funktionsadresse) und "
                "beantworten Ihre Anfrage (Art. 6 Abs. 1 lit. b bzw. f DSGVO)."
            )
            lines.append(
                "Zum Schutz vor Spam prüfen wir das Formular ohne Drittanbieter: mit einer kleinen "
                "Rechenaufgabe, die Ihr Browser löst, einer Zeitprüfung und einer Begrenzung je "
                "IP-Adresse. Auffällige Nachrichten werden höchstens 7 Tage zurückgehalten, bis "
                "sie geprüft sind. Die versandte Mail bleibt höchstens 7 Tage im Postausgang; "
                "danach liegt sie nur noch im Postfach der Empfänger."
            )
        if f["function_mail"]:
            lines.append(
                "Wenn Sie uns über eine angegebene E-Mail-Adresse schreiben, verarbeiten wir Ihre "
                "Adresse und Ihre Nachricht, um zu antworten (Art. 6 Abs. 1 lit. b bzw. f DSGVO)."
            )
        sections.append(_section(f"{nr()} Kontakt", *lines))
    if f["events"]:
        sections.append(
            _section(
                f"{nr()} Termine und Kalender-Abo",
                "Unsere öffentlichen Termine können Sie als Kalender abonnieren. Ihr Kalender ruft "
                "die Kalenderdatei dann regelmäßig bei uns ab; dabei fallen nur die oben "
                "genannten Zugriffsdaten an. Eine Anmeldung ist nicht nötig.",
            )
        )
    people = []
    if f["board"]:
        people.append(
            "Vorstand und Ansprechpartner (auch der Untereinheiten): Name und Funktion "
            "(berechtigtes Interesse, Art. 6 Abs. 1 lit. f DSGVO); Foto, persönliche E-Mail-"
            "Adresse und Telefonnummer nur mit Einwilligung (Art. 6 Abs. 1 lit. a DSGVO)"
        )
    if f["honors"]:
        people.append(
            "Würdenträger und Chronik (z. B. Könige, frühere Vorsitzende, Ehrenmitglieder): "
            "Name, Jahr bzw. Zeitraum und Würde, wie im Schützenwesen üblich (berechtigtes "
            "Interesse, Art. 6 Abs. 1 lit. f DSGVO); Fotos nur mit Einwilligung"
        )
    if f.get("results"):
        people.append(
            "Ergebnisse von Wettbewerben (z. B. Preis- und Vogelschießen): Name, Platz, Wert und "
            "Untereinheit, wie bei öffentlichen Wettbewerben üblich (berechtigtes Interesse, "
            "Art. 6 Abs. 1 lit. f DSGVO); bei Teilnehmern unter 18 Jahren nur mit Einwilligung "
            "(Art. 6 Abs. 1 lit. a DSGVO), sonst erscheint der Platz ohne Namen"
        )
    if people:
        sections.append(
            _section(
                f"{nr()} Personen auf dieser Webseite",
                _bullets(people),
                "Sie können der Veröffentlichung Ihres Namens jederzeit widersprechen "
                "(Art. 21 DSGVO) und Einwilligungen für die Zukunft widerrufen, z. B. "
                + ("über das Kontaktformular, " if f["contact"] else "")
                + f"per E-Mail an {d['email'] or 'uns'} oder als Mitglied im Mitgliederbereich. "
                "Wir entfernen "
                "die Angaben dann von der Webseite.",
            )
        )
    if f["social"]:
        sections.append(
            _section(
                f"{nr()} Links zu sozialen Netzwerken",
                f"Wir verlinken unsere Auftritte bei {', '.join(f['social'])}. Es sind einfache "
                "Links: Erst wenn Sie einen anklicken, verlassen Sie unsere Webseite, und der "
                "jeweilige Anbieter verarbeitet Ihre Daten nach seinen eigenen Bestimmungen.",
            )
        )
    if f.get("posts"):
        sections.append(
            _section(
                f"{nr()} Beiträge aus unseren Kanälen bei {', '.join(f['posts'])}",
                "Unter „Aktuelles“ zeigen wir Beiträge, die wir selbst bei "
                f"{', '.join(f['posts'])} veröffentlicht haben. Unser Server holt Text und Bilder "
                "über die Schnittstelle des Anbieters Meta ab und speichert sie bei uns; die "
                "Bilder werden dabei ohne Metadaten neu gespeichert. Beim Besuch unserer "
                "Webseite werden keine Daten an Meta übertragen, es werden keine Inhalte von "
                "Meta nachgeladen und keine Cookies gesetzt. Löschen wir einen Beitrag beim "
                "Anbieter, verschwindet er auch hier, spätestens nach einer Stunde.",
                "Auf Fotos und in Texten können Personen zu sehen oder genannt sein. "
                "Rechtsgrundlage ist wie bei der Veröffentlichung im Netzwerk Ihre Einwilligung "
                "(Art. 6 Abs. 1 lit. a DSGVO) oder unser berechtigtes Interesse an der "
                "Darstellung unseres Vereinslebens (Art. 6 Abs. 1 lit. f DSGVO). Sie können "
                "jederzeit widersprechen; wir blenden den Beitrag dann aus.",
            )
        )
    sections.append(
        _section(
            f"{nr()} Ihre Rechte",
            "Sie haben das Recht auf Auskunft (Art. 15 DSGVO), Berichtigung (Art. 16), Löschung "
            "(Art. 17), Einschränkung der Verarbeitung (Art. 18), Datenübertragbarkeit (Art. 20) "
            "und Widerspruch (Art. 21).",
            "Sie können sich bei einer Datenschutz-Aufsichtsbehörde beschweren, z. B. bei: "
            f"{_authority(d['address']['postal_code'])}.",
        )
    )
    sections.append(f"Stand: {timezone.localdate():%d.%m.%Y}")
    return "\n\n".join(sections) + "\n"


def generate(website: Website) -> None:
    website.privacy_text = website_privacy(website)
    website.privacy_facts = facts_hash(website)
    website.privacy_generated_at = timezone.now()


# --- Prüfliste vor „öffentlich“ ---


def checks(website: Website) -> list[dict]:
    """Prüfpunkte; ``blocking`` verhindert das Schalten auf „öffentlich“."""
    org = website.organization
    owner, imprint = imprint_service.owner_of(org)
    result = []
    if owner.pk != org.pk:
        result.append(
            {
                "key": "imprint",
                "label": "Eigenes Impressum",
                "ok": False,
                "blocking": True,
                "hint": f"Zurzeit gilt das Impressum von {owner.name}. Die Webseite braucht ein "
                "eigenes Impressum (Einstellungen › Impressum).",
            }
        )
    elif imprint.mode == Imprint.Mode.LINK:
        ok = bool(imprint.external_url)
        result.append(
            {
                "key": "imprint",
                "label": "Impressum (Link)",
                "ok": ok,
                "blocking": True,
                "hint": "" if ok else "Adresse des eigenen Impressums fehlt.",
            }
        )
    else:
        data = imprint_service.details(owner, imprint)
        missing = [
            m for m in imprint_service.missing(owner, imprint, data) if m != "Datenschutzhinweise"
        ]
        result.append(
            {
                "key": "imprint",
                "label": "Impressum vollständig",
                "ok": not missing,
                "blocking": True,
                "hint": f"Es fehlt: {', '.join(missing)}." if missing else "",
            }
        )
        has_pages = WebsiteText.objects.filter(website=website).exclude(published_at=None).exists()
        if has_pages:
            ok = bool(data["responsible"])
            result.append(
                {
                    "key": "responsible",
                    "label": "Verantwortlich für den Inhalt (§ 18 Abs. 2 MStV)",
                    "ok": ok,
                    "blocking": False,
                    "hint": ""
                    if ok
                    else "Die Webseite hat eigene Texte. Bitte im Impressum eine "
                    "verantwortliche Person mit Anschrift angeben, z. B. die Schriftführerin.",
                }
            )
    privacy_ok = (
        bool(website.privacy_url)
        if website.privacy_mode == "link"
        else bool(website.privacy_published_text.strip())
    )
    result.append(
        {
            "key": "privacy",
            "label": "Datenschutzhinweise der Webseite",
            "ok": privacy_ok,
            "blocking": True,
            "hint": ""
            if privacy_ok
            else "Bitte erzeugen oder eintragen, prüfen und veröffentlichen.",
        }
    )
    if privacy_ok and is_outdated(website):
        result.append(
            {
                "key": "privacy_outdated",
                "label": "Datenschutzhinweise passen zu den Einstellungen",
                "ok": False,
                "blocking": False,
                "hint": "Die Bausteine haben sich seit der Erzeugung geändert. Bitte neu erzeugen "
                "und prüfen.",
            }
        )
    has_domain = website.domains.exists()
    result.append(
        {
            "key": "domain",
            "label": "Domain eingetragen",
            "ok": has_domain,
            "blocking": True,
            "hint": "" if has_domain else "Ohne Domain findet die Webseite die Einheit nicht.",
        }
    )
    return result


def blocking(website: Website) -> list[str]:
    return [
        c["label"] + (f": {c['hint']}" if c["hint"] else "")
        for c in checks(website)
        if c["blocking"] and not c["ok"]
    ]


def public_privacy(website: Website) -> dict:
    return {
        "mode": website.privacy_mode,
        "text": website.privacy_published_text if website.privacy_mode == "text" else "",
        "url": website.privacy_url if website.privacy_mode == "link" else "",
        "generated_at": website.privacy_generated_at,
    }
