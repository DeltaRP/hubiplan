"""Fachfrage 7 (31.10.b): Auskunft je Mitglied, Löschen auf Verlangen, Löschliste
(erfundene Daten)."""
# ruff: noqa: F811  (Fixtures als Parameter)

import datetime
import io
import json
import zipfile

import pytest

from members import loeschliste
from members.models import ContactDetails, Membership
from members.workflows import purge_expired

from .test_m3_workflows import JSON, member, types, url  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _liste(settings, tmp_path):
    settings.LOESCHLISTE_PATH = str(tmp_path / "loeschliste" / "loeschliste.jsonl")


def _zip(resp) -> zipfile.ZipFile:
    assert resp.status_code == 200, resp.content[:300]
    assert resp["Content-Type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(resp.content))


def test_auskunft_nur_diese_person(api, orgs, types, member, board_a):
    c = api(board_a)
    c.patch(url(orgs, member, ""), {"city": "Neustadt"}, content_type=JSON)
    # Zweites Mitglied darf nicht in der Auskunft stehen
    other = c.post(
        f"/api/orgs/{orgs['a'].pk}/members/admit/",
        {
            "last_name": "Fremd",
            "first_name": "Otto",
            "birth_date": "1970-01-01",
            "member_type": types["a"]["aktiv"].pk,
            "entry_date": "2020-01-01",
            "email": "otto@example.org",
            "street": "x",
            "postal_code": "1",
            "city": "y",
        },
        content_type=JSON,
    )
    assert other.status_code == 201, other.json()
    zf = _zip(c.get(url(orgs, member, "auskunft/")))
    names = set(zf.namelist())
    assert {"LIESMICH.txt", "akte.json", "rechnungen.json", "mails.json", "zugang.json"} <= names
    assert {"verbund.json", "protokoll.json", "zusatzfelder.json"} <= names
    akte = json.loads(zf.read("akte.json"))
    assert akte["first_name"] == "Erika" and akte["contact"]["city"] == "Neustadt"
    everything = b"".join(zf.read(n) for n in names)
    assert b"Fremd" not in everything and b"otto@example.org" not in everything
    assert b"vorstand-a@example.org" not in everything  # keine Bearbeitenden


def test_auskunft_braucht_exportrecht(api, orgs, member):
    from .factories import give_role, make_user

    user = make_user("schrift@example.org")
    give_role(user, orgs["a"], ["members.view", "members.edit"], name="Schriftführung")
    assert api(user).get(url(orgs, member, "auskunft/")).status_code == 403


def test_loeschen_auf_verlangen_nur_nach_austritt(
    api, orgs, member, board_a, django_capture_on_commit_callbacks
):
    c = api(board_a)
    assert c.post(url(orgs, member, "erase/")).status_code == 400  # noch Mitglied
    c.post(
        url(orgs, member, "exit/"),
        {"exit_date": "2024-06-30", "exit_reason": "exit"},
        content_type=JSON,
    )
    with django_capture_on_commit_callbacks(execute=True):
        resp = c.post(url(orgs, member, "erase/"))
    assert resp.status_code == 200, resp.json()
    assert resp.json()["purged"] is True
    membership = Membership.objects.get(organization=orgs["a"])
    membership.person.refresh_from_db()
    assert membership.person.birth_year_only
    assert [e["m"] for e in loeschliste.entries()] == [membership.pk]


def test_loeschliste_nach_backup(api, orgs, member, board_a, django_capture_on_commit_callbacks):
    c = api(board_a)
    c.patch(url(orgs, member, ""), {"city": "Neustadt"}, content_type=JSON)
    c.post(
        url(orgs, member, "exit/"),
        {"exit_date": "2020-12-31", "exit_reason": "exit"},
        content_type=JSON,
    )
    with django_capture_on_commit_callbacks(execute=True):
        assert purge_expired(datetime.date(2023, 1, 1)) == 1
    assert len(loeschliste.entries()) == 1
    # „Älteres Backup eingespielt“: Daten wieder da, Löschung nicht mehr vermerkt
    membership = Membership.objects.get(organization=orgs["a"])
    Membership.objects.filter(pk=membership.pk).update(purged_at=None, club_number="4711")
    ContactDetails.objects.create(
        person=membership.person,
        organization=orgs["a"],
        scope=orgs["federation"],
        email="erika@example.org",
    )
    assert loeschliste.apply() == 1
    membership.refresh_from_db()
    assert membership.purged_at is not None and membership.club_number == ""
    assert not ContactDetails.objects.exists()
    # Zweites Anwenden ändert nichts
    assert loeschliste.apply() == 0


def test_loeschliste_wiederaufnahme_gilt(
    api, orgs, types, member, board_a, django_capture_on_commit_callbacks
):
    c = api(board_a)
    c.post(
        url(orgs, member, "exit/"),
        {"exit_date": "2015-12-31", "exit_reason": "exit"},
        content_type=JSON,
    )
    with django_capture_on_commit_callbacks(execute=True):
        purge_expired(datetime.date(2020, 1, 1))
        resp = c.post(
            url(orgs, member, "reentry/"),
            {
                "entry_date": "2024-01-01",
                "member_type": types["a"]["aktiv"].pk,
                "email": "erika@example.org",
                "street": "Neu 1",
                "postal_code": "1",
                "city": "x",
            },
            content_type=JSON,
        )
    assert resp.status_code == 200, resp.json()
    assert loeschliste.apply() == 0
    assert Membership.objects.get(organization=orgs["a"]).purged_at is None


def test_loeschliste_neue_mitgliedschaft_gleiche_nummer(orgs, member):
    """Gleiche Nummer, anderer Anlagezeitpunkt (nach dem Einspielen neu vergeben): bleibt."""
    membership = Membership.objects.get(organization=orgs["a"])
    target = loeschliste.path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "m": membership.pk,
                "o": orgs["a"].pk,
                "c": "2001-01-01T00:00:00+00:00",
                "d": True,
            }
        )
        + "\n"
    )
    assert loeschliste.apply() == 0
