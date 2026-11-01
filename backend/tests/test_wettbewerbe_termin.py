"""Wettbewerb und Termin im Kalender, Zusagen als Starter, volle Seiten bei den
Papierlisten (Ralf 2026-11-01; alles erfunden)."""

import datetime

import pytest
from django.utils import timezone

from competitions import report
from competitions.models import Competition
from events.models import Event, EventResponse

from .factories import give_role, make_user
from .test_wettbewerbe import club, schuetzen, url, zuege  # noqa: F401


@pytest.fixture
def kalender(club):  # noqa: F811
    club.enabled_modules = [*club.enabled_modules, "events"]
    club.save()
    return club


def _termin(org, title="Osterschießen", day=datetime.date(2027, 4, 4), **extra):
    start = timezone.make_aware(datetime.datetime.combine(day, datetime.time(14, 0)))
    return Event.objects.create(
        organization=org,
        title=title,
        location="Schießstand am Deich",
        description="Für alle Züge",
        starts_at=start,
        ends_at=start + datetime.timedelta(hours=4),
        **extra,
    )


@pytest.mark.django_db
class TestTermin:
    def test_bestehenden_termin_waehlen(self, kalender, orgs, board_a, api):
        c = api(board_a)
        termin = _termin(kalender, rsvp_enabled=True)
        _termin(kalender, "Vorstandssitzung", visibility=Event.Visibility.BOARD)
        _termin(kalender, "Schützenfest", day=datetime.date(2027, 8, 20))
        resp = c.get(url(kalender, "event-candidates/?datum=2027-04-01"))
        assert resp.status_code == 200, resp.content
        assert resp.json()["on"] and resp.json()["can_create"]
        titles = [e["title"] for e in resp.json()["events"]]
        assert "Osterschießen" in titles and "Schützenfest" not in titles
        assert "Vorstandssitzung" in titles  # der Vorstand sieht auch Vorstandstermine
        resp = c.get(url(kalender, "event-candidates/?suche=fest"))
        assert [e["title"] for e in resp.json()["events"]] == ["Schützenfest"]

        resp = c.post(
            url(kalender),
            {
                "title": "Osterschießen",
                "date": "2027-04-04",
                "template": "schiessen",
                "event": termin.pk,
            },
            "application/json",
        )
        assert resp.status_code == 201, resp.content
        detail = c.get(url(kalender, f"{resp.json()['id']}/")).json()
        assert detail["event"] == termin.pk
        assert detail["event_info"]["title"] == "Osterschießen"
        assert detail["event_info"]["time"] == "14:00"
        assert detail["location"] == "Schießstand am Deich"
        assert detail["description"] == "Für alle Züge"
        assert detail["calendar"] == {"on": True, "can_create": True}
        # Lösen und wieder zuordnen
        link = url(kalender, f"{detail['id']}/event/")
        resp = c.post(link, {"event": None}, "application/json")
        assert resp.status_code == 200 and resp.json()["event"] is None
        resp = c.post(link, {"event": termin.pk}, "application/json")
        assert resp.json()["event"]["id"] == termin.pk
        # Termin eines anderen Vereins oder eine Serie: nicht wählbar
        fremd = _termin(orgs["b"])
        serie = _termin(kalender, "Training", repeat=Event.Repeat.WEEKLY)
        for pk in (fremd.pk, serie.pk):
            assert c.post(link, {"event": pk}, "application/json").status_code == 400

    def test_termin_aus_wettbewerb_anlegen(self, kalender, board_a, api):
        c = api(board_a)
        resp = c.post(
            url(kalender),
            {
                "title": "Pokalschießen 2027",
                "date": "2027-05-09",
                "location": "Vereinsheim",
                "template": "einfach",
                "create_event": True,
            },
            "application/json",
        )
        assert resp.status_code == 201, resp.content
        comp = Competition.objects.get(pk=resp.json()["id"])
        event = comp.event
        assert event.title == "Pokalschießen 2027" and event.location == "Vereinsheim"
        assert event.all_day and event.visibility == Event.Visibility.MEMBERS
        assert timezone.localtime(event.starts_at).date() == datetime.date(2027, 5, 9)
        assert event.ends_at == event.starts_at
        # Später: ein zweiter Termin wird abgelehnt
        link = url(kalender, f"{comp.pk}/event/")
        assert c.post(link, {"create": True}, "application/json").status_code == 400

    def test_ohne_terminrecht_kein_neuer_termin(self, kalender, api):
        meister = make_user("meister@example.org")
        give_role(meister, kalender, ["competitions.manage"], name="Schießmeister")
        c = api(meister)
        resp = c.post(
            url(kalender),
            {"title": "Pokalschießen", "date": "2027-05-09", "create_event": True},
            "application/json",
        )
        assert resp.status_code == 403
        assert not Competition.objects.filter(title="Pokalschießen").exists()
        resp = c.post(url(kalender), {"title": "Pokalschießen", "date": "2027-05-09"})
        detail = c.get(url(kalender, f"{resp.json()['id']}/")).json()
        assert detail["calendar"] == {"on": True, "can_create": False}

    def test_zusagen_als_starter(self, kalender, schuetzen, board_a, api):  # noqa: F811
        c = api(board_a)
        termin = _termin(kalender, rsvp_enabled=True)
        for first, status in (("Max", "yes"), ("Erika", "yes"), ("Otto", "no")):
            EventResponse.objects.create(
                organization=kalender,
                event=termin,
                membership=schuetzen[first],
                status=status,
                source="member",
            )
        resp = c.post(
            url(kalender),
            {"title": "Osterschießen", "date": "2027-04-04", "event": termin.pk},
            "application/json",
        )
        comp_id = resp.json()["id"]
        c.post(url(kalender, f"{comp_id}/starters/"), {"name": "Gerd Gast"}, "application/json")
        c.post(
            url(kalender, f"{comp_id}/starters/"),
            {"membership": schuetzen["Max"].pk},
            "application/json",
        )
        resp = c.post(url(kalender, f"{comp_id}/starters/from-event/"))
        assert resp.status_code == 200, resp.content
        assert resp.json() == {"added": 1, "already": 1}
        names = sorted(s["name"] for s in c.get(url(kalender, f"{comp_id}/starters/")).json())
        assert names == ["Erika Beispiel", "Gerd Gast", "Max Muster"]


@pytest.mark.django_db
class TestVolleSeiten:
    def test_leere_schiessliste_genau_eine_seite(self, club):  # noqa: F811
        comp = Competition.objects.create(
            organization=club, title="Osterschießen", date=datetime.date(2027, 4, 4)
        )
        assert _count(report.shooting_list(comp, empty=True)) == 1

    def test_letzte_seite_wird_aufgefuellt(self, club):  # noqa: F811
        from reportlab.platypus import Spacer

        comp = Competition.objects.create(
            organization=club, title="Osterschießen", date=datetime.date(2027, 4, 4)
        )
        used = []

        def story(blank):
            used.append(blank)
            return [Spacer(1, 30) for _ in range(40 + blank)]  # 30 pt je Zeile

        pdf = report._filled(comp, "Test", story, 3)  # noqa: SLF001
        best = used[-1]
        pages = _count(pdf)
        assert best >= 3 and pages == report._build(comp, "T", story(3))[1]  # noqa: SLF001
        assert report._build(comp, "T", story(best + 1))[1] == pages + 1  # noqa: SLF001


def _count(pdf: bytes) -> int:
    import re

    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


@pytest.mark.django_db
class TestSchiesslisteNachZug:
    """Ralf 2026-11-01: je Zug eine eigene Tabelle mit Feldern für die Zugwertung."""

    def _texts(self, flowables) -> list[str]:
        from reportlab.platypus import KeepTogether, Paragraph, Table

        out = []
        for f in flowables:
            if isinstance(f, KeepTogether):
                out += self._texts(f._content)  # noqa: SLF001
            elif isinstance(f, Paragraph):
                out.append(f.text)
            elif isinstance(f, Table):
                for row in f._cellvalues:  # noqa: SLF001
                    out += [c for c in row if isinstance(c, str) and c]
                    out += self._texts([c for c in row if not isinstance(c, str)])
        return out

    def test_je_zug_eine_tabelle(self, club, monkeypatch):  # noqa: F811
        from competitions.models import Score, Scoring, Starter
        from organizations.models import Department

        zug1 = Department.objects.create(organization=club, parent=club, name="Zug Eins")
        zug2 = Department.objects.create(organization=club, parent=club, name="Zug Zwei")
        comp = Competition.objects.create(
            organization=club, title="Osterschießen", date=datetime.date(2027, 4, 4)
        )
        einzel = Scoring.objects.create(organization=club, competition=comp, name="Einzel", shots=3)
        Scoring.objects.create(
            organization=club,
            competition=comp,
            name="Zugwertung",
            kind=Scoring.Kind.UNIT,
            source=einzel,
            team_mode="beste",
            team_size=2,
            sort_order=1,
        )
        for name, unit, value in (
            ("Max Muster", zug1, 28),
            ("Otto Normal", zug1, 19),
            ("Erika Beispiel", zug2, None),
            ("Gerd Gast", None, 24),
        ):
            s = Starter.objects.create(organization=club, competition=comp, name=name, unit=unit)
            if value is not None:
                Score.objects.create(organization=club, scoring=einzel, starter=s, value=value)
        stories = []
        real = report._filled  # noqa: SLF001

        def spy(comp, title, make_story, least, **kw):
            stories.append(make_story(least))
            return real(comp, title, make_story, least, **kw)

        monkeypatch.setattr(report, "_filled", spy)
        pdf = report.shooting_list(comp, order="einheit")
        assert pdf.startswith(b"%PDF")
        texts = self._texts(stories[0])
        i1, i2 = texts.index("<b>Zug Eins</b>"), texts.index("<b>Zug Zwei</b>")
        guests = texts.index("<b>Gäste und ohne Einheit</b>")
        assert i1 < texts.index("Max Muster") < i2 < texts.index("Erika Beispiel") < guests
        assert guests < texts.index("Gerd Gast")
        # Zugwertung je Zug: Felder für die besten 2, Summe und Platz
        assert texts.count("<b>Zugwertung</b><br/>Summe der besten 2") == 2
        assert texts.count("<b>2.</b>") == 2 and texts.count("<b>Platz</b>") == 2
        # erfasste Werte stehen drin: Einzel und Zugwertung von Zug Eins (28 + 19 = 47, Platz 1)
        assert {"28", "19", "24", "47"} <= set(texts) and "1" in texts
        # leere Liste nach Zug: auch je Zug eine Tabelle
        stories.clear()
        report.shooting_list(comp, order="einheit", empty=True)
        texts = self._texts(stories[0])
        assert "<b>Zug Zwei</b>" in texts and "Max Muster" not in texts and "28" not in texts

    def test_nach_name_mit_werten(self, club):  # noqa: F811
        from competitions.models import Score, Scoring, Starter

        comp = Competition.objects.create(
            organization=club, title="Osterschießen", date=datetime.date(2027, 4, 4)
        )
        einzel = Scoring.objects.create(organization=club, competition=comp, name="Einzel")
        s = Starter.objects.create(organization=club, competition=comp, name="Peter Probe")
        Score.objects.create(organization=club, scoring=einzel, starter=s, value=28)
        assert report.shooting_list(comp).startswith(b"%PDF")
