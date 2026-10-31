"""Öffentliche Schnittstelle der Webseite und Kontaktformular (alles erfunden)."""

import datetime
import hashlib
import time

import pytest
from django.core import mail, signing
from django.test import Client
from django.utils import timezone

from access.models import Role, RoleAssignment
from core.tenancy import rls_bypass
from events.models import Event
from organizations.models import Department, DepartmentRole
from website import contact, services
from website.models import HeldMessage, Website, WebsiteDomain, WebsiteText

from .factories import make_member

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def private_root(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


@pytest.fixture
def setup(orgs):
    org = orgs["a"]
    org.enabled_modules = ["members", "events", "website"]
    org.contact_email = "info@verein-a.example.org"
    org.save()
    site = Website.objects.create(organization=org, public_key="schluessel-a", state="public")
    WebsiteDomain.objects.create(organization=org, website=site, hostname="www.verein-a.example")
    erika = make_member(org, "Erika", "Beispiel", email="erika@example.org")
    otto = make_member(org, "Otto", "Muster", email="otto@example.org")
    chair = Role.objects.create(
        organization=org, name="1. Vorsitzende", on_website=True, website_position=1
    )
    RoleAssignment.objects.create(organization=org, role=chair, person=erika.person)
    secret = Role.objects.create(organization=org, name="Datenschutz", on_website=False)
    RoleAssignment.objects.create(organization=org, role=secret, person=otto.person)
    unit = Department.objects.create(organization=org, parent=org, name="Jägerzug")
    lead = DepartmentRole.objects.create(department=unit, name="Zugführer", on_website=True)
    from members.models import DepartmentRoleHolder

    DepartmentRoleHolder.objects.create(
        organization=org, membership=otto, role=lead, valid_from=datetime.date(2020, 1, 1)
    )
    return {"org": org, "site": site, "erika": erika, "otto": otto, "unit": unit, "chair": chair}


def get(path, **headers):
    return Client().get(f"/api/public/site/v1/{path}", **headers)


class TestZustand:
    def test_hostname_aufloesen(self, setup):
        assert get("resolve/?host=WWW.verein-a.example:443").json()["key"] == "schluessel-a"
        assert get("resolve/?host=unbekannt.example").status_code == 404

    def test_oeffentlich(self, setup):
        resp = get("schluessel-a/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Verein A" and data["state"] == "public"
        assert data["email"] == "info@verein-a.example.org"
        assert data["units"][0]["slug"] == "jaegerzug"
        assert resp["Access-Control-Allow-Origin"] == "*"
        assert "public" in resp["Cache-Control"]
        # keine internen Nummern
        assert '"id": ' not in resp.content.decode().replace(" ", " ")

    def test_wartung_nur_wartungsangaben(self, setup):
        setup["site"].state = "maintenance"
        setup["site"].save()
        resp = get("schluessel-a/")
        assert resp.status_code == 503
        data = resp.json()
        assert data["maintenance_text"] and "menu" not in data and "email" not in data
        assert get("schluessel-a/board/").status_code == 404
        assert get("schluessel-a/events/").status_code == 404
        assert get("schluessel-a/contact/").status_code == 404
        assert get("schluessel-a/imprint/").status_code == 200

    def test_wartung_mit_vorschau(self, setup):
        site = setup["site"]
        site.state = "maintenance"
        site.save()
        token = services.open_token(site)
        resp = Client().post(
            "/api/public/site/v1/schluessel-a/preview/", {"token": token}, "application/json"
        )
        assert resp.status_code == 200
        session = resp.json()["session"]
        # Gesamtaudit 30.10. (I-S01): derselbe kurze Schlüssel gilt nur einmal
        again = Client().post(
            "/api/public/site/v1/schluessel-a/preview/", {"token": token}, "application/json"
        )
        assert again.status_code == 403
        resp = get("schluessel-a/board/", HTTP_X_PREVIEW_SESSION=session)
        assert resp.status_code == 200
        assert resp["Cache-Control"] == "private, no-store"
        assert resp["X-Robots-Tag"] == "noindex"
        info = get("schluessel-a/", HTTP_X_PREVIEW_SESSION=session).json()
        assert info["preview"] is True and "menu" in info
        bad = Client().post(
            "/api/public/site/v1/schluessel-a/preview/", {"token": "falsch"}, "application/json"
        )
        assert bad.status_code == 403

    def test_aus_und_modul_aus(self, setup, settings):
        site = setup["site"]
        site.state = "off"
        site.save()
        assert get("schluessel-a/").status_code == 404
        site.state = "public"
        site.save()
        settings.WEBSITE_PREVIEW_ONLY = True
        assert get("schluessel-a/").status_code == 503
        settings.WEBSITE_PREVIEW_ONLY = False
        org = setup["org"]
        org.enabled_modules = ["members"]
        org.save()
        assert get("schluessel-a/").status_code == 404
        assert get("resolve/?host=www.verein-a.example").status_code == 404


class TestPersonen:
    def test_vorstand_nur_markierte_rollen(self, setup):
        data = get("schluessel-a/board/").json()
        assert [r["name"] for r in data["roles"]] == ["1. Vorsitzende"]
        holder = data["roles"][0]["holders"][0]
        assert holder == {"name": "Erika Beispiel", "photo_url": None}
        assert data["roles"][0]["contact_form"] is True
        assert "Otto" not in str(data)

    def test_ehrung_in_der_mehrzahl(self, setup):
        """Ralf 2026-10-31: bei mehreren Trägern steht die Ehrung in der Mehrzahl."""
        from members.models import HonoraryTitle, HonoraryTitleAward

        org = setup["site"].organization
        title = HonoraryTitle.objects.create(organization=org, name="Ehrenmitglied", is_public=True)
        since = datetime.date(2000, 1, 1)
        HonoraryTitleAward.objects.create(
            organization=org, person=setup["erika"].person, title=title, valid_from=since
        )
        honorary = get("schluessel-a/board/").json()["honorary"]
        assert honorary[0]["title"] == honorary[0]["heading"] == "Ehrenmitglied"
        HonoraryTitleAward.objects.create(
            organization=org, person=setup["otto"].person, title=title, valid_from=since
        )
        assert get("schluessel-a/board/").json()["honorary"][0]["heading"] == "Ehrenmitglieder"
        title.name_plural = "Ehrenmitglieder des Vereins"
        title.save()
        heading = get("schluessel-a/board/").json()["honorary"][0]["heading"]
        assert heading == "Ehrenmitglieder des Vereins"

    def test_widerspruch_und_einwilligung(self, setup):
        erika = setup["erika"]
        services.set_entry(erika, "email", True, "paper", None)
        holder = get("schluessel-a/board/").json()["roles"][0]["holders"][0]
        assert holder["email"] == "erika@example.org" and "phone" not in holder
        services.set_entry(erika, "name", True, "paper", None)
        assert get("schluessel-a/board/").json()["roles"] == []
        setup["site"].show_vacant = True
        setup["site"].save()
        role = get("schluessel-a/board/").json()["roles"][0]
        assert role["vacant"] is True and role["holders"] == []

    def test_namensform(self, setup):
        setup["site"].name_format = "initial"
        setup["site"].save()
        holder = get("schluessel-a/board/").json()["roles"][0]["holders"][0]
        assert holder["name"] == "Erika B."

    def test_zug_ohne_termine(self, setup):
        units = {u["slug"]: u["has_events"] for u in get("schluessel-a/").json()["units"]}
        assert units == {"jaegerzug": False}

    def test_zugseite(self, setup):
        data = get("schluessel-a/units/jaegerzug/").json()
        assert data["name"] == "Jägerzug"
        assert data["roles"][0]["holders"][0]["name"] == "Otto Muster"
        assert get("schluessel-a/units/gibtsnicht/").status_code == 404
        setup["site"].units_mode = "none"
        setup["site"].save()
        assert get("schluessel-a/units/jaegerzug/").status_code == 404

    def test_chronik_der_vorsitzenden(self, setup):
        chair = setup["chair"]
        chair.in_chronicle = True
        chair.save()
        RoleAssignment.objects.create(
            organization=setup["org"],
            role=chair,
            person=setup["otto"].person,
            valid_from=datetime.date(1990, 1, 1),
            valid_until=datetime.date(1999, 12, 31),
        )
        chronicle = get("schluessel-a/board/").json()["chronicle"][0]
        assert [h["name"] for h in chronicle["holders"]] == ["Otto Muster", "Erika Beispiel"]
        assert chronicle["holders"][0]["current"] is False

    def test_aemter_eigener_schalter(self, setup):
        """Schalter „Ämter“ steuert die früheren Amtsinhaber, „Vorstand“ nur den Vorstand."""
        setup["chair"].in_chronicle = True
        setup["chair"].save()
        site = setup["site"]
        site.blocks = {"board": True, "history": True, "offices": False}
        site.save()
        data = get("schluessel-a/board/").json()
        assert data["roles"] and data["chronicle"] == []
        info = get("schluessel-a/").json()
        assert info["blocks"]["offices"] is False and info["has_offices"] is False
        site.blocks = {"board": False, "history": False, "offices": True}
        site.save()
        data = get("schluessel-a/board/").json()
        assert data["roles"] == [] and data["chronicle"]
        assert get("schluessel-a/").json()["has_offices"] is True
        site.blocks = {"board": False, "history": False, "offices": False}
        site.save()
        assert get("schluessel-a/board/").status_code == 404

    def test_chronik_nur_mit_text(self, setup):
        """„has_history_text“: Schalter „Chronik“ an und Textseite „geschichte“ veröffentlicht."""
        from website.content_models import WebsiteText

        site = setup["site"]
        assert get("schluessel-a/").json()["has_history_text"] is False
        WebsiteText.objects.create(
            organization=site.organization,
            website=site,
            kind=WebsiteText.Kind.PAGE,
            slug="geschichte",
            title="Chronik",
            published_title="Chronik",
            published_body="Gegründet 1920.",
            published_at=timezone.now(),
        )
        assert get("schluessel-a/").json()["has_history_text"] is True
        site.blocks = {**site.blocks, "history": False}
        site.save()
        assert get("schluessel-a/").json()["has_history_text"] is False

    def test_neuer_schalter_gilt_als_ein(self, setup):
        """Ältere Einstellungen ohne „history“/„offices“: Chronik und Ämter bleiben sichtbar."""
        setup["site"].blocks = {"board": True}
        setup["site"].save()
        blocks = get("schluessel-a/").json()["blocks"]
        assert blocks["history"] is True and blocks["offices"] is True

    def test_startseite_standard_wie_bisher(self, setup):
        assert get("schluessel-a/").json()["home"] == [
            "carousel",
            "greeting",
            "events",
            "honors",
            "units",
        ]

    def test_startseite_folgt_einstellung_und_bereichen(self, setup):
        site = setup["site"]
        site.home_sections = [
            {"key": "units", "on": True},
            {"key": "events", "on": True},
            {"key": "greeting", "on": False},
            {"key": "instagram", "on": True},
        ]
        site.blocks = {"events": False}
        site.save()
        # Termine ganz aus: auch nicht auf der Startseite
        assert get("schluessel-a/").json()["home"] == [
            "units",
            "instagram",
            "carousel",
            "honors",
        ]


class TestInhalte:
    def test_nur_veroeffentlichte_seiten(self, setup):
        site = setup["site"]
        text = WebsiteText.objects.create(
            organization=setup["org"], website=site, kind="page", slug="geschichte", title="G"
        )
        assert get("schluessel-a/pages/geschichte/").status_code == 404
        from website.content import publish

        text.body = "Seit 1920"
        publish(text, None)
        assert get("schluessel-a/pages/geschichte/").json()["text"] == "Seit 1920"
        assert get("schluessel-a/").json()["menu"] == [{"slug": "geschichte", "title": "G"}]


class TestTermine:
    def test_oeffentliche_termine_und_abo(self, setup):
        org, unit = setup["org"], setup["unit"]
        start = timezone.now() + datetime.timedelta(days=3)
        common = {
            "organization": org,
            "starts_at": start,
            "ends_at": start + datetime.timedelta(hours=2),
        }
        with rls_bypass():
            Event.objects.create(title="Schützenfest", visibility="public", **common)
            Event.objects.create(title="Intern", visibility="members", **common)
            Event.objects.create(title="Zugabend", visibility="public", department=unit, **common)
        titles = [e["title"] for e in get("schluessel-a/events/").json()["events"]]
        assert sorted(titles) == ["Schützenfest", "Zugabend"]
        titles = [
            e["title"] for e in get("schluessel-a/events/?einheit=jaegerzug").json()["events"]
        ]
        assert titles == ["Zugabend"]
        units = {u["slug"]: u["has_events"] for u in get("schluessel-a/").json()["units"]}
        assert units == {"jaegerzug": True}
        ics = get("schluessel-a/events.ics")
        assert ics.status_code == 200 and b"Sch\xc3\xbctzenfest" in ics.content

    def test_termine_von_oben(self, orgs, setup):
        """Schalter „übergeordnete Einheiten“: öffentliche, nach unten freigegebene
        Termine des Dachverbands erscheinen mit dessen Namen."""
        fed = orgs["federation"]
        fed.enabled_modules = ["events"]
        fed.save()
        start = timezone.now() + datetime.timedelta(days=3)
        common = {
            "organization": fed,
            "starts_at": start,
            "ends_at": start + datetime.timedelta(hours=2),
        }
        with rls_bypass():
            Event.objects.create(title="Bundesfest", visibility="public", **common)
            Event.objects.create(title="Nur oben", visibility="public", share_down=False, **common)
            Event.objects.create(title="Verbandsrat", visibility="members", **common)

        def titles():
            return {e["title"]: e["owner"] for e in get("schluessel-a/events/").json()["events"]}

        assert titles() == {}
        setup["site"].include_parent_events = True
        setup["site"].save()
        assert titles() == {"Bundesfest": "Testbund"}
        # Termine einer Untereinheit bleiben bei ihr
        assert get("schluessel-a/events/?einheit=jaegerzug").json()["events"] == []


class TestKontakt:
    def form(self, recipient, **extra):
        data = get("schluessel-a/contact/").json()
        ch = data["challenge"]
        body = {
            "recipient": recipient,
            "name": "Max Besucher",
            "email": "max@example.org",
            "subject": "Frage",
            "message": "Wann ist das nächste Schützenfest?",
            "challenge": ch["token"],
            "nonce": contact.solve(ch["salt"], ch["difficulty"]),
            **extra,
        }
        return body

    def post(self, body):
        return Client().post("/api/public/site/v1/schluessel-a/contact/", body, "application/json")

    def test_empfaenger_ohne_adressen(self, setup):
        data = get("schluessel-a/contact/").json()
        names = [r["name"] for r in data["recipients"]]
        assert names == ["Verein A (allgemein)", "1. Vorsitzende", "Zugführer (Jägerzug)"]
        assert "@" not in str(data["recipients"])

    def test_senden_an_rolle(self, setup, monkeypatch):
        monkeypatch.setattr(contact, "MIN_SECONDS", 0)
        rid = get("schluessel-a/contact/").json()["recipients"][1]["id"]
        resp = self.post(self.form(rid, copy=True))
        assert resp.status_code == 200, resp.content
        assert mail.outbox[0].to == ["erika@example.org"]
        assert mail.outbox[0].reply_to == ["max@example.org"]
        assert mail.outbox[1].to == ["max@example.org"]  # Kopie

    def test_zu_schnell(self, setup):
        rid = get("schluessel-a/contact/").json()["recipients"][0]["id"]
        resp = self.post(self.form(rid))
        assert resp.status_code == 400 and "zu schnell" in resp.json()["detail"]

    def test_rechenaufgabe_falsch_und_nur_einmal(
        self, setup, monkeypatch, django_capture_on_commit_callbacks
    ):
        monkeypatch.setattr(contact, "MIN_SECONDS", 0)
        body = self.form("allgemein")
        salt = signing.loads(body["challenge"], salt=contact.SALT)["s"]
        wrong = next(
            n
            for n in range(1000)
            if contact._leading_zero_bits(hashlib.sha256(f"{salt}{n}".encode()).digest())
            < contact.DIFFICULTY
        )
        resp = self.post({**body, "nonce": wrong})
        assert resp.status_code == 400 and "Sicherheitsprüfung" in resp.json()["detail"]
        assert resp.json()["code"] == "expired"
        with django_capture_on_commit_callbacks(execute=True):
            assert self.post(body).status_code == 200
        again = self.post(body)  # schon benutzt
        assert again.status_code == 400 and again.json()["code"] == "used"

    def test_abbruch_gibt_aufgabe_frei(
        self, setup, monkeypatch, django_capture_on_commit_callbacks
    ):
        """Audit 31.10. R-CL-02: Fehler nach dem Belegen meldet nie „schon angekommen“."""
        monkeypatch.setattr(contact, "MIN_SECONDS", 0)
        body = self.form("allgemein")

        def kaputt(*args, **kwargs):
            raise RuntimeError("Datenbank weg")

        monkeypatch.setattr(contact, "_accept", kaputt)
        with pytest.raises(RuntimeError):
            self.post(body)
        monkeypatch.undo()
        monkeypatch.setattr(contact, "MIN_SECONDS", 0)
        with django_capture_on_commit_callbacks(execute=True):
            assert self.post(body).status_code == 200
        assert len(mail.outbox) >= 1

    def test_in_arbeit_ist_nicht_angekommen(self, setup, monkeypatch):
        monkeypatch.setattr(contact, "MIN_SECONDS", 0)
        body = self.form("allgemein")
        salt = signing.loads(body["challenge"], salt=contact.SALT)["s"]
        contact.consume_challenge(salt)  # andere Anfrage arbeitet noch
        resp = self.post(body)
        assert resp.status_code == 409 and resp.json()["code"] == "busy"

    def test_honigtopf(self, setup, monkeypatch):
        monkeypatch.setattr(contact, "MIN_SECONDS", 0)
        resp = self.post(self.form("allgemein", homepage="http://spam.example"))
        assert resp.status_code == 200 and mail.outbox == []

    def test_spam_wird_zurueckgehalten(self, setup, monkeypatch, board_a, api):
        monkeypatch.setattr(contact, "MIN_SECONDS", 0)
        body = self.form("allgemein", message="Cheap viagra at http://a.example and more")
        assert self.post(body).status_code == 200
        assert mail.outbox == []
        held = HeldMessage.objects.get()
        assert "viagra" in held.reason
        c = api(board_a)
        url = f"/api/orgs/{setup['org'].pk}/website/held/"
        assert c.get(url).json()[0]["sender_email"] == "max@example.org"
        assert c.post(f"{url}{held.pk}/").status_code == 204
        assert mail.outbox[0].to == ["info@verein-a.example.org"]
        assert not HeldMessage.objects.exists()

    def test_obergrenze_je_stunde(self, setup, monkeypatch):
        monkeypatch.setattr(contact, "MIN_SECONDS", 0)
        setup["site"].contact_limit_per_hour = 1
        setup["site"].save()
        assert self.post(self.form("allgemein")).status_code == 200
        body = self.form("allgemein", message="Noch eine ganz andere Frage zum Fest.")
        assert self.post(body).status_code == 200
        assert len(mail.outbox) == 1
        assert "Obergrenze" in HeldMessage.objects.get().reason

    def test_alte_challenge_abgelehnt(self, setup):
        body = self.form("allgemein")
        with pytest.raises(contact.Rejected) as exc:
            contact.check_challenge(
                setup["site"], body["challenge"], body["nonce"], now=time.time() + 3 * 3600
            )
        # Die Webseite holt dann ohne Neuladen eine neue Aufgabe (UX-Audit 31.10. S03)
        assert exc.value.code == "expired"

    def test_zurueckgehaltene_nach_7_tagen_weg(self, setup):
        HeldMessage.objects.create(
            organization=setup["org"],
            website=setup["site"],
            recipient="allgemein",
            recipient_name="x",
            sender_name="x",
            sender_email="x@example.org",
            subject="x",
            body="x",
            reason="x",
        )
        assert contact.purge_held(timezone.now() + datetime.timedelta(days=8)) == 1


def test_cors_vorabfrage(setup):
    resp = Client().options(
        "/api/public/site/v1/schluessel-a/contact/", HTTP_ORIGIN="https://www.verein-a.example"
    )
    assert resp.status_code == 204
    assert resp["Access-Control-Allow-Origin"] == "*"
    assert "POST" in resp["Access-Control-Allow-Methods"]


def test_formularmails_nur_7_tage_im_postausgang(setup, settings):
    from outbox.models import OutgoingMail
    from outbox.purge import EMPTIED, purge_sent

    with rls_bypass():
        for kind in ("website-contact", "circular"):
            OutgoingMail.objects.create(
                organization=setup["org"],
                to="a@example.org",
                subject="x",
                body="geheim",
                kind=kind,
                status="sent",
            )
    purge_sent(timezone.now() + datetime.timedelta(days=8))
    with rls_bypass():
        bodies = dict(OutgoingMail.objects.values_list("kind", "body"))
    assert bodies == {"website-contact": EMPTIED, "circular": "geheim"}


class TestSpamPruefung:
    """Inhaltsprüfung ohne Formular: deutsche Spamwörter, Wortanfang, fremde Schrift."""

    def test_deutsche_spamwoerter(self):
        assert "sportwetten" in contact.suspicious("Angebot", "Beste Sportwetten hier!", "a@b.de")
        reason = contact.suspicious("Tipp", "Jetzt in Kryptowährung anlegen", "a@b.de")
        assert "kryptowährung" in reason

    def test_nur_ab_wortanfang(self):
        assert contact.suspicious("Frage", "No abetting here, just a question", "a@b.de") == ""
        assert contact.suspicious("Frage", "Wer erklärt uns Kryptografie?", "a@b.de") == ""
        assert contact.suspicious("Schützenfest", "Wann ist das Vogelschießen?", "a@b.de") == ""

    def test_fremde_schrift(self):
        reason = contact.suspicious("Привет", "Здравствуйте, предлагаем услуги", "a@b.de")
        assert "Schrift" in reason
        text = "Unser Gastverein aus Kiew heißt Дружба, wir möchten zum Schützenfest kommen."
        assert contact.suspicious("Besuch", text, "a@b.de") == ""
