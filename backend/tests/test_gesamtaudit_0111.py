"""Gesamtaudit 01.11.2026: Regressionstests zu den behobenen Befunden (erfundene Daten)."""

import pytest

pytestmark = pytest.mark.django_db
JSON = "application/json"


def _totp(user):
    from allauth.mfa.models import Authenticator

    return Authenticator.objects.create(user=user, type=Authenticator.Type.TOTP, data={})


# --- GA-S01: 2FA-Reset nur für Konten, die allein in diesem Verein Rechte haben ---


@pytest.mark.parametrize("fremd", ["anderer_verein", "verband", "staff"])
def test_reset_mfa_nicht_fuer_konten_mit_rechten_anderswo(orgs, api, board_a, fremd):
    from allauth.mfa.models import Authenticator

    from accounts.models import User

    from .factories import give_role, make_user

    ziel = make_user("ziel@example.org", is_staff=(fremd == "staff"))
    if fremd == "anderer_verein":
        give_role(ziel, orgs["b"])
    elif fremd == "verband":
        give_role(ziel, orgs["federation"])
    _totp(ziel)
    # Rollenverwaltung A vergibt eine Rolle an die bekannte Adresse und will zurücksetzen
    zuordnung = give_role(ziel, orgs["a"], name="Beisitz")
    _totp(board_a)
    board = User.objects.get(pk=board_a.pk)
    resp = api(board).post(f"/api/orgs/{orgs['a'].pk}/assignments/{zuordnung.pk}/reset-mfa/")
    assert resp.status_code == 400
    assert "Plattform" in resp.json()["detail"]
    assert Authenticator.objects.filter(user=ziel).exists()


def test_reset_mfa_bei_rolle_in_eigener_untereinheit_erlaubt(orgs, api, board_a):
    from allauth.mfa.models import Authenticator

    from accounts.models import User

    from .factories import give_role, make_org, make_user

    einheit = make_org("Zug 1", "unit", parent=orgs["a"])
    ziel = make_user("zug@example.org")
    give_role(ziel, einheit)
    zuordnung = give_role(ziel, orgs["a"], name="Beisitz")
    _totp(ziel)
    _totp(board_a)
    board = User.objects.get(pk=board_a.pk)
    resp = api(board).post(f"/api/orgs/{orgs['a'].pk}/assignments/{zuordnung.pk}/reset-mfa/")
    assert resp.status_code == 200, resp.json()
    assert not Authenticator.objects.filter(user=ziel).exists()


# --- GA-S03: nur das Ergebnis des eigenen Mailservers zählt ---


def test_dmarc_pass_nur_vom_eigenen_server(settings):
    from email.message import EmailMessage

    from circulars.inbound import dmarc_passed

    msg = EmailMessage()
    msg["Authentication-Results"] = "mx.example.org; dmarc=none"
    msg["Authentication-Results"] = "fremd.example.net; dmarc=pass"
    assert not dmarc_passed(msg)  # nur der oberste Eintrag zählt
    settings.MAIL_AUTHSERV_ID = "mx.example.org"
    msg2 = EmailMessage()
    msg2["Authentication-Results"] = "fremd.example.net; dmarc=pass"
    assert not dmarc_passed(msg2)
    msg2["Authentication-Results"] = "mx.example.org; dmarc=pass"
    assert dmarc_passed(msg2)


# --- GA-S08: Rückgängig hält die Regel „Barkasse nie unter null“ ein ---


def test_rueckgaengig_macht_barkasse_nicht_negativ(orgs, api, board_a, settings, tmp_path):
    from decimal import Decimal

    from core.tenancy import tenant_context
    from finance.models import Account
    from finance.services import balance

    settings.PRIVATE_ROOT = tmp_path / "private"
    club = orgs["a"]
    club.enabled_modules = ["finance", "members"]
    club.save()
    base = f"/api/orgs/{club.pk}/finance"
    c = api(board_a)
    cash = c.post(
        f"{base}/accounts/",
        {"name": "Barkasse", "kind": "cash", "opening_balance": "0", "opening_date": "2025-01-01"},
        content_type=JSON,
    ).json()["id"]
    inc = c.post(f"{base}/categories/", {"name": "Spenden", "kind": "income"}, content_type=JSON)
    out = c.post(f"{base}/categories/", {"name": "Material", "kind": "expense"}, content_type=JSON)
    einnahme = c.post(
        f"{base}/bookings/",
        {
            "date": "2025-03-01",
            "kind": "income",
            "amount": "100.00",
            "account": cash,
            "category": inc.json()["id"],
            "text": "Spende",
        },
        content_type=JSON,
    )
    assert einnahme.status_code == 201, einnahme.json()
    set_id = einnahme["X-Change-Set"]
    ausgabe = c.post(
        f"{base}/bookings/",
        {
            "date": "2025-03-02",
            "kind": "expense",
            "amount": "80.00",
            "account": cash,
            "category": out.json()["id"],
            "text": "Material",
        },
        content_type=JSON,
    )
    assert ausgabe.status_code == 201, ausgabe.json()
    # Löschen lehnt die normale Schnittstelle ab …
    assert c.delete(f"{base}/bookings/{einnahme.json()['id']}/").status_code == 400
    # … und Rückgängig ebenso
    undo = c.post(f"/api/orgs/{club.pk}/changes/{set_id}/undo/", {"force": True}, content_type=JSON)
    assert undo.status_code == 409
    assert "unter null" in " ".join(undo.json()["problems"])
    with tenant_context(club.pk):
        assert balance(Account.objects.get(pk=cash), all_dates=True) == Decimal("20.00")


# --- GA-S09/GA-P03: Rücklagen gesperrt und mit fester Abfragezahl ---


def test_ruecklage_wird_beim_pruefen_gesperrt(orgs, monkeypatch):
    import datetime

    from core.tenancy import tenant_context
    from finance import reserves
    from finance.models import Reserve

    club = orgs["a"]
    with tenant_context(club.pk):
        reserve = Reserve.objects.create(organization=club, name="Fahne", kind="free")
        locked = []
        real = Reserve.objects.select_for_update

        def spy(*args, **kwargs):
            locked.append(True)
            return real(*args, **kwargs)

        monkeypatch.setattr(Reserve.objects, "select_for_update", spy)
        reserves._never_negative(reserve, [(datetime.date(2025, 1, 1), 5)])
    assert locked


def test_ruecklagen_bestaende_mit_einer_abfrage(orgs, django_assert_max_num_queries):
    import datetime
    from decimal import Decimal

    from core.tenancy import tenant_context
    from finance import reserves
    from finance.models import Reserve, ReserveMovement

    club = orgs["a"]
    with tenant_context(club.pk):
        for i in range(10):
            r = Reserve.objects.create(organization=club, name=f"R{i}", kind="free")
            ReserveMovement.objects.create(
                organization=club,
                reserve=r,
                direction="add",
                date=datetime.date(2025, 1, 1),
                year=2025,
                amount=Decimal("10.00") * (i + 1),
            )
        with django_assert_max_num_queries(2):
            result = reserves.balances(club)
    assert sorted(result.values()) == [Decimal("10.00") * (i + 1) for i in range(10)]


# --- GA-F06: Kürzung und Komplettlöschung der Protokollkette fallen auf ---


def test_protokollkette_erkennt_geloeschtes_ende(orgs, board_a):
    from audit.chain import seal, verify
    from audit.log import record
    from audit.models import AuditCheck, AuditEntry
    from audit.tasks import check_chains
    from core.tenancy import rls_bypass, tenant_context

    club = orgs["a"]
    with tenant_context(club.pk):
        for i in range(3):
            record(club, board_a, "update", club, {"Name": [f"A{i}", f"B{i}"]})
    seal(club.pk)
    assert verify(club.pk)["ok"]
    head = AuditCheck.objects.get(organization=club).head_seq
    with rls_bypass():
        AuditEntry.objects.filter(organization=club, seq=head).delete()
    result = verify(club.pk)
    assert not result["ok"] and "Ende der Kette" in " ".join(result["problems"])
    assert AuditCheck.objects.get(organization=club).head_seq == head  # Kopf bleibt
    # Alles weg: die tägliche Prüfung schaut trotzdem hin
    with rls_bypass():
        AuditEntry.objects.filter(organization=club).delete()
    check_chains()
    check = AuditCheck.objects.get(organization=club)
    assert not check.ok and check.head_seq == head


# --- GA-F08/F09: Vollübernahme mit Kassenzählung, Finanzeinstellungen, CAMT-Original ---


def test_export_enthaelt_kassenzaehlung_und_finanzeinstellungen():
    from datatransfer import dump, tables

    assert "finance.CashCount" in tables.MODULE_MODELS
    for field in (
        "finance_locked_until",
        "cash_counts_enabled",
        "reserves_enabled",
        "datev_enabled",
    ):
        assert field in dump.ORG_FIELDS and field in dump.DEPT_FIELDS


def test_camt_original_laesst_sich_wieder_einlesen():
    import hashlib

    from django.core.exceptions import ValidationError

    from datatransfer.tables import check_file
    from finance.models import BankStatement

    from .test_kontoauszug import camt_xml, entry

    data = camt_xml([entry("12.50")])
    data = data.encode() if isinstance(data, str) else data
    obj = BankStatement(source_sha256=hashlib.sha256(data).hexdigest())
    check_file("finance.bankstatement", obj, data, "kontoauszug.xml")
    with pytest.raises(ValidationError):
        check_file("finance.bankstatement", obj, data + b" ", "kontoauszug.xml")
    obj.source_sha256 = ""
    with pytest.raises(ValidationError):
        check_file("finance.bankstatement", obj, b"<kein camt/>", "kontoauszug.xml")


def test_kassenzaehlung_kennungen_werden_umgeschrieben():
    from datatransfer.tables import IdMap, fix_json_ids
    from finance.models import CashCount

    ids = IdMap()
    ids.set("finance.booking", 1, 101)
    ids.set("finance.category", 7, 70)
    obj = CashCount(booking_ids=[1, 2], lines=[{"category": 7, "name": "Fest", "amount": "5.00"}])
    fix_json_ids("finance.cashcount", obj, ids)
    assert obj.booking_ids == [101]
    assert obj.lines[0]["category"] == 70
