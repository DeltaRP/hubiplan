"""Mailverteiler: Rundschreiben aus dem eigenen Mailprogramm (circulars/inbound.py)."""
# ruff: noqa: F811  (Fixtures aus test_m12_events als Parameter)

import datetime
from email.message import EmailMessage
from unittest import mock

import pytest
from django.test import Client

from circulars import inbound, services
from circulars.models import Circular, CircularRecipient, InboundMail, MailingList
from outbox.models import OutgoingMail

from .factories import give_role, make_member, make_user
from .test_m12_events import (  # noqa: F401  (Fixtures)
    JSON,
    cal,
    dept_role,
    member_with_access,
    private_root,
    zug,
    zug2,
)

pytestmark = pytest.mark.django_db

DOMAIN = "verein.example.org"
PDF = b"%PDF-1.4\n%test\n"


@pytest.fixture(autouse=True)
def verteiler_settings(settings, private_root):
    settings.INBOUND_DOMAINS = [DOMAIN]
    settings.INBOUND_SIMULATION = True
    settings.INBOUND_IMAP_HOST = ""
    settings.MAIL_RATE_PER_HOUR = 0
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.EMAIL_BACKEND = "outbox.backend.OutboxBackend"


def base(org) -> str:
    return f"/api/orgs/{org.pk}/circulars/"


@pytest.fixture
def members(cal, zug, zug2):
    club = cal["a"]
    return {
        "anna": make_member(club, "Anna", "Adler", departments=[zug]),
        "bernd": make_member(club, "Bernd", "Berg", departments=[zug2]),
    }


def create_list(client, url, **data) -> dict:
    resp = client.post(
        f"{url}lists/", {"name": "Alle", "local_part": "alle", **data}, content_type=JSON
    )
    assert resp.status_code == 201, resp.json()
    return resp.json()


def mail_bytes(
    sender: str,
    to: str = f"alle@{DOMAIN}",
    subject: str = "Einladung",
    body: str = "Hallo {Vorname},\n\nbis bald!",
    pdf: bytes | None = None,
    **headers,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = f"Vorstand <{sender}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{abs(hash((sender, to, subject, body)))}@example.org>"
    for name, value in headers.items():
        msg[name.replace("_", "-")] = value
    msg.set_content(body)
    if pdf is not None:
        msg.add_attachment(pdf, maintype="application", subtype="pdf", filename="Plan.pdf")
        msg.add_attachment(b"PK..", maintype="application", subtype="zip", filename="x.zip")
    return msg.as_bytes()


def confirmation(entry: InboundMail) -> OutgoingMail:
    return OutgoingMail.objects.filter(kind="verteiler", to__contains=entry.user.email).latest(
        "created_at"
    )


class TestVerwalten:
    def test_anlegen_adresse_und_muster(self, cal, board_a, api):
        c = api(board_a)
        data = create_list(c, base(cal["a"]), local_part="Alle")
        assert data["local_part"] == "alle"
        assert data["address"] == f"alle@{DOMAIN}"
        assert data["mode"] == "confirm"
        # Das Muster erscheint nicht in der Liste der Rundschreiben
        listed = c.get(base(cal["a"])).json()
        assert all(r["id"] != data["pattern_id"] for r in listed)
        # Muster lässt sich nicht versenden oder einzeln löschen
        resp = c.post(f"{base(cal['a'])}{data['pattern_id']}/send/", content_type=JSON)
        assert resp.status_code == 400
        resp = c.delete(f"{base(cal['a'])}{data['pattern_id']}/")
        assert resp.status_code == 400
        # Empfänger wie beim Rundschreiben einstellbar
        resp = c.patch(
            f"{base(cal['a'])}{data['pattern_id']}/",
            {"kind": "notice", "filters": {"age_min": 18}},
            content_type=JSON,
        )
        assert resp.status_code == 200
        assert c.get(f"{base(cal['a'])}lists/{data['id']}/").json()["kind"] == "notice"

    def test_adresse_eindeutig_und_gueltig(self, cal, board_a, board_b, api):
        create_list(api(board_a), base(cal["a"]))
        resp = api(board_b).post(
            f"{base(cal['b'])}lists/", {"name": "X", "local_part": "alle"}, content_type=JSON
        )
        assert resp.status_code == 400 and "vergeben" in str(resp.json())
        for bad in ("postmaster", "-x", "é", "a b"):
            resp = api(board_b).post(
                f"{base(cal['b'])}lists/", {"name": "X", "local_part": bad}, content_type=JSON
            )
            assert resp.status_code == 400, bad

    def test_weitere_adressen(self, cal, board_a, board_b, members, api):
        c = api(board_a)
        # Umlaute werden umgeschrieben
        data = create_list(c, base(cal["a"]), name="Schriftführer", local_part="Schriftführer")
        assert data["local_part"] == "schriftfuehrer"
        url = f"{base(cal['a'])}lists/{data['id']}/"
        resp = c.patch(
            url, {"aliases": ["SF", "schriftführer", "schriftfuehrerin", ""]}, content_type=JSON
        )
        assert resp.status_code == 200, resp.json()
        # Doppelte und die Hauptadresse fallen weg
        assert resp.json()["aliases"] == ["sf", "schriftfuehrerin"]
        assert resp.json()["alias_addresses"] == [f"sf@{DOMAIN}", f"schriftfuehrerin@{DOMAIN}"]
        # Vergeben auch über die weiteren Adressen, auch für andere Vereine
        resp = api(board_b).post(
            f"{base(cal['b'])}lists/", {"name": "X", "local_part": "sf"}, content_type=JSON
        )
        assert resp.status_code == 400 and "vergeben" in str(resp.json())
        other = create_list(api(board_b), base(cal["b"]), local_part="kasse")
        resp = api(board_b).patch(
            f"{base(cal['b'])}lists/{other['id']}/",
            {"aliases": ["schriftfuehrerin"]},
            content_type=JSON,
        )
        assert resp.status_code == 400 and "vergeben" in str(resp.json()["aliases"])
        resp = c.patch(url, {"aliases": ["postmaster"]}, content_type=JSON)
        assert resp.status_code == 400
        resp = c.patch(url, {"aliases": [f"a{i}" for i in range(6)]}, content_type=JSON)
        assert resp.status_code == 400
        # Mail an die weitere Adresse landet beim Verteiler
        entry = inbound.process_message(mail_bytes(board_a.email, to=f"SF@{DOMAIN}"))
        assert entry.status == InboundMail.Status.WAITING
        assert entry.mailing_list_id == data["id"]

    def test_uebersicht_zaehlt_empfaenger(self, cal, board_a, members, api):
        c = api(board_a)
        create_list(c, base(cal["a"]))
        items = c.get(f"{base(cal['a'])}lists/").json()["items"]
        assert items[0]["recipients"] == 2  # Anna und Bernd

    def test_rundschreiben_an_verteiler(
        self, cal, board_a, members, api, settings, django_capture_on_commit_callbacks
    ):
        c = api(board_a)
        url = base(cal["a"])
        ml = create_list(c, url)
        options = c.get(f"{url}options/").json()
        assert options["lists"] == [{"id": ml["id"], "name": "Alle", "audience": "members"}]
        # Auswahl im Verteiler: nur Anna (Bernd abgewählt)
        bernd = f"m{members['bernd'].pk}"
        c.patch(f"{url}{ml['pattern_id']}/", {"filters": {"exclude": [bernd]}}, content_type=JSON)
        draft = c.post(url, {"subject": "Hallo", "body": "Text"}, content_type=JSON).json()
        resp = c.patch(f"{url}{draft['id']}/", {"mailing_list": ml["id"]}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["mailing_list"] == ml["id"]
        assert resp.json()["filters"] == {"exclude": [bernd]}
        # Spätere Änderung am Verteiler gilt auch für den Entwurf
        c.patch(f"{url}{ml['pattern_id']}/", {"filters": {}}, content_type=JSON)
        items = c.get(f"{url}{draft['id']}/recipients/").json()["items"]
        assert {i["first_name"] for i in items if i["channel"]} == {"Anna", "Bernd"}
        # Verteiler anderer Einheiten gehen nicht
        other = MailingList.objects.create(
            organization=cal["b"],
            name="B",
            local_part="b",
            pattern=Circular.objects.create(organization=cal["b"]),
        )
        resp = c.patch(f"{url}{draft['id']}/", {"mailing_list": other.pk}, content_type=JSON)
        assert resp.status_code == 400
        # Das Muster selbst bekommt keinen Verteiler
        resp = c.patch(f"{url}{ml['pattern_id']}/", {"mailing_list": ml["id"]}, content_type=JSON)
        assert resp.status_code == 400

    def test_loeschen_mit_muster(self, cal, board_a, api):
        c = api(board_a)
        data = create_list(c, base(cal["a"]))
        assert c.delete(f"{base(cal['a'])}lists/{data['id']}/").status_code == 204
        assert not MailingList.objects.exists()
        assert not Circular.objects.filter(pk=data["pattern_id"]).exists()

    def test_fremder_verein_sieht_nichts(self, cal, board_a, board_b, api):
        data = create_list(api(board_a), base(cal["a"]))
        resp = api(board_b).get(f"{base(cal['b'])}lists/")
        assert resp.json()["items"] == []
        resp = api(board_b).get(f"{base(cal['b'])}lists/{data['id']}/")
        assert resp.status_code == 404


class TestEingang:
    def test_bestaetigen_und_versenden(
        self, cal, board_a, members, api, django_capture_on_commit_callbacks
    ):
        c = api(board_a)
        create_list(c, base(cal["a"]))
        entry = inbound.process_message(mail_bytes(board_a.email, pdf=PDF))
        assert entry.status == InboundMail.Status.WAITING
        circular = entry.circular
        assert circular.is_draft and circular.subject == "Einladung"
        assert circular.reply_to == board_a.email and circular.created_by == board_a
        assert [a.name for a in circular.attachments.all()] == ["Plan.pdf"]
        note = confirmation(entry)
        assert "/rundschreiben/bestaetigen/" in note.body
        assert "x.zip (nur PDF möglich)" in note.body
        # Noch nichts an die Mitglieder
        assert not CircularRecipient.objects.exists()
        # Öffnen allein versendet nicht
        token = inbound.confirm_token(entry)
        public = Client()
        url = f"/api/public/circulars/confirm/{token}/"
        data = public.get(url).json()
        assert data["status"] == "waiting" and data["counts"]["mail"] == 2
        assert data["attachments"] == ["Plan.pdf"]
        assert not CircularRecipient.objects.exists()
        with django_capture_on_commit_callbacks(execute=True):
            resp = public.post(url, {"action": "send"}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["status"] == "sent"
        circular.refresh_from_db()
        assert circular.status == Circular.Status.SENT and circular.sent_by == board_a
        sent = OutgoingMail.objects.filter(kind="rundschreiben")
        assert sent.count() == 2
        assert all(board_a.email in m.reply_to for m in sent)
        assert "Hallo Anna" in sent.get(to__contains="anna").body
        # Zweiter Klick tut nichts
        resp = public.post(url, {"action": "send"}, content_type=JSON)
        assert resp.status_code == 400
        assert OutgoingMail.objects.filter(kind="rundschreiben").count() == 2

    def test_verwerfen(self, cal, board_a, members, api):
        create_list(api(board_a), base(cal["a"]))
        entry = inbound.process_message(mail_bytes(board_a.email))
        url = f"/api/public/circulars/confirm/{inbound.confirm_token(entry)}/"
        resp = Client().post(url, {"action": "discard"}, content_type=JSON)
        assert resp.status_code == 200 and resp.json()["status"] == "rejected"
        assert not Circular.objects.filter(pk=entry.circular_id).exists()

    def test_ungueltiger_link(self, cal):
        resp = Client().get("/api/public/circulars/confirm/kaputt/")
        assert resp.status_code == 404

    def test_entwurf_modus(self, cal, board_a, members, api):
        create_list(api(board_a), base(cal["a"]), mode="draft")
        entry = inbound.process_message(mail_bytes(board_a.email))
        assert entry.status == InboundMail.Status.DRAFT
        assert entry.circular.is_draft
        assert "liegt als Entwurf" in confirmation(entry).body
        # erscheint als normaler Entwurf
        listed = api(board_a).get(base(cal["a"])).json()
        assert any(r["id"] == entry.circular_id for r in listed)

    def test_unbekannter_absender_ohne_antwort(self, cal, board_a, members, api):
        create_list(api(board_a), base(cal["a"]))
        entry = inbound.process_message(mail_bytes("fremd@example.net"))
        assert entry.status == InboundMail.Status.REJECTED
        assert entry.circular is None
        assert not OutgoingMail.objects.filter(kind="verteiler").exists()
        assert not Circular.objects.filter(list_pattern__isnull=True).exists()
        # Vorstand sieht den Eingang beim Verteiler
        ml = MailingList.objects.get()
        rows = api(board_a).get(f"{base(cal['a'])}lists/{ml.pk}/inbound/").json()
        assert rows[0]["sender"] == "fremd@example.net" and rows[0]["status"] == "rejected"

    def test_vorstand_eines_anderen_vereins_darf_nicht(self, cal, board_a, board_b, members, api):
        create_list(api(board_a), base(cal["a"]))
        entry = inbound.process_message(mail_bytes(board_b.email))
        assert entry.status == InboundMail.Status.REJECTED

    def test_abteilungsrolle_darf_an_eigenen_zug(self, cal, board_a, members, zug, api):
        c = api(board_a)
        url = base(cal["a"])
        data = create_list(c, url, local_part="jaeger")
        ml = MailingList.objects.get(pk=data["id"])
        # Verteiler des Zugs (über den Zugang des Zugs angelegt)
        m, user, _ = member_with_access(cal["a"], "Zora", [zug])
        dept_role(zug, m, ["dept.circulars.send"])
        resp = api(user).post(
            f"/api/depts/{zug.pk}/circulars/lists/",
            {"name": "Jägerzug", "local_part": "jaegerzug"},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        detail = api(user).get(f"/api/depts/{zug.pk}/circulars/lists/{resp.json()['id']}/").json()
        assert user.email in {o["email"] for o in detail["sender_options"]}
        entry = inbound.process_message(mail_bytes(user.email, to=f"jaegerzug@{DOMAIN}"))
        assert entry.status == InboundMail.Status.WAITING, entry.reason
        assert entry.circular.department_id == zug.pk
        # An den Vereinsverteiler darf die Zugrolle nicht
        entry = inbound.process_message(
            mail_bytes(user.email, to=f"{ml.local_part}@{DOMAIN}", subject="Anders")
        )
        assert entry.status == InboundMail.Status.REJECTED

    def test_rueckläufer_und_eigene_mails_verworfen(self, cal, board_a, members, api):
        create_list(api(board_a), base(cal["a"]))
        cases = [
            {"Auto_Submitted": "auto-replied"},
            {"Precedence": "bulk"},
            {"X_Hubiplan_Org": "1"},
        ]
        for i, headers in enumerate(cases):
            entry = inbound.process_message(
                mail_bytes(board_a.email, subject=f"Abwesend {i}", **headers)
            )
            assert entry.status == InboundMail.Status.REJECTED, headers
            assert entry.reason.startswith("Verworfen")
        assert not OutgoingMail.objects.filter(kind="verteiler").exists()

    def test_dmarc_fehlgeschlagen(self, cal, board_a, members, api):
        create_list(api(board_a), base(cal["a"]))
        entry = inbound.process_message(
            mail_bytes(
                board_a.email,
                Authentication_Results="mx.example.org; dkim=none; spf=fail; dmarc=fail",
            )
        )
        assert entry.status == InboundMail.Status.REJECTED and "DMARC" in entry.reason

    def test_offener_verteiler_direkt_an_alle(
        self, cal, board_a, members, api, django_capture_on_commit_callbacks
    ):
        c = api(board_a)
        ml = create_list(c, base(cal["a"]))
        resp = c.patch(
            f"{base(cal['a'])}lists/{ml['id']}/", {"open_senders": True}, content_type=JSON
        )
        assert resp.json()["open_senders"] is True
        with django_capture_on_commit_callbacks(execute=True):
            entry = inbound.process_message(mail_bytes("fremd@example.net"))
        assert entry.status == InboundMail.Status.SENT and entry.user is None
        circular = entry.circular
        circular.refresh_from_db()
        assert circular.reply_to == "fremd@example.net" and not circular.is_draft
        assert CircularRecipient.objects.filter(circular=circular).count() == 2
        # keine Bestätigungsmail an den fremden Absender
        assert not OutgoingMail.objects.filter(kind="verteiler", to__contains="fremd@").exists()
        # Spam wird verworfen
        spam = inbound.process_message(
            mail_bytes("fremd@example.net", subject="Kaufen", X_Spam_Flag="YES")
        )
        assert spam.status == InboundMail.Status.REJECTED
        # Höchstens drei am Tag je fremdem Absender
        for i in range(2):
            with django_capture_on_commit_callbacks(execute=True):
                ok = inbound.process_message(mail_bytes("fremd@example.net", subject=f"N{i}"))
            assert ok.status == InboundMail.Status.SENT
        too_many = inbound.process_message(mail_bytes("fremd@example.net", subject="N9"))
        assert too_many.status == InboundMail.Status.REJECTED
        assert "Mehr als 3" in too_many.reason

    def test_direkt_ohne_bestaetigung(
        self, cal, board_a, members, api, django_capture_on_commit_callbacks
    ):
        create_list(api(board_a), base(cal["a"]), mode="direct")
        with django_capture_on_commit_callbacks(execute=True):
            entry = inbound.process_message(
                mail_bytes(
                    board_a.email,
                    Authentication_Results="mx.example.org; spf=pass; dkim=pass; dmarc=pass",
                )
            )
        assert entry.status == InboundMail.Status.SENT and entry.user == board_a
        circular = entry.circular
        circular.refresh_from_db()
        assert not circular.is_draft and circular.sent_by == board_a
        assert CircularRecipient.objects.filter(circular=circular).count() == 2
        note = confirmation(entry)
        assert note.subject.startswith("Versendet:") and "bestaetigen" not in note.body
        # Wer nicht darf, wird auch hier abgewiesen
        other = inbound.process_message(mail_bytes("fremd@example.net", subject="X"))
        assert other.status == InboundMail.Status.REJECTED

    def test_doppelt_und_unbekannte_adresse(self, cal, board_a, members, api):
        create_list(api(board_a), base(cal["a"]))
        raw = mail_bytes(board_a.email)
        assert inbound.process_message(raw) is not None
        assert inbound.process_message(raw) is None
        entry = inbound.process_message(mail_bytes(board_a.email, to=f"gibtsnicht@{DOMAIN}"))
        assert entry.status == InboundMail.Status.REJECTED and entry.organization is None
        # Plus-Adresse zählt als Verteiler
        entry = inbound.process_message(
            mail_bytes(board_a.email, to=f"alle+x@{DOMAIN}", subject="Plus")
        )
        assert entry.status == InboundMail.Status.WAITING

    def test_ohne_betreff_antwort_mit_grund(self, cal, board_a, members, api):
        create_list(api(board_a), base(cal["a"]))
        entry = inbound.process_message(mail_bytes(board_a.email, subject=""))
        assert entry.status == InboundMail.Status.REJECTED
        assert "keinen Betreff" in confirmation(entry).body

    def test_html_mail_und_klammern(self, cal, board_a, members, api):
        create_list(api(board_a), base(cal["a"]))
        msg = EmailMessage()
        msg["From"] = board_a.email
        msg["To"] = f"alle@{DOMAIN}"
        msg["Subject"] = "HTML"
        msg.set_content(
            "<html><head><style>p{color:red}</style></head><body><p>Hallo <b>{Vorname}</b>"
            '</p><ul><li>eins</li></ul><p><a href="https://example.org">Seite</a> {x}</p>'
            "</body></html>",
            subtype="html",
        )
        entry = inbound.process_message(msg.as_bytes())
        body = entry.circular.body
        assert "Hallo **{Vorname}**" in body
        assert "- eins" in body
        assert "[Seite](https://example.org)" in body
        assert "(x)" in body and "color" not in body

    def test_ohne_empfaenger(self, cal, board_a, api):
        create_list(api(board_a), base(cal["a"]))
        entry = inbound.process_message(mail_bytes(board_a.email))
        assert entry.status == InboundMail.Status.REJECTED
        assert "keine Empfänger" in entry.reason
        assert not Circular.objects.filter(list_pattern__isnull=True).exists()

    def test_recht_entzogen_vor_bestaetigung(self, cal, members, api):
        user = make_user("kurz@example.org")
        assignment = give_role(user, cal["a"])
        board = make_user("dauer@example.org")
        give_role(board, cal["a"])
        create_list(api(board), base(cal["a"]))
        entry = inbound.process_message(mail_bytes(user.email))
        assert entry.status == InboundMail.Status.WAITING
        assignment.valid_until = datetime.date(2000, 1, 1)
        assignment.save()
        url = f"/api/public/circulars/confirm/{inbound.confirm_token(entry)}/"
        resp = Client().post(url, {"action": "send"}, content_type=JSON)
        assert resp.status_code == 400


class TestProbe:
    def test_probe_eingang(self, cal, board_a, members, api):
        c = api(board_a)
        data = create_list(c, base(cal["a"]))
        resp = c.post(
            f"{base(cal['a'])}lists/{data['id']}/probe/",
            {"subject": "Probe", "body": "Hallo"},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        assert resp.json()["status"] == "waiting"
        assert "/rundschreiben/bestaetigen/" in resp.json()["confirm_url"]

    def test_probe_nur_ohne_postfach(self, cal, board_a, api, settings):
        c = api(board_a)
        data = create_list(c, base(cal["a"]))
        settings.INBOUND_SIMULATION = False
        resp = c.post(
            f"{base(cal['a'])}lists/{data['id']}/probe/",
            {"subject": "Probe", "body": "Hallo"},
            content_type=JSON,
        )
        assert resp.status_code == 403


class TestAbholen:
    def test_imap(self, cal, board_a, members, api, settings):
        create_list(api(board_a), base(cal["a"]))
        settings.INBOUND_IMAP_HOST = "imap.example.org"
        raw = mail_bytes(board_a.email)
        imap = mock.MagicMock()
        imap.__enter__.return_value = imap
        imap.uid.side_effect = lambda cmd, *args: {
            "search": ("OK", [b"7"]),
            "fetch": ("OK", [(b"7 (BODY[] {1}", raw), b")"]),
            "store": ("OK", [b""]),
        }[cmd]
        with mock.patch("circulars.inbound.imaplib.IMAP4_SSL", return_value=imap):
            assert inbound.fetch_inbound() == 1
        assert InboundMail.objects.get().status == InboundMail.Status.WAITING
        imap.uid.assert_any_call("store", b"7", "+FLAGS", "(\\Deleted)")
        imap.expunge.assert_called_once()

    def test_ohne_postfach_nichts(self, settings):
        settings.INBOUND_IMAP_HOST = ""
        assert inbound.fetch_inbound() == 0


class TestDrosselung:
    def test_stundengrenze(self, cal, board_a, members, api, settings):
        settings.MAIL_RATE_PER_HOUR = 10  # 9 für Rundschreiben
        for i in range(8):
            OutgoingMail.objects.create(to="x@example.org", subject=f"alt {i}", body="")
        assert services.mail_budget() == 1
        create_list(api(board_a), base(cal["a"]))
        entry = inbound.process_message(mail_bytes(board_a.email))
        # Bestätigungsmail zählt mit: danach ist die Grenze erreicht
        assert services.mail_budget() == 0
        inbound.confirm(entry)
        circular = Circular.objects.get(pk=entry.circular_id)
        assert circular.status == Circular.Status.SENDING
        assert circular.recipients.filter(status=CircularRecipient.Status.PENDING).count() == 2
        settings.MAIL_RATE_PER_HOUR = 0
        assert services.send_pending(circular.pk) == 2
        circular.refresh_from_db()
        assert circular.status == Circular.Status.SENT


class TestAbsenderAuswahl:
    def test_nur_ausgewaehlte_duerfen(self, cal, board_a, members, api):
        zweiter = make_user("schrift@example.org")
        give_role(zweiter, cal["a"])
        fremd = make_user("ohne-recht@example.org")
        c = api(board_a)
        data = create_list(c, base(cal["a"]))
        url = f"{base(cal['a'])}lists/{data['id']}/"
        detail = c.get(url).json()
        assert {o["email"] for o in detail["sender_options"]} == {
            board_a.email,
            zweiter.email,
        }
        # Konto ohne Recht ist nicht wählbar
        resp = c.patch(url, {"senders": [fremd.pk]}, content_type=JSON)
        assert resp.status_code == 400
        resp = c.patch(url, {"senders": [zweiter.pk]}, content_type=JSON)
        assert resp.status_code == 200 and resp.json()["senders"] == [zweiter.pk]
        entry = inbound.process_message(mail_bytes(board_a.email))
        assert entry.status == InboundMail.Status.REJECTED
        entry = inbound.process_message(mail_bytes(zweiter.email, subject="Von Schrift"))
        assert entry.status == InboundMail.Status.WAITING
        # Leere Auswahl: wieder alle mit dem Recht
        c.patch(url, {"senders": []}, content_type=JSON)
        entry = inbound.process_message(mail_bytes(board_a.email, subject="Wieder alle"))
        assert entry.status == InboundMail.Status.WAITING


# --- GA-S03: „direkt senden“ nur mit bestätigter Herkunft ---


@pytest.mark.parametrize(
    "ergebnis",
    [
        None,
        "mx.example.org; dmarc=none",
        "mx.example.org; dmarc=temperror",
        "mx.example.org; dmarc=permerror",
        "mx.example.org; spf=softfail; dmarc=bestpass",
    ],
)
def test_direkt_ohne_dmarc_pass_braucht_bestaetigung(cal, board_a, members, api, ergebnis):
    create_list(api(board_a), base(cal["a"]), mode="direct")
    headers = {"Authentication_Results": ergebnis} if ergebnis else {}
    entry = inbound.process_message(mail_bytes(board_a.email, **headers))
    assert entry.status == InboundMail.Status.WAITING
