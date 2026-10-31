"""Social-Media-Kanäle und Funktionsadressen an Rollen (Stammdaten, erfundene Daten)."""

import pytest

from access.catalog import MEMBERS_VIEW
from access.models import Role
from core.tenancy import rls_bypass, tenant_context
from organizations.models import Department, DepartmentRole, Organization, SocialLink

from .factories import give_role, make_user
from .test_datatransfer import _eager, _on_commit_now, as_doc, export, upload  # noqa: F401

JSON = "application/json"


@pytest.fixture
def platform_admin(db):
    user = make_user("plattform@example.org")
    give_role(user, Organization.platform())
    return user


class TestSocialLinks:
    def test_vorstand_pflegt_kanaele(self, api, orgs, board_a):
        c = api(board_a)
        url = f"/api/orgs/{orgs['a'].pk}/social-links/"
        resp = c.post(
            url,
            {"kind": "instagram", "url": "https://www.instagram.com/musterverein/"},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
        first = resp.json()
        assert first["display"] == "instagram.com/musterverein"
        assert first["kind_label"] == "Instagram"
        resp = c.post(
            url,
            {"kind": "facebook", "url": "https://facebook.com/muster", "label": "Musterverein"},
            content_type=JSON,
        )
        second = resp.json()
        assert second["position"] > first["position"]
        listing = c.get(url).json()
        assert [x["display"] for x in listing] == ["instagram.com/musterverein", "Musterverein"]
        resp = c.patch(f"{url}{second['id']}/", {"position": 0}, content_type=JSON)
        assert resp.status_code == 200
        assert c.get(url).json()[0]["kind"] == "facebook"
        assert c.delete(f"{url}{first['id']}/").status_code == 204
        assert SocialLink.objects.filter(organization=orgs["a"]).count() == 1

    def test_nur_https_adressen(self, api, orgs, board_a):
        url = f"/api/orgs/{orgs['a'].pk}/social-links/"
        resp = api(board_a).post(
            url, {"kind": "x", "url": "javascript:alert(1)"}, content_type=JSON
        )
        assert resp.status_code == 400

    def test_lesen_ohne_schreibrecht(self, api, orgs):
        user = make_user("leser@example.org")
        give_role(user, orgs["a"], permissions=[MEMBERS_VIEW], name="Leser")
        SocialLink.objects.create(
            organization=orgs["a"], kind="youtube", url="https://youtube.com/x"
        )
        c = api(user)
        url = f"/api/orgs/{orgs['a'].pk}/social-links/"
        assert len(c.get(url).json()) == 1
        resp = c.post(url, {"kind": "x", "url": "https://x.com/y"}, content_type=JSON)
        assert resp.status_code == 403

    def test_fremde_einheit_unsichtbar(self, api, orgs, board_a):
        SocialLink.objects.create(
            organization=orgs["b"], kind="youtube", url="https://youtube.com/b"
        )
        resp = api(board_a).get(f"/api/orgs/{orgs['b'].pk}/social-links/")
        assert resp.status_code == 404


class TestFunktionsadressen:
    def test_rolle_mit_funktionsadresse(self, api, orgs, board_a):
        c = api(board_a)
        role = Role.objects.get(organization=orgs["a"], name="Vorstand")
        resp = c.patch(
            f"/api/orgs/{orgs['a'].pk}/roles/{role.pk}/",
            {"contact_email": "vorstand@example.org", "on_letterhead": True},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        role.refresh_from_db()
        assert role.contact_email == "vorstand@example.org"
        assert role.on_letterhead is True

    def test_untereinheit_rolle(self, api, orgs, board_a):
        with tenant_context(orgs["a"].pk):
            zug = Department.objects.create(organization=orgs["a"], name="Jägerzug")
            drole = DepartmentRole.objects.create(department=zug, name="Zugführer")
        resp = api(board_a).patch(
            f"/api/orgs/{orgs['a'].pk}/department-roles/{drole.pk}/",
            {"contact_email": "zug@example.org", "on_letterhead": True},
            content_type=JSON,
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["contact_email"] == "zug@example.org"
        drole.refresh_from_db()
        assert drole.on_letterhead is True


class TestDatenuebernahme:
    def test_kanaele_und_funktionsadressen_wandern_mit(self, api, orgs, board_a, platform_admin):
        club = orgs["a"]
        SocialLink.objects.create(
            organization=club, kind="instagram", url="https://instagram.com/a", label="@a"
        )
        role = Role.objects.get(organization=club, name="Vorstand")
        role.contact_email = "vorstand@example.org"
        role.on_letterhead = True
        role.save()
        content, _ = export(api(board_a), f"/api/orgs/{club.pk}")
        doc = as_doc(content)
        assert doc["organization"]["social_links"][0]["label"] == "@a"

        c = api(platform_admin)
        job = upload(c, "/api/platform", content)
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        with rls_bypass():
            new = Organization.objects.get(pk=job["result_organization"]["id"])
            link = SocialLink.objects.get(organization=new)
            assert (link.kind, link.label) == ("instagram", "@a")
            copy = Role.objects.get(organization=new, name="Vorstand")
            assert copy.contact_email == "vorstand@example.org"
            assert copy.on_letterhead is True
