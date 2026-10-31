"""Datenschutztexte aus den tatsächlichen Einstellungen erzeugen.

Die Texte beschreiben, was HUBIplan für eine Einheit wirklich verarbeitet:
eingeschaltete Module, SEPA, Meldung an die übergeordnete Einheit, Fotos,
Mitgliederbereich, Löschfrist. Was HUBIplan nicht wissen kann (z. B. der
Hosting-Anbieter), steht in eckigen Klammern. Die Texte sind ein Vorschlag und
ersetzen keine rechtliche Prüfung.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone

from core.tenancy import rls_bypass

from . import imprint as service
from .models import Department, Imprint, Organization, PlatformSettings


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " und " + items[-1]


def _address(d: dict) -> str:
    a = d["address"]
    parts = [d["name"], a["street"], f"{a['postal_code']} {a['city']}".strip()]
    return ", ".join(p for p in parts if p)


def _contact(d: dict) -> str:
    parts = []
    if d["email"]:
        parts.append(f"E-Mail: {d['email']}")
    if d["phone"]:
        parts.append(f"Telefon: {d['phone']}")
    return ", ".join(parts) or "[E-Mail-Adresse]"


def _representatives(d: dict) -> str:
    if d["representatives_text"]:
        return " ".join(d["representatives_text"].split())
    if d["representatives"]:
        return _join([f"{r['name']} ({r['role']})" for r in d["representatives"]])
    return "[Vorstand nach § 26 BGB]"


def _section(title: str, *lines: str) -> str:
    body = "\n".join(line for line in lines if line)
    return f"{title}\n{body}"


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _today() -> str:
    return timezone.localdate().strftime("%d.%m.%Y")


def _platform_name() -> str:
    platform = Organization.platform()
    imprint = service.ensure(platform)
    return imprint.name or platform.name


def _facts(org: Organization) -> dict:
    """Was die Einheit eingeschaltet hat (ohne Mitgliederdaten)."""
    from billing.models import BillingSettings
    from customfields.models import FieldDefinition
    from members.models import MemberType

    modules = set(org.enabled_modules or [])
    with rls_bypass():
        sepa = (
            "billing" in modules
            and BillingSettings.objects.filter(organization=org, sepa_enabled=True).exists()
        )
        reported = MemberType.objects.filter(organization=org, reported=True).exists()
        has_fields = FieldDefinition.objects.filter(organization=org, is_archived=False).exists()
        has_units = Department.objects.filter(organization=org, is_active=True).exists()
    parent = org.parent if org.parent and org.parent.type == Organization.Type.FEDERATION else None
    return {
        "modules": modules,
        "sepa": sepa,
        "reported": reported and parent is not None,
        "parent": parent,
        "has_fields": has_fields,
        "has_units": has_units,
        "keeps_members": org.keeps_members or org.type == Organization.Type.UNIT,
    }


def unit_privacy(org: Organization) -> str:
    """Datenschutzhinweise einer Einheit für ihre Mitglieder (Art. 13 DSGVO)."""
    owner, imprint = service.owner_of(org)
    if imprint.mode != Imprint.Mode.OWN:
        owner, imprint = org, service.ensure(org)
    d = service.details(owner, imprint)
    f = _facts(org if org.type != Organization.Type.UNIT else org.organization or org)
    name = d["name"]
    months = PlatformSettings.load().deletion_period_months
    units = org.department_label_plural if f["has_units"] else ""

    data = [
        "Name, Vorname, Geburtsdatum, Anschrift, Telefon und E-Mail-Adresse",
        "Beginn, Ende und Art der Mitgliedschaft, Verbandsnummer, Ehrungen und Jubiläen",
    ]
    if units:
        data.append(f"Zugehörigkeit zu Untereinheiten ({units}) und Funktionen darin")
    if f["has_fields"]:
        data.append(
            "weitere Angaben, die wir für die Vereinsarbeit festgelegt haben (Zusatzfelder)"
        )
    if "billing" in f["modules"]:
        data.append("Beiträge, Rechnungen und Zahlungen")
    if f["sepa"]:
        data.append("Bankverbindung (IBAN, BIC, Kontoinhaber) und SEPA-Lastschriftmandat")
    data.append(
        "Foto für die Mitgliederliste und den Mitgliedsausweis, wenn Sie eingewilligt haben"
    )

    purposes = [
        "Mitgliederverwaltung nach unserer Satzung, Einladungen und Mitteilungen "
        "(Art. 6 Abs. 1 lit. b DSGVO)",
        "Ehrungen und Jubiläen (Art. 6 Abs. 1 lit. b DSGVO)",
    ]
    if "billing" in f["modules"]:
        purposes.append(
            "Beiträge und Rechnungen"
            + (", Einzug per SEPA-Lastschrift" if f["sepa"] else "")
            + " (Art. 6 Abs. 1 lit. b DSGVO); Aufbewahrung der Buchungsbelege nach "
            "steuerlichen Vorschriften (Art. 6 Abs. 1 lit. c DSGVO)"
        )
    if "finance" in f["modules"]:
        purposes.append("Kassenführung und Kassenprüfung (Art. 6 Abs. 1 lit. c DSGVO)")
    if "events" in f["modules"]:
        purposes.append(
            "Termine, Zu- und Absagen zu Veranstaltungen und Teilnehmerlisten "
            "(Art. 6 Abs. 1 lit. b DSGVO)"
        )
    purposes.append(
        "Rundschreiben per E-Mail oder Post. Informationen, die keine offizielle Mitteilung "
        "sind, können Sie über den Link in jeder Mail abbestellen "
        "(Art. 6 Abs. 1 lit. b und f DSGVO)"
    )
    if org.type != Organization.Type.PLATFORM:
        from letterhead.data import owner_of as letterhead_owner

        _, letterhead = letterhead_owner(org)
        if letterhead.show_board:
            purposes.append(
                "Briefbogen: Name und Funktion der Vertretungsberechtigten und weiterer "
                "Funktionsträger stehen in der Fußzeile unserer Schreiben; eigene private "
                "Kontaktdaten erscheinen dort nur, wenn die Person sie selbst auswählt "
                "(Art. 6 Abs. 1 lit. b und f DSGVO)"
            )
    if org.type in (Organization.Type.CLUB, Organization.Type.FEDERATION):
        from website.services import module_enabled, website_of

        if module_enabled(org) and website_of(org) is not None:
            purposes.append(
                "Veröffentlichung auf unserer Webseite: Name und Funktion von Vorstand und "
                "Ansprechpartnern sowie Würden und Chronik (Art. 6 Abs. 1 lit. f DSGVO, "
                "Widerspruch jederzeit möglich); Foto, persönliche E-Mail-Adresse und "
                "Telefonnummer nur mit Ihrer Einwilligung (Art. 6 Abs. 1 lit. a DSGVO)"
            )
    purposes.append(
        "Fotos und Mitgliedsausweis mit QR-Code nur mit Ihrer Einwilligung "
        "(Art. 6 Abs. 1 lit. a DSGVO). Der QR-Code zeigt beim Scannen nur Name, Status der "
        "Mitgliedschaft und Zugehörigkeit."
    )
    if org.member_portal_enabled:
        purposes.append(
            "Mitgliederbereich: Sie können Ihre Daten online einsehen und Änderungen melden "
            "(Art. 6 Abs. 1 lit. b DSGVO)"
        )

    recipients = []
    if units:
        recipients.append(
            f"Verantwortliche der Untereinheiten ({units}): die Daten ihrer eigenen Mitglieder"
        )
    if f["reported"]:
        parent = f["parent"]
        recipients.append(
            f"{parent.name}: Name, Geburtsdatum, Anschrift und Mitgliedszeiten der Mitglieder, "
            "die wir dorthin melden (Mitgliedschaft im Verband, Verbandsbeitrag, Ehrungen)"
        )
        if parent.federation_member_access != Organization.MemberAccess.NONE:
            recipients.append(
                f"{parent.name} kann die Mitgliedsdaten in HUBIplan außerdem "
                + (
                    "einsehen"
                    if parent.federation_member_access == Organization.MemberAccess.READ
                    else "einsehen und ändern"
                )
            )
    if f["sepa"]:
        recipients.append("unsere Bank und Ihre Bank für den Lastschrifteinzug")
    operator = _platform_name()
    operator = (
        "der Betreiber von HUBIplan"
        if operator == "HUBIplan"
        else f"{operator} als Betreiber von HUBIplan"
    )
    recipients.append(
        f"{operator}, der die Daten in unserem Auftrag speichert "
        "(Auftragsverarbeitung nach Art. 28 DSGVO)"
    )
    recipients.append("Kassenprüfer und Behörden, soweit gesetzlich vorgeschrieben")

    sections = [
        f"Datenschutzhinweise für Mitglieder von {name}",
        "Dieser Text wurde von HUBIplan aus den Einstellungen erzeugt. Bitte prüfen und "
        "ergänzen; er ersetzt keine rechtliche Beratung.",
        _section(
            "1. Verantwortlich",
            _address(d),
            f"Vertreten durch: {_representatives(d)}",
            _contact(d),
        ),
    ]
    if d["data_protection_officer"]:
        sections.append(_section("Datenschutzbeauftragte(r)", d["data_protection_officer"]))
    sections += [
        _section("2. Welche Daten wir verarbeiten", _bullets(data)),
        _section("3. Wofür und auf welcher Rechtsgrundlage", _bullets(purposes)),
        _section("4. Wer die Daten erhält", _bullets(recipients)),
        _section(
            "5. Wie lange wir die Daten speichern",
            "Solange Sie Mitglied sind. Nach dem Austritt löschen wir Ihre Daten nach "
            f"{months} Monaten. Ausgenommen sind Angaben, die wir aufbewahren müssen, z. B. "
            "Buchungsbelege (bis zu 10 Jahre nach § 147 AO).",
        ),
        _section(
            "6. Ihre Rechte",
            "Sie haben das Recht auf Auskunft (Art. 15 DSGVO), Berichtigung (Art. 16), "
            "Löschung (Art. 17), Einschränkung der Verarbeitung (Art. 18), "
            "Datenübertragbarkeit (Art. 20) und Widerspruch (Art. 21). Eine Einwilligung, "
            "z. B. für Fotos, können Sie jederzeit für die Zukunft widerrufen. Wenden Sie sich "
            f"dazu an {d['email'] or 'uns'}.",
            "Sie können sich bei einer Datenschutz-Aufsichtsbehörde beschweren, z. B. bei der "
            "Behörde des Bundeslands, in dem wir unseren Sitz haben.",
        ),
        _section(
            "7. Pflicht zur Angabe",
            "Name, Anschrift und Geburtsdatum brauchen wir für die Mitgliedschaft. Ohne sie "
            "ist eine Aufnahme nicht möglich. Alle weiteren Angaben sind freiwillig.",
        ),
        _section(
            "8. HUBIplan-App",
            "Mit der HUBIplan-App für Android sehen Sie dieselben Daten wie im "
            "Mitgliederbereich im Browser. Für jedes verbundene Gerät speichern wir einen "
            "Geräteschlüssel, die Bezeichnung des Geräts und den Zeitpunkt der letzten Nutzung "
            "(Art. 6 Abs. 1 lit. b DSGVO). Geräte können Sie jederzeit unter „Mein Konto“ "
            "abmelden.",
            "Auf Wunsch trägt die App Termine in einen Kalender auf Ihrem Gerät ein. Diese "
            "Einträge können andere Apps auf Ihrem Gerät lesen, denen Sie den Zugriff auf den "
            "Kalender erlaubt haben; ob der Kalender mit einem Dienst wie Google abgeglichen "
            "wird, bestimmen Sie in den Einstellungen Ihres Geräts.",
        ),
        f"Stand: {_today()}",
    ]
    return "\n\n".join(sections) + "\n"


def platform_privacy() -> str:
    """Datenschutzerklärung der Plattform aus Impressum und Betriebseinstellungen."""
    platform = Organization.platform()
    d = service.details(platform, service.ensure(platform))
    host = urlparse(settings.FRONTEND_URL).hostname or "[Adresse der Website]"
    keep_days = os.environ.get("BACKUP_KEEP_DAYS", "30")
    session_hours = settings.SESSION_COOKIE_AGE // 3600
    months = PlatformSettings.load().deletion_period_months
    from changes.models import RETENTION_DAYS

    mail = (
        f"Mails gehen über den Mailserver {settings.EMAIL_HOST} hinaus [Name des Mail-Anbieters]."
        if settings.EMAIL_HOST
        else "Derzeit werden sie nicht nach außen versandt."
    )
    sections = [
        f"Datenschutzerklärung für {host}",
        "Dieser Text wurde von HUBIplan aus den Einstellungen erzeugt. Bitte prüfen und "
        "ergänzen; er ersetzt keine rechtliche Beratung.",
        _section(
            "1. Verantwortlich",
            _address(d) if d["address"]["street"] else f"{d['name']}, [Anschrift]",
            f"Vertreten durch: {' '.join(d['representatives_text'].split())}"
            if d["representatives_text"]
            else "",
            _contact(d),
        ),
        _section(
            "2. Wofür diese Website da ist",
            "Über HUBIplan verwalten Vereine, Verbände und ihre Untereinheiten (im Folgenden "
            "Einheiten) ihre Mitglieder, Beiträge, Termine und Dokumente. Für die Daten, die "
            "eine Einheit hier über ihre Mitglieder führt, ist die Einheit selbst verantwortlich. "
            "Ihre Datenschutzhinweise sind in ihren Mails und auf ihren Seiten verlinkt. Der "
            "Betreiber verarbeitet diese Daten nur in ihrem Auftrag (Art. 28 DSGVO).",
        ),
        _section(
            "3. Aufruf der Website",
            "Beim Aufruf verarbeitet der Server technisch notwendige Daten (IP-Adresse, "
            "Zeitpunkt, aufgerufene Adresse, Browserkennung), um die Seite auszuliefern "
            "(Art. 6 Abs. 1 lit. f DSGVO). Zugriffsprotokolle mit IP-Adressen werden nicht "
            "dauerhaft gespeichert. IP-Adressen werden nur kurzzeitig im Arbeitsspeicher "
            "gehalten, um Missbrauch wie zu viele Anmeldeversuche zu begrenzen.",
        ),
        _section(
            "4. Cookies und Speicher im Browser",
            "Wir setzen nur technisch notwendige Cookies: ein Sitzungs-Cookie für die "
            f"Anmeldung (läuft nach {session_hours} Stunden ab) und ein Cookie zum Schutz vor "
            "gefälschten Anfragen (CSRF). Es gibt keine Analyse- oder Werbe-Cookies, kein "
            "Tracking und keine Inhalte von Dritten; Schriften und Skripte kommen vom eigenen "
            "Server (§ 25 Abs. 2 TDDDG).",
            "Für die Bedienung merkt sich Ihr Browser einige Angaben im eigenen Speicher "
            "(Local und Session Storage): die gewählte Einheit, die Spalten, Suche und Seite der "
            "Mitgliederlisten, die Kalenderansicht, die Seite, zu der Sie nach der Anmeldung "
            "zurückkehren, und den Verlauf zum Rückgängigmachen. Diese Angaben bleiben auf Ihrem "
            "Gerät, werden nicht an uns übertragen und dienen nur dazu, die von Ihnen genutzten "
            "Funktionen bereitzustellen (§ 25 Abs. 2 Nr. 2 TDDDG). Der Verlauf zum "
            "Rückgängigmachen wird beim Abmelden und beim Schließen des Tabs gelöscht; die "
            "übrigen Einstellungen können Sie in Ihrem Browser jederzeit löschen.",
        ),
        _section(
            "5. Benutzerkonto und Anmeldung",
            "Für ein Konto verarbeiten wir E-Mail-Adresse, Name, das Passwort nur als "
            "Prüfwert und, falls eingerichtet, die Zwei-Faktor-Anmeldung "
            "(Art. 6 Abs. 1 lit. b DSGVO). Konten legt die jeweilige Einheit an.",
            "Zum Konto gehören außerdem Ihre Anzeigeeinstellung für die Lernhilfen und die "
            "Liste der Erklärungen, die Sie ausgeblendet haben. Sie dienen nur der Anzeige, "
            "werden nicht ausgewertet und mit dem Konto gelöscht. Unter „Mein Konto“ können "
            "Sie beides jederzeit ändern (Art. 6 Abs. 1 lit. b DSGVO).",
        ),
        _section(
            "6. E-Mails",
            "Mails, die Einheiten über HUBIplan versenden, werden im Postausgang der Einheit "
            f"gespeichert. {mail}",
        ),
        _section(
            "7. Hosting, Sicherungen und Protokolle",
            "Die Website läuft auf einem Server bei [Hosting-Anbieter, Standort des "
            "Rechenzentrums], mit dem ein Vertrag zur Auftragsverarbeitung besteht.",
            "Die Datenbank wird täglich verschlüsselt gesichert; Sicherungen werden nach "
            f"{keep_days} Tagen gelöscht.",
            "Änderungen an Daten werden zum Rückgängigmachen "
            f"{RETENTION_DAYS} Tage aufbewahrt. Daten ausgetretener Mitglieder löschen die "
            f"Einheiten nach {months} Monaten, soweit keine Aufbewahrungspflicht besteht.",
        ),
        _section(
            "8. Ihre Rechte",
            "Sie haben das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der "
            "Verarbeitung, Datenübertragbarkeit und Widerspruch (Art. 15 bis 21 DSGVO). Bei "
            "Daten, die eine Einheit über Sie führt, wenden Sie sich am besten direkt an sie. "
            "Sie können sich bei einer Datenschutz-Aufsichtsbehörde beschweren, z. B. bei der "
            "Behörde des Bundeslands, in dem der Betreiber seinen Sitz hat.",
        ),
        f"Stand: {_today()}",
    ]
    return "\n\n".join(sections) + "\n"


def privacy_for(org: Organization) -> str:
    if org.type == Organization.Type.PLATFORM:
        return platform_privacy()
    return unit_privacy(org)
