"""Rundschreiben: Empfängerauswahl, Versand per Mail und Brief, Abmeldung, Rechte."""
# ruff: noqa: F811  (Fixtures aus test_m12_events als Parameter)

import datetime

import pytest
from django.core import mail as djmail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from audit.models import AuditEntry
from circulars import services, text
from circulars.models import Circular, CircularRecipient
from members.models import ContactDetails, Membership, MemberType
from outbox.models import OutgoingMail

from .factories import give_role, make_member, make_user
from .test_m12_events import (  # noqa: F401  (Fixtures)
    JSON,
    board_fed,
    cal,
    dept_role,
    member_with_access,
    private_root,
    zug,
    zug2,
)

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n%test\n"


def base(org) -> str:
    return f"/api/orgs/{org.pk}/circulars/"


def dept_base(dept) -> str:
    return f"/api/depts/{dept.pk}/circulars/"


def draft(client, url, **data) -> dict:
    payload = {"subject": "Einladung", "body": "Hallo {Vorname},\n\nbis bald!", **data}
    resp = client.post(url, payload, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    return resp.json()


def preview(client, url, pk) -> dict:
    resp = client.get(f"{url}{pk}/recipients/")
    assert resp.status_code == 200, resp.json()
    return resp.json()


def send(client, url, pk, capture, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    with capture(execute=True):
        resp = client.post(f"{url}{pk}/send/", content_type=JSON)
    assert resp.status_code == 200, resp.json()
    return resp.json()


def without_email(membership):
    ContactDetails.objects.filter(person=membership.person).update(email="")


@pytest.fixture
def members(cal, zug, zug2):
    club = cal["a"]
    return {
        "anna": make_member(club, "Anna", "Adler", departments=[zug]),
        "bernd": make_member(club, "Bernd", "Berg", departments=[zug2]),
        "clara": make_member(
            club,
            "Clara",
            "Christ",
            departments=[zug],
            birth_date=datetime.date(2012, 3, 1),
        ),
    }


class TestText:
    def test_auszeichnung_und_maskierung(self):
        html = text.to_html("**Wichtig**: <b>x</b> *bitte*\n- eins\n- [Link](https://example.org)")
        assert "<b>Wichtig</b>" in html
        assert "&lt;b&gt;x&lt;/b&gt;" in html
        assert "<i>bitte</i>" in html
        assert '<ul><li>eins</li><li><a href="https://example.org">Link</a></li></ul>' in html
        plain = text.to_plain("**Wichtig** [Link](https://example.org)")
        assert plain == "Wichtig Link (https://example.org)"

    def test_kein_javascript_link(self):
        assert "<a" not in text.to_html("[x](javascript:alert(1))")

    def test_platzhalter(self):
        assert text.fill("Hallo {Vorname} {Unbekannt}", {"Vorname": "Anna"}) == (
            "Hallo Anna {Unbekannt}"
        )
        assert text.unknown_placeholders("{Vorname} {Titel}") == ["Titel"]


class TestEmpfaenger:
    def test_filter_abteilung_alter_und_einzeln(self, cal, board_a, members, zug, api):
        c = api(board_a)
        url = base(cal["a"])
        data = draft(c, url, filters={"departments": [zug.pk]})
        names = {i["first_name"] for i in preview(c, url, data["id"])["items"]}
        assert names == {"Anna", "Clara"}
        c.patch(
            f"{url}{data['id']}/",
            {"filters": {"departments": [zug.pk], "age_min": 18}},
            content_type=JSON,
        )
        names = {i["first_name"] for i in preview(c, url, data["id"])["items"]}
        assert names == {"Anna"}
        # Bernd einzeln dazu, Anna abwählen
        found = c.get(f"{url}{data['id']}/search/?suche=Berg").json()
        assert [f["first_name"] for f in found] == ["Bernd"]
        c.patch(
            f"{url}{data['id']}/",
            {
                "filters": {
                    "departments": [zug.pk],
                    "age_min": 18,
                    "include": [found[0]["key"]],
                    "exclude": [f"m{members['anna'].pk}"],
                }
            },
            content_type=JSON,
        )
        result = preview(c, url, data["id"])
        rows = {i["first_name"]: i for i in result["items"]}
        assert rows["Bernd"]["included"] and rows["Bernd"]["channel"] == "mail"
        assert rows["Anna"]["excluded"] and rows["Anna"]["channel"] is None
        assert result["counts"]["mail"] == 1 and result["counts"]["excluded"] == 1

    def test_mitgliedsart_und_jubilare(self, cal, board_a, members, api):
        club = cal["a"]
        passiv = MemberType.objects.create(organization=club, name="passiv")
        make_member(club, "Dora", "Dach", member_type=passiv, entry_date=datetime.date(2001, 5, 1))
        club.jubilee_years = [25]
        club.save()
        c = api(board_a)
        url = base(club)
        data = draft(c, url, filters={"member_types": [passiv.pk]})
        assert [i["first_name"] for i in preview(c, url, data["id"])["items"]] == ["Dora"]
        data = draft(c, url, filters={"jubilee_year": 2026}, body="{Jubiläumsjahre} Jahre")
        assert [i["first_name"] for i in preview(c, url, data["id"])["items"]] == ["Dora"]

    def test_ohne_email_brief_und_abmeldung(self, cal, board_a, members, api):
        without_email(members["bernd"])
        Membership.objects.filter(pk=members["clara"].pk).update(
            info_opt_out_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        )
        c = api(board_a)
        url = base(cal["a"])
        info = draft(c, url)
        rows = {i["first_name"]: i for i in preview(c, url, info["id"])["items"]}
        assert rows["Anna"]["channel"] == "mail"
        assert rows["Bernd"]["channel"] == "letter"
        assert rows["Clara"]["channel"] is None and rows["Clara"]["opted_out"]
        notice = draft(c, url, kind="notice")
        rows = {i["first_name"]: i for i in preview(c, url, notice["id"])["items"]}
        assert rows["Clara"]["channel"] == "mail"  # Vereinsmitteilung geht immer raus


class TestVersand:
    def test_versand_mail_brief_und_protokoll(
        self, cal, board_a, members, api, settings, django_capture_on_commit_callbacks
    ):
        without_email(members["bernd"])
        c = api(board_a)
        url = base(cal["a"])
        data = draft(c, url, body="Hallo **{Vorname}**,\n\n- Punkt eins")
        resp = c.post(
            f"{url}{data['id']}/attachments/",
            {"file": SimpleUploadedFile("Programm.pdf", PDF, "application/pdf")},
        )
        assert resp.status_code == 201, resp.json()
        bad = c.post(
            f"{url}{data['id']}/attachments/",
            {"file": SimpleUploadedFile("x.pdf", b"kein pdf", "application/pdf")},
        )
        assert bad.status_code == 400
        result = send(c, url, data["id"], django_capture_on_commit_callbacks, settings)
        assert result["sent"] == {"app": 0, "mail": 2, "letter": 1, "portal": 0}
        assert Circular.objects.get(pk=data["id"]).status == "sent"
        mails = [m for m in djmail.outbox if m.extra_headers.get("List-Unsubscribe")]
        assert sorted(m.to[0] for m in mails) == ["anna@example.org", "clara@example.org"]
        anna = next(m for m in mails if m.to == ["anna@example.org"])
        assert "Hallo Anna," in anna.body and "Abmelden:" in anna.body
        assert "<b>Anna</b>" in anna.alternatives[0][0]
        assert anna.attachments[0][0] == "Programm.pdf"
        assert anna.reply_to == [board_a.email]
        # Anzeigename „Person (Verein)“ vor der festen Adresse, nur eine Fußzeile
        name = board_a.get_full_name() or board_a.email
        assert anna.from_email.startswith(f'"{name} ({cal["a"].name})" <')
        assert "an Sie geschickt" not in anna.body
        assert anna.body.count("über HUBIplan versandt") == 1
        assert CircularRecipient.objects.filter(status="sent").count() == 2
        protocol = preview(c, url, data["id"])
        assert protocol["counts"]["letter"] == 1
        # Briefe als PDF, nur für Bernd
        pdf = c.get(f"{url}{data['id']}/letters/")
        assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF")
        # Versendet: nicht mehr änderbar, nicht löschbar, nicht erneut senden
        assert (
            c.patch(f"{url}{data['id']}/", {"subject": "x"}, content_type=JSON).status_code == 400
        )
        assert c.delete(f"{url}{data['id']}/").status_code == 400
        assert c.post(f"{url}{data['id']}/send/").status_code == 400
        assert AuditEntry.objects.filter(object_type="Rundschreiben", action="update").exists()

    def test_pruefung_vor_dem_versand(self, cal, board_a, members, api):
        c = api(board_a)
        url = base(cal["a"])
        data = draft(c, url, subject="", body="Hallo {Titel}")
        resp = c.post(f"{url}{data['id']}/send/")
        assert resp.status_code == 400
        assert "subject" in resp.json() and "Titel" in str(resp.json()["body"])
        data = draft(c, url, filters={"age_min": 99})
        resp = c.post(f"{url}{data['id']}/send/")
        assert resp.status_code == 400 and "keine Empfänger" in str(resp.json())

    def test_probemail_und_vorschau(self, cal, board_a, members, api):
        c = api(board_a)
        url = base(cal["a"])
        data = draft(c, url)
        resp = c.post(f"{url}{data['id']}/test/")
        assert resp.status_code == 200 and resp.json()["sent_to"] == board_a.email
        mail = djmail.outbox[-1]
        assert mail.to == [board_a.email]
        assert mail.subject == "[Probe] Einladung" and "Hallo Anna" in mail.body
        assert c.get(f"{url}{data['id']}/letters/?vorschau=1").content.startswith(b"%PDF")
        assert Circular.objects.get(pk=data["id"]).is_draft

    def test_vorlagen_und_kopie(self, cal, board_a, members, api):
        c = api(board_a)
        url = base(cal["a"])
        tpl = c.post(
            f"{url}templates/",
            {"name": "Versammlung", "kind": "notice", "subject": "JHV", "body": "Einladung"},
            content_type=JSON,
        ).json()
        data = draft(c, url, template=tpl["id"], subject="JHV 2026")
        assert data["kind"] == "notice" and data["subject"] == "JHV 2026"
        copy = c.post(url, {"copy_of": data["id"]}, content_type=JSON).json()
        assert copy["subject"] == "JHV 2026" and copy["id"] != data["id"]
        assert [t["name"] for t in c.get(f"{url}templates/").json()] == ["Versammlung"]


class TestAbmeldung:
    def test_abmeldelink(self, cal, members):
        m = members["anna"]
        token = services.opt_out_token(m.pk)
        anon = Client()
        resp = anon.get(f"/api/public/circulars/optout/{token}/")
        data = resp.json()
        assert data.pop("imprint_key")
        assert data == {"club": "Verein A", "first_name": "Anna", "info_opt_out": False}
        resp = anon.post(f"/api/public/circulars/optout/{token}/", {}, content_type=JSON)
        assert resp.json()["info_opt_out"] is True
        m.refresh_from_db()
        assert m.info_opt_out_at is not None
        resp = anon.post(
            f"/api/public/circulars/optout/{token}/", {"info_opt_out": False}, content_type=JSON
        )
        assert resp.json()["info_opt_out"] is False
        assert anon.get("/api/public/circulars/optout/falsch/").status_code == 404

    def test_vorstand_stellt_in_der_akte_um(self, cal, board_a, members, api):
        m = members["anna"]
        resp = api(board_a).patch(
            f"/api/orgs/{cal['a'].pk}/members/{m.pk}/", {"info_opt_out": True}, content_type=JSON
        )
        assert resp.status_code == 200 and resp.json()["info_opt_out_at"]


class TestMitgliederbereich:
    def test_empfangene_lesen_und_abmelden(
        self, cal, board_a, zug, api, settings, django_capture_on_commit_callbacks
    ):
        m, user, access = member_with_access(cal["a"], "Erika", depts=[zug])
        other, other_user, other_access = member_with_access(cal["a"], "Fritz")
        c = api(board_a)
        url = base(cal["a"])
        data = draft(c, url, filters={"departments": [zug.pk]})
        c.post(
            f"{url}{data['id']}/attachments/",
            {"file": SimpleUploadedFile("Plan.pdf", PDF, "application/pdf")},
        )
        send(c, url, data["id"], django_capture_on_commit_callbacks, settings)
        mine = api(user).get(f"/api/portal/{access.pk}/circulars/").json()
        assert [i["subject"] for i in mine] == ["Einladung"]
        detail = api(user).get(f"/api/portal/{access.pk}/circulars/{data['id']}/").json()
        assert "Hallo Erika," in detail["body"]
        att = detail["attachments"][0]["url"]
        assert api(user).get(att).status_code == 200
        # Fritz war nicht dabei
        assert api(other_user).get(f"/api/portal/{other_access.pk}/circulars/").json() == []
        resp = api(other_user).get(f"/api/portal/{other_access.pk}/circulars/{data['id']}/")
        assert resp.status_code == 404
        # Abmelden im Mitgliederbereich
        settings_url = f"/api/portal/{access.pk}/circulars/settings/"
        resp = api(user).put(settings_url, {"info_opt_out": True}, content_type=JSON)
        assert resp.json()["info_opt_out"] is True


class TestRechte:
    def test_abteilung_nur_eigene_mitglieder(self, cal, members, zug, zug2, api):
        leader = members["anna"]
        user = make_user("oberleutnant@example.org")
        from portal.models import PortalAccess

        PortalAccess.objects.create(organization=cal["a"], membership=leader, user=user)
        dept_role(zug, leader, ["dept.circulars.send"])
        c = api(user)
        url = dept_base(zug)
        data = draft(c, url, filters={"departments": [zug2.pk]})
        names = {i["first_name"] for i in preview(c, url, data["id"])["items"]}
        assert names == {"Anna", "Clara"}
        assert data["department"]["id"] == zug.pk
        # Bernd (anderer Zug) lässt sich nicht einzeln hinzufügen
        assert c.get(f"{url}{data['id']}/search/?suche=Berg").json() == []
        c.patch(
            f"{url}{data['id']}/",
            {"filters": {"include": [f"m{members['bernd'].pk}"]}},
            content_type=JSON,
        )
        names = {i["first_name"] for i in preview(c, url, data["id"])["items"]}
        assert "Bernd" not in names
        # Ohne Recht: kein Zugriff
        assert api(user).get(dept_base(zug2)).status_code == 404

    def test_ohne_recht_und_fremder_verein(self, cal, board_a, board_b, members, api):
        reader = make_user("leser@example.org")
        give_role(reader, cal["a"], permissions=["members.view"], name="Leser")
        assert api(reader).get(base(cal["a"])).status_code == 403
        data = draft(api(board_a), base(cal["a"]))
        assert api(board_b).get(f"{base(cal['b'])}{data['id']}/").status_code == 404
        assert api(board_b).get(f"{base(cal['a'])}{data['id']}/").status_code == 404


class TestDachverband:
    def test_an_vereinsvorstaende(
        self,
        cal,
        board_fed,
        board_a,
        api,
        settings,
        django_capture_on_commit_callbacks,
    ):
        cal["b"].contact_email = "info@verein-b.example.org"
        cal["b"].save()
        c = api(board_fed)
        url = base(cal["federation"])
        data = draft(c, url, body="Hallo {Vorname} vom {Verein}")
        assert data["audience"] == "boards"
        rows = preview(c, url, data["id"])["items"]
        assert {(r["club"], r["email"]) for r in rows} == {
            ("Verein A", "vorstand-a@example.org"),
            ("Verein B", "info@verein-b.example.org"),
        }
        send(c, url, data["id"], django_capture_on_commit_callbacks, settings)
        mail = next(m for m in djmail.outbox if m.to == ["vorstand-a@example.org"])
        assert "vom Verein A" in mail.body and "Abmelden" not in mail.body

    def test_an_mitglieder_nur_mit_zugriff(self, cal, board_fed, members, api):
        c = api(board_fed)
        url = base(cal["federation"])
        resp = c.post(url, {"subject": "x", "audience": "members"}, content_type=JSON)
        assert resp.status_code == 400
        fed = cal["federation"]
        fed.federation_member_access = "read"
        fed.save()
        data = draft(c, url, audience="members", filters={"clubs": [cal["a"].pk]})
        names = {i["first_name"] for i in preview(c, url, data["id"])["items"]}
        assert names == {"Anna", "Bernd", "Clara"}


class TestPostausgang:
    def test_anhaenge_nicht_kopiert(self, cal, settings, members):
        """Der Postausgang verweist auf die gespeicherten Anhänge, statt sie zu kopieren."""
        from outbox import mail

        settings.EMAIL_BACKEND = "outbox.backend.OutboxBackend"
        folder = settings.PRIVATE_ROOT / "circulars"
        folder.mkdir(parents=True)
        (folder / "a.pdf").write_bytes(PDF)
        stored = [
            {
                "name": "a.pdf",
                "path": "circulars/a.pdf",
                "size": len(PDF),
                "content_type": "application/pdf",
                "abs": str(folder / "a.pdf"),
            }
        ]
        assert mail.send(
            "x@example.org", "Betreff", "Text", html="<p>Text</p>", stored_attachments=stored
        )
        sent = OutgoingMail.objects.get(to="x@example.org")
        assert sent.attachments == [{k: v for k, v in stored[0].items() if k != "abs"}]


class TestAnAbteilungen:
    def test_an_rolleninhaber_und_kein_abmeldelink(
        self, cal, board_a, members, zug, zug2, api, settings, django_capture_on_commit_callbacks
    ):
        dept_role(zug, members["anna"], ["dept.members.view"])  # „Rolle 1“ im Jägerzug
        dept_role(zug2, members["bernd"], [])  # „Rolle 0“ bei den Grenadieren
        Membership.objects.filter(pk=members["anna"].pk).update(
            info_opt_out_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        )
        c = api(board_a)
        url = base(cal["a"])
        options = c.get(f"{url}options/").json()
        assert [a["value"] for a in options["audiences"]] == ["members", "departments", "roles"]
        assert options["role_names"] == ["Rolle 0", "Rolle 1"]
        data = draft(c, url, audience="departments")
        assert data["audience"] == "departments"
        rows = {i["first_name"]: i for i in preview(c, url, data["id"])["items"]}
        assert set(rows) == {"Anna", "Bernd"}  # ohne Rollen des Vereins
        assert rows["Anna"]["channel"] == "mail"  # Abmeldung gilt nicht für Rolleninhaber
        assert rows["Anna"]["departments"] == ["Rolle 1 (Jägerzug)"]
        c.patch(f"{url}{data['id']}/", {"filters": {"role_names": ["Rolle 0"]}}, content_type=JSON)
        assert [i["first_name"] for i in preview(c, url, data["id"])["items"]] == ["Bernd"]
        send(c, url, data["id"], django_capture_on_commit_callbacks, settings)
        mail = next(m for m in djmail.outbox if m.to == ["bernd@example.org"])
        assert "Abmelden" not in mail.body

    def test_rolleninhaber_des_vereins(self, cal, board_a, members, zug, api):
        club = cal["a"]
        kasse = make_user("kasse@example.org", first_name="Clara", last_name="Christ")
        assignment = give_role(kasse, club, name="Kassierer")
        # Konto mit Mitgliedsakte ohne eigene Mail: Mail an die Adresse des Kontos
        assignment.person = members["clara"].person
        assignment.save()
        without_email(members["clara"])
        schrift = make_user("schrift@example.org", first_name="Sven", last_name="Schrift")
        give_role(schrift, club, name="Schriftführer")
        # Kassierer im Zug gehört nicht dazu (keine Vermischung der Ebenen)
        zug_kasse = dept_role(zug, members["anna"], [])
        zug_kasse.name = "Kassierer"
        zug_kasse.save()
        c = api(board_a)
        url = base(club)
        options = c.get(f"{url}options/").json()
        names = {r["name"]: r["id"] for r in options["club_roles"]}
        assert set(names) == {"Vorstand", "Kassierer", "Schriftführer"}
        data = draft(
            c,
            url,
            audience="roles",
            filters={"club_roles": [names["Kassierer"]], "selected": ["club_roles"]},
        )
        assert data["audience"] == "roles"
        items = preview(c, url, data["id"])["items"]
        assert [(i["first_name"], i["channel"]) for i in items] == [("Clara", "mail")]
        assert items[0]["departments"] == ["Kassierer"]
        # Alle Rollen des Vereins: Konten ohne Akte per Mail an das Konto
        c.patch(f"{url}{data['id']}/", {"filters": {}}, content_type=JSON)
        rows = {i["last_name"]: i for i in preview(c, url, data["id"])["items"]}
        assert set(rows) == {"Christ", "Schrift", "vorstand-a@example.org"}
        assert rows["Schrift"]["departments"] == ["Schriftführer"]
        # „nur ausgewählte“ ohne Auswahl: niemand
        c.patch(
            f"{url}{data['id']}/",
            {"filters": {"club_roles": [], "selected": ["club_roles"]}},
            content_type=JSON,
        )
        assert preview(c, url, data["id"])["items"] == []

    def test_abteilung_darf_nicht_an_abteilungen(self, cal, members, zug, api):
        user = make_user("leitung@example.org")
        from portal.models import PortalAccess

        PortalAccess.objects.create(organization=cal["a"], membership=members["anna"], user=user)
        dept_role(zug, members["anna"], ["dept.circulars.send"])
        data = draft(api(user), dept_base(zug), audience="departments")
        assert data["audience"] == "members"
        assert draft(api(user), dept_base(zug), audience="roles")["audience"] == "members"
        assert "audiences" not in api(user).get(f"{dept_base(zug)}options/").json()


class TestEmpfangen:
    def test_verein_sieht_rundschreiben_des_dachverbands(
        self, cal, board_fed, board_a, board_b, api, settings, django_capture_on_commit_callbacks
    ):
        c = api(board_fed)
        url = base(cal["federation"])
        data = draft(c, url, body="Hallo {Vorname}")
        c.post(
            f"{url}{data['id']}/attachments/",
            {"file": SimpleUploadedFile("Rundbrief.pdf", PDF, "application/pdf")},
        )
        send(c, url, data["id"], django_capture_on_commit_callbacks, settings)
        received = api(board_a).get(f"{base(cal['a'])}received/").json()
        assert [r["subject"] for r in received] == ["Einladung"]
        assert received[0]["sender"] == "Testbund"
        detail = api(board_a).get(f"{base(cal['a'])}received/{data['id']}/").json()
        assert detail["body"].startswith("Hallo")
        assert api(board_a).get(detail["attachments"][0]["url"]).status_code == 200
        # Verein C gehört nicht zum Verband
        board_c = make_user("vorstand-c2@example.org")
        give_role(board_c, cal["c"])
        assert api(board_c).get(f"{base(cal['c'])}received/").json() == []
        assert api(board_c).get(f"{base(cal['c'])}received/{data['id']}/").status_code == 404
