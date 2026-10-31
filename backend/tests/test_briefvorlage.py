"""Word-Briefvorlage: Briefbogen je Einheit, persönliche Vorlage, Hinweise (erfundene Daten)."""

import datetime
import io
import zipfile
from xml.etree import ElementTree

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from access.catalog import DOCS_MANAGE, MEMBERS_VIEW
from access.models import Role, RoleAssignment
from core.tenancy import tenant_context
from finance.models import Account
from letterhead import data as service
from letterhead.docx import build
from letterhead.models import Letterhead, LetterheadChoice
from members.models import DepartmentRoleHolder, Membership
from organizations.models import Department, DepartmentRole, SocialLink
from portal.models import PortalAccess

from .factories import give_role, make_member, make_user
from .test_datatransfer import _eager, _on_commit_now, as_doc, export, upload  # noqa: F401

JSON = "application/json"


def parts(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return {name: z.read(name) for name in z.namelist()}


def text_of(content: bytes) -> str:
    """Alle XML-Teile als Text (zum Suchen nach Angaben)."""
    return "".join(
        v.decode("utf-8") for k, v in parts(content).items() if k.endswith((".xml", ".rels"))
    )


def png_bytes() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 20), (10, 80, 60)).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def club(orgs):
    club = orgs["a"]
    club.contact_email = "info@verein-a.example.org"
    club.contact_phone = "0123 456"
    club.short_name = "VA"
    club.save()
    return club


@pytest.fixture
def account(club):
    with tenant_context(club.pk):
        return Account.objects.create(
            organization=club,
            name="Girokonto",
            iban="DE89370400440532013000",
            bic="COBADEFFXXX",
            bank_name="Musterbank",
            opening_date=datetime.date(2024, 1, 1),
        )


@pytest.fixture
def zug(club):
    with tenant_context(club.pk):
        return Department.objects.create(organization=club, name="Jägerzug", founding_year=1950)


@pytest.fixture
def chair(club):
    """Vorsitzende mit Mitgliedsakte (private Kontaktdaten) und Vorstandsrolle."""
    user = make_user("vorsitz@example.org", first_name="Vera", last_name="Vorsitz")
    membership = make_member(club, "Vera", "Vorsitz", email="vera.privat@example.org")
    with tenant_context(club.pk):
        person = Membership.objects.get(pk=membership.pk).person
        contact = person.contacts.first()
        contact.phone = "0170 1111111"
        contact.save()
    role = Role.objects.create(
        organization=club,
        name="1. Vorsitzende",
        permissions=[MEMBERS_VIEW],
        represents=True,
        contact_email="vorsitz@verein-a.example.org",
    )
    RoleAssignment.objects.create(
        organization=club,
        role=role,
        user=user,
        person=person,
        valid_from=datetime.date(2020, 1, 1),
    )
    return user


def personal(client, ctx: str, unit: int, function: str, **extra):
    data = {"context": ctx, "unit": unit, "function": function, **extra}
    return client.post("/api/me/letterheads/download/", data)


class TestBriefbogen:
    def test_kein_gruendungsjahr_wenn_im_namen(self, club):
        club.name = "Testverein von 1900"
        club.save(update_fields=["name"])
        assert service.ensure(club).tagline == ""

    def test_standard_und_vererbung(self, club, zug):
        lh = service.ensure(club)
        assert lh.mode == Letterhead.Mode.OWN
        assert lh.tagline == "gegründet 1900"
        assert service.ensure(zug).mode == Letterhead.Mode.INHERIT
        owner, _ = service.owner_of(zug)
        assert owner == club

    def test_eigener_briefbogen_nur_mit_arbeitsbereich(self, club, zug):
        lh = service.ensure(zug)
        lh.mode = Letterhead.Mode.OWN
        lh.save()
        assert service.owner_of(zug)[0] == club
        zug.own_workspace = True
        zug.save()
        assert service.owner_of(zug)[0] == zug

    def test_pflege_durch_vorstand(self, api, club, board_a, account):
        c = api(board_a)
        url = f"/api/orgs/{club.pk}/letterhead/"
        state = c.get(url).json()
        assert state["owner"]["is_self"] is True
        assert state["accounts"][0]["iban"] == "DE89 3704 0044 0532 0130 00"
        resp = c.patch(
            url,
            {"form": "a", "font": "Georgia", "closing": "Mit Schützengruß", "account": account.pk},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        lh = Letterhead.objects.get(organization=club)
        assert (lh.form, lh.font, lh.closing, lh.account_id) == (
            "a",
            "Georgia",
            "Mit Schützengruß",
            account.pk,
        )
        assert c.patch(url, {"mode": "inherit"}, content_type=JSON).status_code == 400
        assert c.patch(url, {"account": 999999}, content_type=JSON).status_code == 400

    def test_lesen_ohne_schreibrecht(self, api, club):
        user = make_user("leser@example.org")
        give_role(user, club, permissions=[MEMBERS_VIEW], name="Leser")
        c = api(user)
        assert c.get(f"/api/orgs/{club.pk}/letterhead/").status_code == 200
        resp = c.patch(f"/api/orgs/{club.pk}/letterhead/", {"form": "a"}, content_type=JSON)
        assert resp.status_code == 403

    def test_untereinheit(self, api, club, zug, board_a):
        c = api(board_a)
        url = f"/api/orgs/{club.pk}/letterhead/units/{zug.pk}/"
        state = c.get(url).json()
        assert state["owner"]["id"] == club.pk
        assert state["may_have_own"] is False
        assert c.patch(url, {"mode": "own"}, content_type=JSON).status_code == 400

    def test_vorschau_und_neutrale_vorlage(self, api, club, board_a, account, zug):
        c = api(board_a)
        pdf = c.get(f"/api/orgs/{club.pk}/letterhead/preview/?unit={zug.pk}")
        assert pdf.status_code == 200
        assert pdf.content.startswith(b"%PDF")
        resp = c.get(f"/api/orgs/{club.pk}/letterhead/download/?type=dotx")
        assert resp.status_code == 200
        assert resp["Content-Type"].endswith("wordprocessingml.template")
        content = resp.content
        assert b"template.main+xml" in parts(content)["[Content_Types].xml"]
        text = text_of(content)
        assert "Verein A" in text
        assert "DE89 3704 0044 0532 0130 00" in text
        assert "info@verein-a.example.org" in text

    def test_fremde_untereinheit(self, api, orgs, board_a):
        with tenant_context(orgs["b"].pk):
            fremd = Department.objects.create(organization=orgs["b"], name="Fremdzug")
        resp = api(board_a).get(f"/api/orgs/{orgs['a'].pk}/letterhead/units/{fremd.pk}/")
        assert resp.status_code == 404


class TestWordDatei:
    def test_xml_gueltig_und_sonderzeichen(self, club, chair, account):
        club.name = 'Schützen & Söhne <1920> "Hubertus"'
        club.save()
        SocialLink.objects.create(organization=club, kind="instagram", url="https://i.example/x")
        lh = service.ensure(club)
        lh.show_social = True
        lh.save()
        ctx = service.contexts_for(chair)[0]
        sender = service.build_sender(chair, ctx, club, ctx.functions[0].key, signature=png_bytes())
        club.logo.save("logo.png", SimpleUploadedFile("logo.png", png_bytes()))
        content = build(service.letter_data(club, sender=sender), "docx")
        files = parts(content)
        for name, raw in files.items():
            if name.endswith((".xml", ".rels")):
                ElementTree.fromstring(raw)  # noqa: S314 – selbst erzeugt, nur Wohlgeformtheit
        assert "word/media/logo.png" in files
        assert "word/media/unterschrift.png" in files
        doc = files["word/document.xml"].decode()
        assert "Schützen &amp; Söhne &lt;1920&gt;" in files["word/header1.xml"].decode()
        assert "Betreff" in doc and "Mit freundlichen Grüßen" in doc
        assert "i.example/x" in files["word/footer1.xml"].decode()

    def test_ohne_logo_auf_wunsch(self, club):
        club.logo.save("logo.png", SimpleUploadedFile("logo.png", png_bytes()))
        content = build(service.letter_data(club, with_logo=False), "dotx")
        assert not any(n.startswith("word/media/") for n in parts(content))

    def test_untereinheit_zusatzzeile(self, club, zug):
        letter = service.letter_data(zug)
        assert letter.name == club.name
        assert letter.sub_line == "Jägerzug"


class TestPersoenlicheVorlage:
    def test_kontexte_und_standardkontakt(self, api, club, chair, zug):
        c = api(chair)
        data = c.get("/api/me/letterheads/").json()
        ctx = data["contexts"][0]
        assert ctx["key"] == f"org:{club.pk}"
        assert [u["name"] for u in ctx["units"]] == [club.name, "Jägerzug"]
        assert ctx["functions"][0]["contact_email"] == "vorsitz@verein-a.example.org"
        assert ctx["own"]["phone"] == "0170 1111111"
        fn = ctx["functions"][0]["key"]
        resp = personal(c, ctx["key"], club.pk, fn, contacts="unit", format="docx")
        assert resp.status_code == 200
        text = text_of(resp.content)
        assert "Vera Vorsitz" in text
        assert "1. Vorsitzende" in text
        assert "info@verein-a.example.org" in text
        # Private Daten nur auf Wahl
        assert "vera.privat@example.org" not in text
        assert "0170 1111111" not in text
        assert "Lindenweg" not in text
        choice = LetterheadChoice.objects.get(user=chair, unit=club)
        assert choice.contacts == ["unit"]
        assert choice.downloaded_at is not None
        assert all(len(v) == 24 for v in choice.checksums.values())

    def test_private_daten_auf_wahl(self, api, club, chair):
        c = api(chair)
        ctx = service.contexts_for(chair)[0]
        resp = personal(
            c,
            ctx.key,
            club.pk,
            ctx.functions[0].key,
            contacts="role,own_email,own_phone,own_address",
            title="Dr.",
            function_text="Vorsitzende und Schriftführerin",
        )
        text = text_of(resp.content)
        assert "vorsitz@verein-a.example.org" in text
        assert "vera.privat@example.org" in text
        assert "0170 1111111" in text
        assert "Lindenweg 4" in text
        assert "Dr. Vera Vorsitz" in text
        assert "Vorsitzende und Schriftführerin" in text

    def test_vorschau(self, api, club, chair):
        ctx = service.contexts_for(chair)[0]
        resp = api(chair).post(
            "/api/me/letterheads/preview/",
            {"context": ctx.key, "unit": club.pk, "function": ctx.functions[0].key},
        )
        assert resp.status_code == 200
        assert resp.content.startswith(b"%PDF")

    def test_unterschrift_muss_bild_sein(self, api, club, chair):
        ctx = service.contexts_for(chair)[0]
        resp = personal(
            api(chair),
            ctx.key,
            club.pk,
            ctx.functions[0].key,
            signature=SimpleUploadedFile("u.png", b"kein bild", content_type="image/png"),
        )
        assert resp.status_code == 400

    def test_ohne_vorstandsrolle_kein_zugang(self, api, club):
        user = make_user("pruefer@example.org")
        assignment = give_role(user, club, permissions=[MEMBERS_VIEW], name="Kassenprüfer")
        assignment.role.is_board = False
        assignment.role.save()
        assert service.contexts_for(user) == []
        resp = personal(api(user), f"org:{club.pk}", club.pk, f"role:{assignment.role_id}")
        assert resp.status_code == 404

    def test_beendete_rolle(self, api, club, chair):
        RoleAssignment.objects.filter(user=chair).update(valid_until=datetime.date(2021, 1, 1))
        assert service.contexts_for(chair) == []

    def test_fremde_einheit_oder_funktion(self, api, orgs, club, chair):
        ctx = service.contexts_for(chair)[0]
        c = api(chair)
        assert personal(c, ctx.key, orgs["b"].pk, ctx.functions[0].key).status_code == 404
        assert personal(c, f"org:{orgs['b'].pk}", orgs["b"].pk, "role:1").status_code == 404
        assert personal(c, ctx.key, club.pk, "role:999999").status_code == 400

    def test_rolle_in_untereinheit(self, api, club, zug):
        user = make_user("zugfuehrer@example.org")
        membership = make_member(club, "Zacharias", "Zug")
        with tenant_context(club.pk):
            role = DepartmentRole.objects.create(
                department=zug, name="Zugführer", contact_email="zug@verein-a.example.org"
            )
            DepartmentRoleHolder.objects.create(
                organization=club,
                membership=membership,
                role=role,
                valid_from=datetime.date(2024, 1, 1),
            )
            PortalAccess.objects.create(organization=club, membership=membership, user=user)
        ctx = service.contexts_for(user)[0]
        assert ctx.key == f"dept:{zug.pk}"
        resp = personal(api(user), ctx.key, zug.pk, f"drole:{role.pk}", contacts="role")
        assert resp.status_code == 200
        text = text_of(resp.content)
        assert "Zacharias Zug" in text
        assert "Zugführer" in text
        assert "zug@verein-a.example.org" in text
        assert "Jägerzug" in text


class TestHinweise:
    def test_veraltet_nach_neuer_iban(self, api, club, chair, account):
        c = api(chair)
        ctx = service.contexts_for(chair)[0]
        personal(c, ctx.key, club.pk, ctx.functions[0].key, contacts="unit")
        assert c.get("/api/me/letterheads/").json()["notices"] == []
        with tenant_context(club.pk):
            account.iban = "DE02120300000000202051"
            account.save()
        notices = c.get("/api/me/letterheads/").json()["notices"]
        assert notices == [
            {
                "kind": "outdated",
                "unit": {"id": club.pk, "name": club.name},
                "context": ctx.key,
                "changes": ["Bankverbindung"],
            }
        ]
        resp = c.post(
            "/api/me/letterheads/dismiss/",
            {"unit": club.pk, "context": ctx.key},
            content_type=JSON,
        )
        assert resp.status_code == 204
        assert c.get("/api/me/letterheads/").json()["notices"] == []

    def test_neue_funktion(self, api, club):
        user = make_user("neu@example.org")
        give_role(user, club, name="Schriftführer", valid_from=datetime.date.today())
        c = api(user)
        notices = c.get("/api/me/letterheads/").json()["notices"]
        assert notices[0]["kind"] == "new"
        assert notices[0]["function"] == "Schriftführer"
        c.post(
            "/api/me/letterheads/dismiss/",
            {"unit": club.pk, "context": f"org:{club.pk}"},
            content_type=JSON,
        )
        assert c.get("/api/me/letterheads/").json()["notices"] == []

    def test_lange_bestehende_funktion_ohne_hinweis(self, api, board_a):
        assert api(board_a).get("/api/me/letterheads/").json()["notices"] == []


class TestDokumentenablage:
    def test_neutrale_vorlage_ablegen(self, api, club, board_a):
        from documents.models import Document, Folder

        club.enabled_modules = ["members", "documents"]
        club.save()
        with tenant_context(club.pk):
            folder = Folder.objects.create(
                organization=club, name="Vorlagen", visibility="board", public_key=Folder.new_key()
            )
        c = api(board_a)
        url = f"/api/orgs/{club.pk}/letterhead/publish/"
        resp = c.post(url, {"folder": folder.pk, "format": "dotx"}, content_type=JSON)
        assert resp.status_code == 201, resp.json()
        assert resp.json()["created"] is True
        again = c.post(url, {"folder": folder.pk}, content_type=JSON).json()
        assert again["created"] is False
        with tenant_context(club.pk):
            doc = Document.objects.get(pk=again["document"])
            assert doc.versions.count() == 2
            assert doc.versions.first().name.endswith(".dotx")

    def test_ohne_ablagerecht(self, api, club):
        user = make_user("nur-org@example.org")
        give_role(user, club, permissions=["org.edit"], name="Geschäftsführer")
        resp = api(user).post(
            f"/api/orgs/{club.pk}/letterhead/publish/", {"folder": 1}, content_type=JSON
        )
        assert resp.status_code == 403
        assert DOCS_MANAGE not in {"org.edit"}


class TestDatenuebernahme:
    def test_briefbogen_wandert_mit(self, api, club, board_a, zug):
        from organizations.models import Organization

        admin = make_user("plattform@example.org")
        give_role(admin, Organization.platform())
        lh = service.ensure(club)
        lh.form, lh.font, lh.closing = "a", "Verdana", "Mit Schützengruß"
        lh.save()
        content, _ = export(api(board_a), f"/api/orgs/{club.pk}")
        assert as_doc(content)["organization"]["letterhead"]["font"] == "Verdana"
        c = api(admin)
        job = upload(c, "/api/platform", content)
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        copy = Letterhead.objects.get(organization_id=job["result_organization"]["id"])
        assert (copy.form, copy.font, copy.closing) == ("a", "Verdana", "Mit Schützengruß")


class TestFusszeile:
    def test_lange_angaben_bleiben_auf_dem_blatt(self, club):
        from letterhead import docx

        club.contact_email = "vorstand@ein-sehr-langer-vereinsname-mit-bindestrichen.test"
        club.save(update_fields=["contact_email"])
        data = service.letter_data(club)
        rows = docx.footer_rows(data)
        assert rows >= 3
        assert docx.bottom_margin(data) >= 8 + rows * docx.FOOTER_LINE_MM
        assert (
            f'w:bottom="{docx.mm(docx.bottom_margin(data))}"'
            in zipfile.ZipFile(io.BytesIO(docx.build(data, "docx")))
            .read("word/document.xml")
            .decode()
        )


class TestPdfBriefe:
    def test_jeder_brief_beginnt_mit_erster_seite(self, club, zug):
        import re

        from reportlab.platypus import Paragraph

        from letterhead.pdf import LetterDocument, text_styles

        letters = [service.letter_data(club), service.letter_data(zug)]
        st = text_styles(letters[0])
        story = []
        for n, data in enumerate(letters):
            story += LetterDocument.start(
                data, ["Max Muster", "Weg 1"], [("Datum", "1.1.")], n == 0
            )
            story += [Paragraph("Text " * 40, st["body"]) for _ in range(30 if n == 0 else 1)]
        buf = io.BytesIO()
        LetterDocument(buf, letters).build(story)
        pages = len(re.findall(rb"/Type /Page\b", buf.getvalue()))
        assert pages >= 3  # langer erster Brief mit Folgeseite, zweiter Brief neu


def test_lange_mailadresse_bricht_im_informationsblock_nicht_um():
    """Ralf 2026-10-30: lange Adressen bleiben einzeilig, die Schrift wird kleiner."""
    import types

    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    from letterhead.docx import INFO_W, single_line_size
    from letterhead.pdf import draw_info

    address = "erika.mustermann@verein.example.org"
    size = single_line_size(address, "Calibri", INFO_W - 24)
    assert 6 <= size < 9
    assert stringWidth(address, "Helvetica", size) / 72 * 25.4 <= INFO_W - 24
    assert single_line_size("info@verein.de", "Calibri", INFO_W - 24) == 9

    c = canvas.Canvas(io.BytesIO())
    letter = types.SimpleNamespace(font="Calibri")
    # eine Zeile (3,8 mm), nicht zwei
    assert draw_info(c, letter, [("E-Mail", address)], 50) == pytest.approx(53.8)


class TestMehrereFunktionen:
    def test_alle_funktionen_voreingestellt(self, api, club, chair):
        person = RoleAssignment.objects.get(user=chair).person
        second = Role.objects.create(
            organization=club, name="Adjutant", contact_email="adjutant@verein-a.example.org"
        )
        RoleAssignment.objects.create(
            organization=club,
            role=second,
            user=chair,
            person=person,
            valid_from=datetime.date(2024, 5, 1),
        )
        ctx = service.contexts_for(chair)[0]
        assert [f.name for f in ctx.functions] == [
            "1. Vorsitzende & Adjutant",
            "1. Vorsitzende",
            "Adjutant",
        ]
        assert ctx.functions[0].key == service.ALL_FUNCTIONS
        c = api(chair)
        resp = personal(c, ctx.key, club.pk, service.ALL_FUNCTIONS, contacts="role", format="docx")
        assert resp.status_code == 200
        text = text_of(resp.content)
        assert "1. Vorsitzende &amp; Adjutant" in text
        assert "vorsitz@verein-a.example.org" in text
        assert "adjutant@verein-a.example.org" in text
        # Einzelne Funktionen bleiben wählbar
        resp = personal(c, ctx.key, club.pk, ctx.functions[2].key, format="docx")
        assert resp.status_code == 200

    def test_eine_funktion_ohne_sammeleintrag(self, club, chair):
        ctx = service.contexts_for(chair)[0]
        assert [f.key for f in ctx.functions] != [service.ALL_FUNCTIONS]
        assert len(ctx.functions) == 1
