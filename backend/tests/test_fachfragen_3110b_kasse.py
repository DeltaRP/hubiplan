"""Fachfragen 31.10.b, Kasse: Gegenbeleg, Kategorien abgeschlossener Jahre (erfundene Daten)."""

import pytest

from core.tenancy import tenant_context

from .test_m9_billing import JSON, base, c, club, members, setup, zug  # noqa: F401
from .test_quittung import _private, bestand, draft, finalize, q, sign  # noqa: F401

pytestmark = pytest.mark.django_db


# --- Frage 10: Quittung aus abgeschlossenem Jahr: Gegenbeleg im laufenden Jahr ---


def test_storno_aus_abgeschlossenem_jahr_als_gegenbeleg(c, q, bestand, club):  # noqa: F811
    from finance.models import Booking, YearClosing

    r = draft(c, q)
    sign(c, q, r["id"], "treasurer")
    sign(c, q, r["id"], "counterparty")
    done = finalize(c, q, r["id"]).json()
    original = Booking.objects.get(pk=done["booking"])
    old_year = original.year - 1
    with tenant_context(club.pk):
        Booking.objects.filter(pk=original.pk).update(
            year=old_year, number=9999, date=original.date.replace(year=original.date.year - 1)
        )
        YearClosing.objects.create(organization=club, year=old_year)
    resp = c.post(f"{q['url']}{r['id']}/cancel/", {"reason": "Betrag falsch"}, content_type=JSON)
    assert resp.status_code == 200, resp.json()
    counter = Booking.objects.exclude(pk__in=[original.pk, bestand]).get()
    assert counter.year == original.year  # laufendes Jahr
    assert counter.text.startswith(f"Gegenbeleg zu Quittung {done['number']}")
    original.refresh_from_db()
    assert original.year == old_year and original.amount == counter.amount


# --- Frage 9: Kategorien in abgeschlossenen Jahren bleiben wie beim Abschluss ---


def test_abgeschlossenes_jahr_behaelt_steuerbereich(c, q, bestand, club):  # noqa: F811
    from finance import services
    from finance.models import Category

    club.tax_areas_enabled = True
    club.save(update_fields=["tax_areas_enabled"])
    with tenant_context(club.pk):
        Category.objects.filter(pk=q["cat"]).update(tax_area="purpose", name="Getränke")
    resp = c.post(f"{q['fin']}/closings/", {"year": 2025}, content_type=JSON)
    assert resp.status_code in (200, 201), resp.json()
    resp = c.patch(
        f"{q['fin']}/categories/{q['cat']}/",
        {"tax_area": "business", "name": "Getränkeverkauf"},
        content_type=JSON,
    )
    assert resp.status_code == 200, resp.json()

    with tenant_context(club.pk):
        report = services.overview(club, 2025)
    assert [a["area"] for a in report["tax_areas"]] == ["purpose"]
    assert [x["name"] for x in report["categories"]] == ["Getränke"]
    booking = c.get(f"{q['fin']}/bookings/{bestand}/").json()
    assert (booking["tax_area"], booking["category_name"]) == ("purpose", "Getränke")

    neu = c.post(
        f"{q['fin']}/bookings/",
        {
            "date": "2026-01-05",
            "kind": "income",
            "amount": "10.00",
            "account": q["cash"],
            "category": q["cat"],
            "text": "Neu",
        },
        content_type=JSON,
    ).json()
    assert (neu["tax_area"], neu["category_name"]) == ("business", "Getränkeverkauf")


# --- Frage 17 (PERF-02): Finanzlisten fragen nicht je Konto oder Kategorie extra ---


def test_finanzlisten_abfragen_wachsen_nicht(api, board_a, orgs):  # noqa: F811
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    unit = orgs["a"]
    unit.enabled_modules = ["finance", "members"]
    unit.save()
    cl = api(board_a)
    root = f"/api/orgs/{unit.pk}/finance"
    counts = {}
    for n in (2, 8):
        while len(cl.get(f"{root}/accounts/").json()) < n:
            i = len(cl.get(f"{root}/accounts/").json())
            cl.post(
                f"{root}/accounts/",
                {"name": f"Konto {i}", "kind": "bank", "opening_date": "2025-01-01"},
                content_type="application/json",
            )
            cl.post(
                f"{root}/categories/",
                {"name": f"Kategorie {i}", "kind": "income"},
                content_type="application/json",
            )
        for path in ("accounts/", "categories/", "overview/?year=2025"):
            with CaptureQueriesContext(connection) as queries:
                assert cl.get(f"{root}/{path}").status_code == 200
            counts.setdefault(path, []).append(len(queries))
    for path, (small, large) in counts.items():
        assert large == small, (path, counts)
