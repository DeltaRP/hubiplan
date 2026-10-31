"""Finanzamt-Prüfung B6: DATEV-Buchungsstapel für die Steuerberatung (erfundene Daten)."""
# ruff: noqa: F811  (Fixtures als Parameter)

import pytest

from .test_m9_billing import JSON, base, c, club, setup, zug  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def fin(club):
    return f"/api/orgs/{club.pk}/finance"


@pytest.fixture
def buchungen(c, fin, setup):
    out = c.post(
        f"{fin}/categories/", {"name": "Getränkeeinkauf", "kind": "expense"}, content_type=JSON
    ).json()["id"]
    for data in [
        {"kind": "income", "amount": "60", "category": setup["cat"], "text": "Beitrag Erika"},
        {
            "kind": "expense",
            "amount": "45.90",
            "category": out,
            "text": "Wasser und Saft",
            "counterparty": 'Getränke "Müller"',
        },
        {"kind": "transfer", "amount": "20", "to_account": setup["cash"], "text": "Wechselgeld"},
    ]:
        resp = c.post(
            f"{fin}/bookings/",
            {"date": "2025-03-05", "account": setup["bank"], **data},
            content_type=JSON,
        )
        assert resp.status_code == 201, resp.json()
    return {**setup, "out": out}


def test_ausgeschaltet_und_fehlende_konten(c, fin, buchungen):
    resp = c.get(f"{fin}/datev/?jahr=2025")
    assert resp.status_code == 400 and "nicht eingeschaltet" in str(resp.json())
    resp = c.patch(
        f"{fin}/settings/",
        {"datev_enabled": True, "datev_consultant": "1234567", "datev_client": "12345"},
        content_type=JSON,
    )
    assert resp.status_code == 200 and resp.json()["datev_enabled"] is True
    resp = c.get(f"{fin}/datev/?jahr=2025")
    assert resp.status_code == 400
    assert "Girokonto" in str(resp.json()) and "Getränkeeinkauf" in str(resp.json())
    bad = c.patch(f"{fin}/settings/", {"datev_client": "12a"}, content_type=JSON)
    assert bad.status_code == 400


def test_buchungsstapel(c, fin, buchungen):
    c.patch(
        f"{fin}/settings/",
        {
            "datev_enabled": True,
            "datev_consultant": "1234567",
            "datev_client": "12345",
            "datev_chart": "SKR 49",
        },
        content_type=JSON,
    )
    for path, number in [
        (f"accounts/{buchungen['bank']}/", "1200"),
        (f"accounts/{buchungen['cash']}/", "1000"),
        (f"categories/{buchungen['cat']}/", "8100"),
        (f"categories/{buchungen['out']}/", "5400"),
    ]:
        resp = c.patch(f"{fin}/{path}", {"datev_account": number}, content_type=JSON)
        assert resp.status_code == 200, resp.json()
    assert (
        c.patch(
            f"{fin}/categories/{buchungen['out']}/", {"datev_account": "54x"}, content_type=JSON
        ).status_code
        == 400
    )
    resp = c.get(f"{fin}/datev/?jahr=2025")
    assert resp.status_code == 200
    assert "EXTF_Buchungsstapel_20250101_20251231.csv" in resp["Content-Disposition"]
    lines = resp.content.decode("cp1252").split("\r\n")
    head = lines[0].split(";")
    assert head[:5] == ['"EXTF"', "700", "21", '"Buchungsstapel"', "13"]
    assert head[10:16] == ["1234567", "12345", "20250101", "4", "20250101", "20251231"]
    assert head[26] == '"49"'
    assert lines[1].startswith('"Umsatz (ohne Soll/Haben-Kz)";"Soll/Haben-Kennzeichen"')
    rows = [line.split(";") for line in lines[2:] if line]
    assert [(r[0], r[1], r[6], r[7], r[9]) for r in rows] == [
        ("60,00", '"S"', "1200", "8100", "0503"),
        ("45,90", '"H"', "1200", "5400", "0503"),
        ("20,00", '"S"', "1000", "1200", "0503"),
    ]
    assert rows[1][13] == '"Getränke ""Müller"": Wasser und Saft"'
