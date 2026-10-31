"""Zuwendungsbestätigungen nach amtlichem Muster (steuerbegünstigte Einheiten mit Bescheid)."""
# ruff: noqa: F811  (Fixtures als Parameter)

import datetime

import pytest
from django.db import connection

from core.rls import APP_ROLE
from core.tenancy import set_rls, tenant_context
from finance.models import Donation, DonationSettings
from organizations.imprint import ensure

from .factories import make_member
from .test_m9_billing import JSON, base, c, club, setup, zug  # noqa: F401

pytestmark = pytest.mark.django_db

SETTINGS = {
    "enabled": True,
    "purposes": "des traditionellen Brauchtums einschließlich des Schützenwesens",
    "notice": "exemption",
    "tax_office": "Neuss",
    "tax_number": "122/5701/0000",
    "assessment_period": "2022 bis 2024",
    "place": "Neuss",
}


@pytest.fixture(autouse=True)
def _private(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


def register(org, value=True):
    """Schalter „steuerbegünstigt mit eigenem Bescheid“."""
    with tenant_context(org.pk):
        DonationSettings.objects.update_or_create(organization=org, defaults={"enabled": value})


@pytest.fixture
def ev(club, setup):
    register(club)
    return f"/api/orgs/{club.pk}/finance"


@pytest.fixture
def ready(ev, c):
    today = datetime.date.today()
    data = {**SETTINGS, "notice_date": (today - datetime.timedelta(days=400)).isoformat()}
    resp = c.put(f"{ev}/donation-settings/", data, content_type=JSON)
    assert resp.status_code == 200, resp.json()
    assert resp.json()["problems"] == []
    return ev


def donate(c, fin, **extra):
    data = {
        "date": f"{datetime.date.today().year}-01-15",
        "amount": "100.00",
        "donor_name": "Max Muster",
        "donor_address": "Musterweg 1\n41468 Neuss",
        **extra,
    }
    resp = c.post(f"{fin}/donations/", data, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    return resp.json()


def test_nur_mit_schalter_steuerbeguenstigt(club, setup, c):
    # Entscheidend ist der Schalter, nicht der Registereintrag: auch ein nicht
    # eingetragener Verein kann steuerbegünstigt sein (§ 1 Abs. 1 Nr. 5 KStG)
    fin = f"/api/orgs/{club.pk}/finance"
    with tenant_context(club.pk):
        imprint = ensure(club)
        imprint.registered = False
        imprint.save()
    data = c.get(f"{fin}/donation-settings/").json()
    assert data["enabled"] is False
    assert "nicht als steuerbegünstigt" in data["problems"][0]
    me = c.get("/api/me/organizations/").json()
    assert any(o["id"] == club.pk and o["donations_enabled"] is False for o in me)
    resp = c.put(
        f"{fin}/donation-settings/",
        {**SETTINGS, "notice_date": datetime.date.today().isoformat()},
        content_type=JSON,
    )
    assert resp.json()["problems"] == []
    d = donate(c, fin)
    resp = c.post(f"{fin}/donation-statements/", {"donations": [d["id"]]}, content_type=JSON)
    assert resp.status_code == 201, resp.json()
    me = c.get("/api/me/organizations/").json()
    assert any(o["id"] == club.pk and o["donations_enabled"] is True for o in me)
    # ausschalten sperrt das Ausstellen wieder
    c.put(f"{fin}/donation-settings/", {"enabled": False}, content_type=JSON)
    d = donate(c, fin)
    resp = c.post(f"{fin}/donation-statements/", {"donations": [d["id"]]}, content_type=JSON)
    assert resp.status_code == 400


def test_nicht_fuer_die_plattform(orgs):
    from finance import donations
    from organizations.models import Organization

    assert donations.available(orgs["a"]) is True
    assert donations.available(Organization.platform()) is False


def test_ohne_bescheid_nichts_ausstellen(ev, c):
    d = donate(c, ev)
    data = c.get(f"{ev}/donation-settings/").json()
    assert data["problems"] and "Finanzamt" in data["problems"][0]
    resp = c.post(f"{ev}/donation-statements/", {"donations": [d["id"]]}, content_type=JSON)
    assert resp.status_code == 400


def test_alter_bescheid_gesperrt(ev, c):
    old = datetime.date.today().replace(year=datetime.date.today().year - 6)
    data = c.put(
        f"{ev}/donation-settings/", {**SETTINGS, "notice_date": old.isoformat()}, content_type=JSON
    ).json()
    assert any("älter als 5 Jahre" in p for p in data["problems"])
    # Feststellung nach § 60a AO: schon nach 3 Jahren
    four = datetime.date.today().replace(year=datetime.date.today().year - 4)
    data = c.put(
        f"{ev}/donation-settings/",
        {"notice": "statute", "notice_date": four.isoformat()},
        content_type=JSON,
    ).json()
    assert any("älter als 3 Jahre" in p for p in data["problems"])
    d = donate(c, ev)
    resp = c.post(f"{ev}/donation-statements/", {"donations": [d["id"]]}, content_type=JSON)
    assert resp.status_code == 400


def test_einzelbestaetigung_doppel_und_storno(ready, c):
    d = donate(c, ready, waiver=True)
    resp = c.post(
        f"{ready}/donation-statements/",
        {"donations": [d["id"]], "signer_name": "Erika Kasse"},
        content_type=JSON,
    )
    assert resp.status_code == 201, resp.json()
    st = resp.json()
    assert st["kind"] == "single" and st["number"].startswith("ZB-")
    assert st["total"] == "100.00"
    pdf = c.get(f"{ready}/donation-statements/{st['id']}/pdf/")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # bestätigt: nicht mehr änderbar oder löschbar, nicht zweimal bestätigen
    url = f"{ready}/donations/{d['id']}/"
    assert c.patch(url, {"amount": "50.00"}, content_type=JSON).status_code == 400
    assert c.delete(url).status_code == 400
    again = c.post(f"{ready}/donation-statements/", {"donations": [d["id"]]}, content_type=JSON)
    assert again.status_code == 400
    # Storno gibt die Zuwendung frei, das Doppel bleibt
    assert (
        c.post(f"{ready}/donation-statements/{st['id']}/cancel/", {}, content_type=JSON).status_code
        == 400
    )
    resp = c.post(
        f"{ready}/donation-statements/{st['id']}/cancel/",
        {"reason": "Betrag falsch"},
        content_type=JSON,
    )
    assert resp.status_code == 200 and resp.json()["cancelled_at"]
    assert c.patch(url, {"amount": "50.00"}, content_type=JSON).status_code == 200
    assert c.get(f"{ready}/donation-statements/{st['id']}/pdf/").status_code == 200
    nxt = c.post(f"{ready}/donation-statements/", {"donations": [d["id"]]}, content_type=JSON)
    assert nxt.status_code == 201
    assert nxt.json()["number"] != st["number"]


def test_sammelbestaetigung_jahresende(ready, c, club):
    year = datetime.date.today().year
    m = make_member(club, "Erika", "Muster", "erika@example.org")
    donate(c, ready, membership=m.pk, donor_name="", donor_address="", date=f"{year}-01-10")
    donate(c, ready, membership=m.pk, donor_name="", donor_address="", date=f"{year}-01-20")
    donate(c, ready, donor_name="Anna Andere", amount="25.00")
    donate(
        c,
        ready,
        kind="goods",
        amount="80.00",
        goods_description="Zelt, 2 Jahre alt, gut erhalten, Kaufpreis 150 €",
        goods_origin="private",
    )
    preview = c.get(f"{ready}/donations/year-end/?jahr={year}").json()
    assert len(preview["donors"]) == 2  # Sachzuwendung nicht gesammelt
    resp = c.post(f"{ready}/donation-statements/year-end/", {"year": year}, content_type=JSON)
    assert resp.status_code == 200, resp.json()
    made = {s["donor_name"]: s for s in resp.json()["items"]}
    assert made["Erika Muster"]["kind"] == "collective"
    assert made["Erika Muster"]["total"] == "200.00"
    assert made["Erika Muster"]["period_from"] == f"{year}-01-01"
    assert made["Anna Andere"]["kind"] == "single"
    for s in made.values():
        assert c.get(f"{ready}/donation-statements/{s['id']}/pdf/").content.startswith(b"%PDF")
    # Sachzuwendung bleibt offen und wird einzeln bestätigt
    open_ = c.get(f"{ready}/donations/?offen=1").json()["results"]
    assert len(open_) == 1 and open_[0]["kind"] == "goods"
    resp = c.post(
        f"{ready}/donation-statements/", {"donations": [open_[0]["id"]]}, content_type=JSON
    )
    assert resp.status_code == 201 and resp.json()["goods"] is True
    assert c.get(f"{ready}/donation-statements/{resp.json()['id']}/pdf/").status_code == 200


def test_sammelbestaetigung_nur_ein_zuwendender_ohne_sachen(ready, c):
    a = donate(c, ready)
    b = donate(c, ready, donor_name="Anna Andere")
    g = donate(
        c, ready, kind="goods", goods_description="Fahne", goods_origin="unknown", amount="50"
    )
    for ids in ([a["id"], b["id"]], [a["id"], g["id"]]):
        resp = c.post(f"{ready}/donation-statements/", {"donations": ids}, content_type=JSON)
        assert resp.status_code == 400


def test_mitgliedsbeitraege_nur_wenn_eingeschaltet(ready, c):
    data = {
        "date": "2025-03-01",
        "amount": "60.00",
        "donor_name": "Max Muster",
        "donor_address": "Musterweg 1\n41468 Neuss",
        "kind": "fee",
    }
    assert c.post(f"{ready}/donations/", data, content_type=JSON).status_code == 400
    c.put(f"{ready}/donation-settings/", {"fees_allowed": True}, content_type=JSON)
    d = c.post(f"{ready}/donations/", data, content_type=JSON)
    assert d.status_code == 201
    resp = c.post(
        f"{ready}/donation-statements/", {"donations": [d.json()["id"]]}, content_type=JSON
    )
    assert resp.status_code == 201


def test_sachzuwendung_braucht_angaben(ready, c):
    data = {"date": "2025-03-01", "amount": "60.00", "donor_name": "Max", "kind": "goods"}
    resp = c.post(f"{ready}/donations/", data, content_type=JSON)
    assert resp.status_code == 400
    assert "goods_description" in resp.json() and "goods_origin" in resp.json()


def test_aus_kassenbuch_uebernehmen(ready, c, setup):
    year = datetime.date.today().year
    cat = c.post(
        f"{ready}/categories/",
        {"name": "Spenden", "kind": "income", "donations": True},
        content_type=JSON,
    ).json()
    assert cat["donations"] is True
    booking = {
        "date": f"{year}-01-05",
        "kind": "income",
        "amount": "250.00",
        "account": setup["bank"],
        "category": cat["id"],
        "text": "Spende Fahnenweihe",
        "counterparty": "Firma Beispiel GmbH",
    }
    assert c.post(f"{ready}/bookings/", booking, content_type=JSON).status_code == 201
    # andere Kategorie: nicht übernehmen
    other = {**booking, "category": setup["cat"], "text": "Beitrag"}
    assert c.post(f"{ready}/bookings/", other, content_type=JSON).status_code == 201
    resp = c.post(f"{ready}/donations/import/", {"year": year}, content_type=JSON)
    assert resp.json()["created"] == 1
    # zweimal übernehmen legt nichts doppelt an
    assert (
        c.post(f"{ready}/donations/import/", {"year": year}, content_type=JSON).json()["created"]
        == 0
    )
    items = c.get(f"{ready}/donations/").json()["results"]
    assert items[0]["donor_name"] == "Firma Beispiel GmbH"
    assert items[0]["booking_number"]


def test_nur_lesen_ohne_kassenrecht(ready, c, club, api):
    from .factories import give_role, make_user

    reader = make_user("leser@example.org")
    give_role(reader, club, ["finance.view"], name="Prüfer")
    r = api(reader)
    assert r.get(f"{ready}/donations/").status_code == 200
    data = {"date": "2025-03-01", "amount": "10", "donor_name": "X"}
    assert r.post(f"{ready}/donations/", data, content_type=JSON).status_code == 403


@pytest.mark.skipif(connection.vendor != "postgresql", reason="nur PostgreSQL")
def test_rls_zuwendungen(ready, c, club, orgs):
    donate(c, ready)
    with connection.cursor() as cursor:
        cursor.execute(f"SET ROLE {APP_ROLE}")
    try:
        set_rls(orgs["b"].pk)
        assert Donation.objects.count() == 0
        assert DonationSettings.objects.count() == 0
        set_rls(club.pk)
        assert Donation.objects.count() == 1
        assert DonationSettings.objects.count() == 1
    finally:
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
        set_rls(None, None, False)


def test_jahre_mit_daten(ready, c):
    # UX-Audit 31.10.: Jahresauswahl zeigt alle Jahre mit Zuwendungen, neueste zuerst
    year = datetime.date.today().year
    donate(c, ready)
    donate(c, ready, date=f"{year - 3}-05-01")
    assert c.get(f"{ready}/donations/years/").json() == [year, year - 3]
    assert c.get(f"{ready}/donation-statements/years/").json() == []


def test_pruefliste_vor_den_jahresbestaetigungen(ready, c):
    # Lernhilfen: Zahlen für die Prüfliste, nur offene Zuwendungen des Jahres
    year = datetime.date.today().year
    url = f"{ready}/donations/checks/?jahr={year}"
    assert c.get(url).json() == {
        "open": 0,
        "without_address": 0,
        "goods_without_documents": 0,
        "goods_open": 0,
        "fees_skipped": 0,
    }
    done = donate(c, ready)
    assert (
        c.post(
            f"{ready}/donation-statements/", {"donations": [done["id"]]}, content_type=JSON
        ).status_code
        == 201
    )
    donate(c, ready, donor_address="  ")
    donate(
        c,
        ready,
        kind="goods",
        goods_description="Zelt, 3 Jahre alt",
        goods_origin="private",
    )
    donate(c, ready, date=f"{year - 1}-05-01", donor_address="")
    assert c.get(url).json() == {
        "open": 2,
        "without_address": 1,
        "goods_without_documents": 1,
        "goods_open": 1,
        "fees_skipped": 0,
    }


def test_ohne_name_oder_anschrift_keine_bestaetigung(ready, c):
    """Fachfrage 5 (Audit 31.10.): „Unbekannt“ oder fehlende Anschrift sperrt das Ausstellen."""
    year = datetime.date.today().year
    a = donate(c, ready, donor_name="Unbekannt", donor_address="Irgendwo 1")
    b = donate(c, ready, donor_name="Bea Beispiel", donor_address="")
    for d in (a, b):
        resp = c.post(f"{ready}/donation-statements/", {"donations": [d["id"]]}, content_type=JSON)
        assert resp.status_code == 400
    donate(c, ready, donor_name="Carl Komplett")
    preview = c.get(f"{ready}/donations/year-end/?jahr={year}").json()
    missing = {d["donor_name"]: d["incomplete"] for d in preview["donors"]}
    assert missing["Unbekannt"] and missing["Bea Beispiel"] and not missing["Carl Komplett"]
    resp = c.post(f"{ready}/donation-statements/year-end/", {"year": year}, content_type=JSON)
    assert [s["donor_name"] for s in resp.json()["items"]] == ["Carl Komplett"]
