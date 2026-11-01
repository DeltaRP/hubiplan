"""Meldungen Schritt 1: Ausschreibung selbst erfassen, Mannschaften melden, Meldewege,
Fassungen und Änderungsmeldungen, fremder Wettbewerb aus der Meldung (alles erfunden).

Leitszenario (Ralf, 2026-11-01): Der Verein meldet zum Vergleichsschießen des
Dachverbands zwei Mannschaften mit je fünf Schützen, bisher per Brief.
"""

import datetime

import pytest
from django.utils import timezone

from competitions.models import Competition, Starter, Team, TeamMember
from entries import services
from entries.models import Entry, EntryVersion

from .factories import give_role, make_member, make_user

pytestmark = pytest.mark.django_db


def url(org, rest=""):
    return f"/api/orgs/{org.pk}/entries/{rest}"


@pytest.fixture
def club(orgs):
    org = orgs["a"]
    org.enabled_modules = ["members", "competitions", "entries"]
    org.short_name = "Hubertus"
    org.save()
    return org


@pytest.fixture
def schuetzen(club):
    names = [
        ("Max", "Muster"),
        ("Erika", "Beispiel"),
        ("Otto", "Normal"),
        ("Jürgen", "Müller"),
        ("Anna", "Schmidt"),
        ("Paul", "Weber"),
        ("Lena", "Kraus"),
        ("Karl", "Klein"),
        ("Ida", "Groß"),
        ("Tom", "Lang"),
        ("Uwe", "Kurz"),
    ]
    return {first: make_member(club, first, last) for first, last in names}


def _call(c, club, **extra):
    data = {
        "title": "Vergleichsschießen 2027",
        "organizer": "Testbund e. V.",
        "organizer_address": "Schützenweg 1\n12345 Musterstadt",
        "organizer_email": "meldung@testbund.example.org",
        "date": "2027-06-12",
        "deadline": "2027-05-31",
        "location": "Musterstadt",
        "template": "mannschaften",
        **extra,
    }
    resp = c.post(url(club, "calls/"), data, "application/json")
    assert resp.status_code == 201, resp.content
    return resp.json()


def _post(c, path, data):
    resp = c.post(path, data, "application/json")
    assert resp.status_code in (200, 201), resp.content
    return resp.json()


def _patch(c, path, data):
    resp = c.patch(path, data, "application/json")
    assert resp.status_code == 200, resp.content
    return resp.json()


def _mannschaften(c, club, call, schuetzen, names):
    """Zwei Mannschaften mit je fünf Schützen."""
    block = call["blocks"][0]["id"]
    base = url(club, f"calls/{call['id']}/entry/")
    entry = _post(c, f"{base}teams/", {"block": block})
    entry = _post(c, f"{base}teams/", {"block": block})
    teams = entry["teams"]
    for i, first in enumerate(names):
        entry = _post(
            c,
            f"{base}persons/",
            {
                "block": block,
                "team": teams[i // 5]["id"],
                "membership": schuetzen[first].pk,
            },
        )
    return entry


ZEHN = ["Max", "Erika", "Otto", "Jürgen", "Anna", "Paul", "Lena", "Karl", "Ida", "Tom"]


class TestZugriff:
    def test_modul_aus(self, orgs, board_a, api):
        orgs["a"].enabled_modules = ["members"]
        orgs["a"].save()
        assert api(board_a).get(url(orgs["a"], "calls/")).status_code == 404

    def test_ohne_recht(self, club, api):
        user = make_user("kassierer@example.org")
        give_role(user, club, ["finance.view"], name="Kassierer")
        assert api(user).get(url(club, "calls/")).status_code == 403

    def test_mitglieder_waehlen_braucht_mitgliederrecht(self, club, schuetzen, api):
        user = make_user("melder@example.org")
        give_role(user, club, ["entries.submit"], name="Melder")
        c = api(user)
        call = _call(c, club)
        resp = c.get(url(club, f"calls/{call['id']}/candidates/?suche=Muster"))
        assert resp.status_code == 403
        base = url(club, f"calls/{call['id']}/entry/")
        entry = _post(c, f"{base}teams/", {"block": call["blocks"][0]["id"]})
        resp = c.post(
            f"{base}persons/",
            {
                "block": call["blocks"][0]["id"],
                "team": entry["teams"][0]["id"],
                "membership": schuetzen["Max"].pk,
            },
            "application/json",
        )
        assert resp.status_code == 403
        # Gäste gehen ohne Mitgliederrecht
        _post(
            c,
            f"{base}persons/",
            {
                "block": call["blocks"][0]["id"],
                "team": entry["teams"][0]["id"],
                "name": "Gerd Gast",
                "club": "SV Nachbarort",
            },
        )


class TestAblauf:
    def test_zwei_mannschaften_per_brief_mit_ersatz(self, club, schuetzen, board_a, api):
        c = api(board_a)
        call = _call(
            c,
            club,
            person_fields=["birth_year", "member_number"],
            conditions={"active": True, "min_age": 16},
        )
        block = call["blocks"][0]["id"]
        _patch(
            c,
            url(club, f"calls/{call['id']}/blocks/{block}/"),
            {
                "settings": {
                    "min_teams": 1,
                    "max_teams": 2,
                    "min_size": 5,
                    "max_size": 5,
                    "substitutes": 1,
                    "positions": ["Mannschaftsführer"],
                }
            },
        )
        entry = _mannschaften(c, club, call, schuetzen, ZEHN)
        assert [t["name"] for t in entry["teams"]] == ["Hubertus I", "Hubertus II"]
        assert entry["status"] == "entwurf" and entry["hints"] == []
        # Vorschau als Brief und Tabelle
        base = url(club, f"calls/{call['id']}/entry/")
        pdf = c.get(f"{base}preview/?als=pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

        entry = _post(c, f"{base}submit/", {"channel": "brief"})
        assert entry["status"] == "abgegeben" and len(entry["versions"]) == 1
        v1 = entry["versions"][0]
        assert v1["kind"] == "meldung" and v1["channel"] == "brief"
        assert v1["signed_by"]  # Unterzeichner aus dem Konto

        # Fremder Wettbewerb mit beiden Mannschaften und zehn Startern
        comp = Competition.objects.get(pk=entry["competition"])
        assert not comp.own and comp.organizer == "Testbund e. V."
        assert comp.date == datetime.date(2027, 6, 12)
        assert list(Team.objects.filter(competition=comp).values_list("name", flat=True)) == [
            "Hubertus I",
            "Hubertus II",
        ]
        assert Starter.objects.filter(competition=comp).count() == 10
        team1 = Team.objects.get(competition=comp, name="Hubertus I")
        assert TeamMember.objects.filter(team=team1).count() == 5

        # Ersatz: Uwe schießt statt Max; derselbe Platz, derselbe Starter
        max_person = next(p for p in entry["persons"] if p["name"] == "Max Muster")
        entry = _patch(c, f"{base}persons/{max_person['id']}/", {"membership": schuetzen["Uwe"].pk})
        assert entry["changed"] is True
        entry = _post(c, f"{base}submit/", {"channel": "brief"})
        v2 = entry["versions"][1]
        assert v2["kind"] == "aenderung"
        assert v2["changes"] == ["In Hubertus I: Uwe Kurz statt Max Muster."]
        starter = Starter.objects.get(competition=comp, membership=schuetzen["Uwe"])
        assert starter.name == "Uwe Kurz"
        assert Starter.objects.filter(competition=comp).count() == 10

        # Belege: Brief, Excel, CSV
        for fmt, start in (("pdf", b"%PDF"), ("xlsx", b"PK"), ("csv", b"\xef\xbb\xbf")):
            resp = c.get(f"{base}versions/2/?als={fmt}")
            assert resp.status_code == 200 and resp.content.startswith(start)
        csv_text = c.get(f"{base}versions/1/?als=csv").content.decode("utf-8-sig")
        assert "Max Muster" in csv_text and "Mitgliedsnummer" in csv_text

        # Ohne Änderung keine weitere Fassung
        resp = c.post(f"{base}submit/", {"channel": "brief"}, "application/json")
        assert resp.status_code == 400

        # Bestätigung vermerken
        entry = _post(c, f"{base}confirm/", {"note": "per Mail am 02.06."})
        assert entry["status"] == "bestaetigt"

    def test_email_an_veranstalter_mit_kopie(
        self, club, schuetzen, board_a, api, mailoutbox, django_capture_on_commit_callbacks
    ):
        c = api(board_a)
        call = _call(c, club)
        _mannschaften(c, club, call, schuetzen, ZEHN)
        base = url(club, f"calls/{call['id']}/entry/")
        with django_capture_on_commit_callbacks(execute=True):
            _post(c, f"{base}submit/", {"channel": "email"})
        mails = [m for m in mailoutbox if m.extra_headers.get("X-Hubiplan-Kind") == "meldung"]
        assert [m.to for m in mails] == [
            ["meldung@testbund.example.org"],
            ["vorstand-a@example.org"],
        ]
        assert mails[0].subject.startswith("Meldung zu Vergleichsschießen 2027")
        assert mails[0].reply_to == ["vorstand-a@example.org"]
        name, content, mime = mails[0].attachments[0]
        assert name.endswith(".pdf") and content.startswith(b"%PDF")

    def test_zurueckziehen(self, club, schuetzen, board_a, api):
        c = api(board_a)
        call = _call(c, club)
        _mannschaften(c, club, call, schuetzen, ZEHN)
        base = url(club, f"calls/{call['id']}/entry/")
        _post(c, f"{base}submit/", {"channel": "sonstiges", "sent_to": "persönlich"})
        entry = _post(
            c,
            f"{base}submit/",
            {"channel": "brief", "withdraw": True, "reason": "Stand ist belegt"},
        )
        assert entry["status"] == "zurueckgezogen"
        assert entry["versions"][-1]["kind"] == "rueckzug"
        resp = c.post(f"{base}teams/", {"block": call["blocks"][0]["id"]}, "application/json")
        assert resp.status_code == 400


class TestHinweise:
    def test_bedingungen_nur_als_warnung(self, club, schuetzen, board_a, api):
        jung = make_member(club, "Finn", "Jung", birth_date=datetime.date(2015, 3, 1))
        alt = make_member(club, "Gustav", "Ehemalig")
        from members.models import MembershipPeriod

        MembershipPeriod.objects.filter(membership=alt).update(
            exit_date=datetime.date(2020, 12, 31)
        )
        c = api(board_a)
        call = _call(c, club, conditions={"active": True, "min_age": 16, "guests": False})
        block = call["blocks"][0]["id"]
        _patch(
            c,
            url(club, f"calls/{call['id']}/blocks/{block}/"),
            {"settings": {"min_size": 5, "max_size": 5, "max_teams": 1}},
        )
        base = url(club, f"calls/{call['id']}/entry/")
        entry = _post(c, f"{base}teams/", {"block": block})
        team = entry["teams"][0]["id"]
        _post(c, f"{base}persons/", {"block": block, "team": team, "membership": jung.pk})
        _post(c, f"{base}persons/", {"block": block, "team": team, "membership": alt.pk})
        entry = _post(c, f"{base}persons/", {"block": block, "team": team, "name": "Gerd Gast"})
        texts = [h["text"] for h in entry["hints"]]
        assert "Hubertus I: 3 von mindestens 5 Personen." in texts
        assert any(t.startswith("Finn Jung: Mindestalter 16") for t in texts)
        assert any(t.startswith("Gustav Ehemalig ist am 12.06.2027 kein aktives") for t in texts)
        assert "Gerd Gast: Gäste sind nicht vorgesehen." in texts
        # Abgeben trotzdem möglich (Frage 4: nur Warnung)
        entry = _post(c, f"{base}submit/", {"channel": "brief"})
        assert entry["status"] == "abgegeben"

    def test_komplette_mitgliederliste_mit_ausgetretenen(self, club, schuetzen, board_a, api):
        alt = make_member(club, "Gustav", "Ehemalig")
        from members.models import MembershipPeriod

        MembershipPeriod.objects.filter(membership=alt).update(
            exit_date=datetime.date(2020, 12, 31)
        )
        c = api(board_a)
        call = _call(c, club)
        found = c.get(url(club, f"calls/{call['id']}/candidates/?suche=Ehemalig")).json()
        assert found == []
        found = c.get(url(club, f"calls/{call['id']}/candidates/?suche=Ehemalig&alle=1")).json()
        assert [f["name"] for f in found] == ["Gustav Ehemalig"]
        found = c.get(url(club, f"calls/{call['id']}/candidates/?suche=muell")).json()
        assert [f["name"] for f in found] == ["Jürgen Müller"]


class TestMeldeschluss:
    def test_nach_meldeschluss_nur_ersatz(self, club, schuetzen, board_a, api):
        c = api(board_a)
        gestern = (timezone.localdate() - datetime.timedelta(days=1)).isoformat()
        call = _call(c, club, deadline=gestern, date=None)
        entry = _mannschaften(c, club, call, schuetzen, ZEHN)
        base = url(club, f"calls/{call['id']}/entry/")
        _post(c, f"{base}submit/", {"channel": "brief"})
        resp = c.post(f"{base}teams/", {"block": call["blocks"][0]["id"]}, "application/json")
        assert resp.status_code == 400
        person = entry["persons"][0]
        resp = c.delete(f"{base}persons/{person['id']}/")
        assert resp.status_code == 400
        _patch(c, f"{base}persons/{person['id']}/", {"membership": schuetzen["Uwe"].pk})


class TestKopierenUndKuerzen:
    def test_kopie_fuer_das_naechste_jahr(self, club, board_a, api):
        c = api(board_a)
        call = _call(c, club)
        new = _post(c, url(club, f"calls/{call['id']}/copy/"), {})
        assert new["title"] == "Vergleichsschießen 2028"
        assert new["date"] == "2028-06-12" and new["deadline"] == "2028-05-31"
        assert len(new["blocks"]) == 1 and new["copied_from"] == call["id"]
        assert new["entry_status"] is None

    def test_kuerzen_nach_einem_jahr(self, club, schuetzen, board_a, api):
        c = api(board_a)
        call = _call(c, club, person_fields=["birth_date"], date="2024-06-12")
        _mannschaften(c, club, call, schuetzen, ZEHN)
        base = url(club, f"calls/{call['id']}/entry/")
        _post(c, f"{base}submit/", {"channel": "brief"})
        v = EntryVersion.objects.get(entry__call_id=call["id"])
        person = v.data["blocks"][0]["teams"][0]["persons"][0]
        assert person["details"]["birth_date"] == "17.05.1980"
        assert services.shorten_old(datetime.date(2025, 7, 1)) == 1
        v.refresh_from_db()
        person = v.data["blocks"][0]["teams"][0]["persons"][0]
        assert person["details"] == {} and person["name"] == "Max Muster"
        assert v.data["fields"] == []
        assert services.shorten_old(datetime.date(2025, 7, 1)) == 0
        # Gekürzte Fassung bleibt als Brief lesbar
        assert c.get(f"{base}versions/1/?als=pdf").status_code == 200


class TestBausteine:
    def test_zahl_auswahl_text(self, club, board_a, api):
        c = api(board_a)
        call = _call(c, club, template="")
        base = url(club, f"calls/{call['id']}/")
        zahl = _post(c, f"{base}blocks/", {"kind": "zahl", "label": "Teilnehmer am Umzug"})
        wahl = _post(
            c,
            f"{base}blocks/",
            {"kind": "auswahl", "label": "Musik", "settings": {"options": ["ja", "nein"]}},
        )
        resp = c.post(f"{base}blocks/", {"kind": "auswahl", "label": "Leer"}, "application/json")
        assert resp.status_code == 400
        _post(c, f"{base}blocks/", {"kind": "text", "label": "Bemerkung"})
        resp = c.put(
            f"{base}entry/answers/",
            {"block": wahl["id"], "value": "vielleicht"},
            "application/json",
        )
        assert resp.status_code == 400
        c.put(f"{base}entry/answers/", {"block": zahl["id"], "value": 42}, "application/json")
        c.put(f"{base}entry/answers/", {"block": wahl["id"], "value": "ja"}, "application/json")
        entry = _post(c, f"{base}entry/submit/", {"channel": "tabelle"})
        assert entry["answers"] == {str(zahl["id"]): 42, str(wahl["id"]): "ja"}
        # Keine Personen, kein fremder Wettbewerb
        assert entry["competition"] is None
        resp = c.put(
            f"{base}entry/answers/", {"block": zahl["id"], "value": 40}, "application/json"
        )
        entry = _post(c, f"{base}entry/submit/", {"channel": "tabelle"})
        assert entry["versions"][1]["changes"] == ["Teilnehmer am Umzug: 40 statt 42."]

    def test_abgegebene_ausschreibung_nicht_loeschbar(self, club, schuetzen, board_a, api):
        c = api(board_a)
        call = _call(c, club)
        _mannschaften(c, club, call, schuetzen, ZEHN)
        _post(c, url(club, f"calls/{call['id']}/entry/submit/"), {"channel": "brief"})
        assert c.delete(url(club, f"calls/{call['id']}/")).status_code == 400
        assert Entry.objects.filter(call_id=call["id"]).exists()
