"""Audit Datenspeicherung und Berechnungen 31.10.: vollständige Übernahme."""
# ruff: noqa: F811  (Fixtures als Parameter)

import datetime
from decimal import Decimal

import pytest

from core.tenancy import rls_bypass, tenant_context
from finance.models import Account, Booking, Category
from members.models import Membership, MemberType
from organizations.models import Department, Organization
from website.models import Website
from website.social_models import SocialFeed, SocialPost

from .test_datatransfer import (  # noqa: F401
    _eager,
    _on_commit_now,
    as_doc,
    board_fed,
    club_c,
    export,
    platform_admin,
    types,
    upload,
)
from .test_m2_members import admit, make_types

pytestmark = pytest.mark.django_db
JSON = "application/json"


def run_import(c, content):
    job = upload(c, "/api/platform", content)
    assert job["preview"]["error_count"] == 0, job["preview"]["errors"]
    c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
    job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
    assert job["status"] == "done", job
    return Organization.objects.get(pk=job["result_organization"]["id"])


class TestD3101ArbeitsbereichDerUntereinheit:
    def test_kasse_der_untereinheit_zieht_mit(self, api, club_c, board_c, platform_admin):
        club = club_c["club"]
        with tenant_context(club.pk):
            zug = Department.objects.create(
                organization=club, name="2. Zug", founding_year=1960, own_workspace=True
            )
        with tenant_context(zug.pk):
            kasse = Account.objects.create(
                organization=zug,
                name="Zugkasse",
                kind="cash",
                opening_balance=Decimal("100.00"),
                opening_date=datetime.date(2024, 1, 1),
            )
            cat = Category.objects.create(organization=zug, name="Feste", kind="income")
            Booking.objects.create(
                organization=zug,
                year=2024,
                number=1,
                date=datetime.date(2024, 5, 1),
                kind="income",
                amount=Decimal("12.50"),
                account=kasse,
                category=cat,
                text="Kuchen",
            )
        content, _ = export(api(board_c), f"/api/orgs/{club.pk}")
        doc = as_doc(content)
        dept = next(d for d in doc["organization"]["departments"] if d["name"] == "2. Zug")
        assert dept["own_workspace"] is True
        assert dept["tables"]["finance.account"][0]["opening_balance"] == "100.00"

        new = run_import(api(platform_admin), content)
        with rls_bypass():
            new_zug = Department.objects.get(organization=new, name="2. Zug")
            assert new_zug.own_workspace is True
            acc = Account.objects.get(organization=new_zug)
            assert acc.opening_balance == Decimal("100.00")
            assert Booking.objects.get(organization=new_zug).amount == Decimal("12.50")


class TestD3102DirekteVerbandsmitglieder:
    def test_eigene_mitglieder_des_dachverbands(self, api, orgs, board_fed, platform_admin):
        fed = orgs["federation"]
        c = api(board_fed)
        assert (
            c.patch(f"/api/orgs/{fed.pk}/", {"direct_members": True}, content_type=JSON).status_code
            == 200
        )
        with tenant_context(fed.pk):
            t = make_types(fed)
        m = admit(c, fed, t["passiv"], last_name="Direkt").json()
        content, _ = export(api(platform_admin), "/api/platform", organization=fed.pk)
        doc = as_doc(content)
        assert doc["organization"]["direct_members"] is True
        assert [x["id"] for x in doc["organization"]["memberships"]] == [m["id"]]

        new = run_import(api(platform_admin), content)
        assert new.direct_members is True
        with rls_bypass():
            ms = Membership.objects.get(organization=new)
            assert ms.person.last_name == "Direkt"
            assert MemberType.objects.filter(organization=new, name="passiv").exists()


class TestD3103SocialMedia:
    def test_beitraege_ohne_zugangsdaten(self, api, club_c, board_c, platform_admin):
        club = club_c["club"]
        with tenant_context(club.pk):
            site = Website.objects.filter(organization=club).first() or Website.objects.create(
                organization=club
            )
            feed = SocialFeed.objects.create(
                organization=club,
                website=site,
                kind="instagram",
                app_id="123",
                app_secret="geheim-verschluesselt",
                access_token="token-verschluesselt",
                status="ok",
                account_name="verein_c",
            )
            SocialPost.objects.create(
                organization=club,
                feed=feed,
                external_id="p1",
                media_type="text",
                text="Schützenfest!",
                published_at=datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
                state="hidden",
            )
        content, _ = export(api(board_c), f"/api/orgs/{club.pk}")
        assert b"geheim-verschluesselt" not in content and b"token-verschluesselt" not in content
        new = run_import(api(platform_admin), content)
        with rls_bypass():
            f = SocialFeed.objects.get(organization=new)
            assert f.access_token == "" and f.status == "new" and f.account_name == "verein_c"
            post = SocialPost.objects.get(organization=new)
            assert post.state == "hidden" and post.text == "Schützenfest!"
