"""Wettbewerbsergebnisse auf der Webseite (Wettbewerbe Schritt 5, Konzept Abschnitt 10.2).

Je Wettbewerb entscheidet die Einheit, ob und wann er erscheint (nicht, live während des
Wettbewerbs, nach Abschluss) und wie viel (nur Wertung der Untereinheiten und Mannschaften,
Plätze 1 bis 3 mit Namen, ganze Rangliste). Namen stehen im Namensformat der Webseite.

Einwilligung: Kategorie „Wettbewerbsergebnisse“ mit Widerspruch (wie Würden). Wer
widerspricht, erscheint „ohne Namen“, der Platz bleibt. Unter 18 am Wettbewerbstag nur mit
ausdrücklicher Einwilligung (Kategorie „Ergebnisse unter 18“). Gäste (keine Mitglieder)
erscheinen mit Namen im Namensformat und ihrem Verein: Wer bei einem öffentlichen
Wettbewerb antritt, tritt öffentlich an.
"""

from __future__ import annotations

import hmac

from .models import PublicationConsent

Category = PublicationConsent.Category
WITHOUT_NAME = "ohne Namen"
MODULE = "competitions"
# Live-Ansicht: so oft fragt die Seite im Browser nach (Ralf 2026-11-01)
POLL_SECONDS = 15


def enabled(site) -> bool:
    return (
        not site.is_unit
        and MODULE in (site.org.enabled_modules or [])
        and site.site.block_on("results")
    )


def _published(site):
    from competitions.models import Competition

    S, W = Competition.Status, Competition.Website
    qs = Competition.objects.filter(organization=site.org).exclude(website=W.OFF)
    out = []
    for c in qs.order_by("-date", "-pk"):
        if c.status == S.FINAL or (c.website == W.LIVE and c.status != S.PREPARATION):
            out.append(c)
    return out


def published(site) -> list:
    """Veröffentlichte Wettbewerbe, neueste zuerst (je Abruf einmal ermittelt)."""
    if not enabled(site):
        return []
    if getattr(site, "_results", None) is None:
        site._results = _published(site)
    return site._results


def available(site) -> bool:
    return bool(published(site)) or bool(series_list(site)) or bool(trophies(site))


def find(site, token: str):
    for c in published(site):
        if hmac.compare_digest(site.token("competition", c.pk), token):
            return c
    return None


def _split(name: str) -> tuple[str, str]:
    parts = (name or "").strip().rsplit(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], "")


def _age_on(birth, on) -> int | None:
    if not birth:
        return None
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


class Names:
    """Namen der Starter eines Wettbewerbs, wie sie auf der Webseite erscheinen dürfen."""

    def __init__(self, site, comp):
        from competitions.models import Starter

        from .public import format_name

        self.site = site
        self.comp = comp
        self._format = format_name
        self.starters = {
            s.pk: s
            for s in Starter.objects.filter(competition=comp).select_related(
                "membership__person", "unit"
            )
        }

    def of_starter(self, pk) -> str:
        s = self.starters.get(pk)
        if s is None:
            return WITHOUT_NAME
        return self.of(s.membership, s.name)

    def of(self, membership, fallback: str) -> str:
        fmt = self.site.site.name_format
        if membership is None:
            first, last = _split(fallback)
            return self._format(first, last, fmt) or WITHOUT_NAME
        person = membership.person
        active = self.site.consents.get(membership.pk, set())
        if Category.RESULTS in active:
            return WITHOUT_NAME
        age = _age_on(person.birth_date, self.comp.date)
        if age is not None and age < 18 and Category.RESULTS_MINOR not in active:
            return WITHOUT_NAME
        return self._format(person.first_name, person.last_name, fmt) or WITHOUT_NAME

    def club(self, pk) -> str:
        s = self.starters.get(pk)
        return s.club if s and s.is_guest else ""


def _state(comp) -> dict:
    from competitions.models import Competition

    S = Competition.Status
    return {
        "status": comp.status,
        "live": comp.status == S.RUNNING,
        "provisional": comp.status == S.PROVISIONAL,
        "final": comp.status == S.FINAL,
    }


def summary(site, comp) -> dict:
    return {
        "id": site.token("competition", comp.pk),
        "title": comp.title,
        "date": comp.date.isoformat(),
        "year": comp.date.year,
        "occasion": comp.occasion,
        "discipline": comp.discipline,
        "location": comp.location,
        "own": comp.own,
        "organizer": comp.organizer if not comp.own else "",
        **_state(comp),
        "url": site.url(f"results/{site.token('competition', comp.pk)}/"),
    }


def _row(names: Names, r: dict, kind: str, depth: str) -> dict:
    out = {
        "place": r.get("place"),
        "value": r.get("value_text", ""),
        "prize": bool(r.get("prize")),
    }
    if kind in ("einheit", "mannschaft"):
        out["name"] = r.get("name", "")
        if kind == "mannschaft" and depth == "alle":
            out["members"] = r.get("members", [])
        if r.get("reason"):
            out["note"] = r["reason"]
        return out
    out["name"] = names.of_starter(r.get("starter"))
    out["unit"] = r.get("unit_name", "")
    club = names.club(r.get("starter"))
    if club:
        out["club"] = club
    if r.get("out_of_competition"):
        out["out_of_competition"] = True
    if r.get("note"):
        out["note"] = r["note"]
    return out


def detail(site, comp) -> dict:
    """Rangliste eines Wettbewerbs für die Webseite (nach Umfang und Einwilligungen)."""
    from competitions import services
    from competitions.models import AwardGrant, Competition

    depth = comp.website_depth
    names = Names(site, comp)
    data = services.standings(comp)
    scorings = []
    for s in data.get("scorings", []):
        kind = s["kind"]
        team = kind in ("einheit", "mannschaft")
        if depth == Competition.WebsiteDepth.UNITS and not team:
            continue
        rows = [r for r in s["rows"] if r.get("place") is not None or r.get("value_text")]
        if not team and depth == Competition.WebsiteDepth.TOP3:
            rows = [r for r in rows if r.get("place") is not None and r["place"] <= 3]
        scorings.append(
            {
                "name": s["name"],
                "kind": kind,
                "field": len([r for r in s["rows"] if r.get("place") is not None])
                or s.get("field_size"),
                "rows": [_row(names, r, kind, depth) for r in rows],
                "complete": not (not team and depth == Competition.WebsiteDepth.TOP3),
            }
        )
    prizes = []
    if comp.form == Competition.Form.BIRD:
        for p in comp.prizes.select_related("winner__membership__person", "winner__unit"):
            entry = {"name": p.name, "fallen": p.fallen, "award": p.award}
            if p.fallen:
                if p.winner_id:
                    entry["unit"] = p.winner.unit.name if p.winner.unit_id else ""
                    if depth != Competition.WebsiteDepth.UNITS:
                        entry["winner"] = names.of(p.winner.membership, p.winner.name)
                elif depth != Competition.WebsiteDepth.UNITS:
                    entry["winner"] = names.of(None, p.winner_name)
                if p.shot_number:
                    entry["shot"] = p.shot_number
            prizes.append(entry)
    titles = []
    if comp.status == Competition.Status.FINAL:
        for g in AwardGrant.objects.filter(competition=comp).select_related(
            "membership__person", "trophy"
        ):
            if not (g.title or g.trophy_id):
                continue
            if g.unit_id:
                who = g.name
            elif depth == Competition.WebsiteDepth.UNITS:
                continue
            else:
                who = names.of(g.membership, g.name)
            titles.append(
                {"title": g.full_title or (g.trophy.name if g.trophy_id else ""), "name": who}
            )
    return {
        **summary(site, comp),
        "description": comp.description,
        "details": comp.details,
        "depth": depth,
        "scorings": scorings,
        "prizes": prizes,
        "titles": titles,
        "version": services.version(comp),
        "poll_seconds": POLL_SECONDS if comp.status != Competition.Status.FINAL else None,
        "version_url": site.url(f"results/{site.token('competition', comp.pk)}/version/"),
    }


def version(site, comp) -> dict:
    from competitions import services
    from competitions.models import Competition

    return {
        "version": services.version(comp),
        "status": comp.status,
        "final": comp.status == Competition.Status.FINAL,
    }


def series_list(site) -> list:
    from competitions.models import Series

    if not enabled(site):
        return []
    return [
        {
            "id": site.token("series", s.pk),
            "name": s.name,
            "url": site.url(f"results/series/{site.token('series', s.pk)}/"),
        }
        for s in Series.objects.filter(organization=site.org, on_website=True)
        if s.competitions.filter(status="endgueltig").exclude(website="aus").exists()
        or s.grants.filter(manual=True).exists()
    ]


def find_series(site, token: str):
    from competitions.models import Series

    if not enabled(site):
        return None
    for s in Series.objects.filter(organization=site.org, on_website=True):
        if hmac.compare_digest(site.token("series", s.pk), token):
            return s
    return None


def series_detail(site, series) -> dict:
    """Archiv einer Reihe: Sieger je Jahr (nur endgültige, veröffentlichte Wettbewerbe) und
    Titel über alle Jahre, mit den Namensregeln der Webseite."""
    from competitions.models import AwardGrant, Competition

    S, D = Competition.Status, Competition.WebsiteDepth
    years = []
    comps = (
        Competition.objects.filter(series=series, status=S.FINAL)
        .exclude(website=Competition.Website.OFF)
        .order_by("-date", "-pk")
    )
    for comp in comps:
        d = detail(site, comp)
        winners = []
        for s in d["scorings"]:
            first = [r for r in s["rows"] if r.get("place") == 1]
            if first:
                winners.append(
                    {
                        "scoring": s["name"],
                        "names": [r["name"] for r in first],
                        "value": first[0]["value"],
                    }
                )
        for p in d["prizes"]:
            if p.get("fallen"):
                winners.append(
                    {
                        "scoring": p["name"],
                        "names": [p.get("winner") or p.get("unit", "")],
                        "value": "",
                    }
                )
        years.append(
            {
                "year": comp.date.year,
                "title": comp.title,
                "url": d["url"],
                "winners": winners,
                "depth": comp.website_depth,
            }
        )
    titles = []
    names_cache: dict[int, Names] = {}
    for g in AwardGrant.objects.filter(series=series).select_related(
        "membership__person", "competition", "trophy"
    ):
        if not (g.title or g.trophy_id):
            continue
        comp = g.competition
        if comp is not None and (comp.website == Competition.Website.OFF or comp.status != S.FINAL):
            continue
        if g.unit_id:
            who = g.name
        elif comp is not None and comp.website_depth == D.UNITS:
            continue
        else:
            if comp is not None:
                names = names_cache.setdefault(comp.pk, Names(site, comp))
            else:
                names = _ManualNames(site, g.year)
            who = names.of(g.membership, g.name)
        titles.append({"year": g.year, "title": g.full_title or g.trophy.name, "name": who})
    return {
        "id": site.token("series", series.pk),
        "name": series.name,
        "description": series.description,
        "years": years,
        "titles": titles,
    }


class _ManualNames(Names):
    """Von Hand nachgetragene Jahre: Einwilligungen wie sonst, Alter zum 31.12. des Jahres."""

    def __init__(self, site, year: int):
        import datetime

        from .public import format_name

        self.site = site
        self._format = format_name
        self.starters = {}

        class _C:
            date = datetime.date(year, 12, 31)

        self.comp = _C()


def trophies(site) -> list:
    from competitions.awards import trophy_holders
    from competitions.models import Competition, Trophy

    if not enabled(site):
        return []
    out = []
    for tr in Trophy.objects.filter(organization=site.org, on_website=True):
        holders = []
        for h in trophy_holders(tr):
            if h["competition"]:
                comp = Competition.objects.filter(pk=h["competition"]).first()
                if comp is None or comp.website == "aus" or comp.status != "endgueltig":
                    continue
            holders.append(h)
        if not holders:
            continue
        from members.models import Membership

        rows = []
        for h in holders:
            if h["unit"]:
                name = h["name"]
            else:
                m = (
                    Membership.objects.select_related("person").filter(pk=h["membership"]).first()
                    if h["membership"]
                    else None
                )
                name = _ManualNames(site, h["year"]).of(m, h["name"])
            rows.append({"year": h["year"], "name": name, "kept": h["kept"]})
        out.append({"name": tr.name, "description": tr.description, "holders": rows})
    return out


def overview(site) -> dict:
    comps = published(site)
    return {
        "competitions": [summary(site, c) for c in comps],
        "series": series_list(site),
        "trophies": trophies(site),
        "poll_seconds": POLL_SECONDS,
    }


def home(site, limit: int = 3) -> list:
    """Startseite „Aktuelle Ergebnisse“: die neuesten Wettbewerbe mit ihren Siegern."""
    out = []
    for comp in published(site)[:limit]:
        d = detail(site, comp)
        winners = []
        for s in d["scorings"]:
            top = [r for r in s["rows"] if r.get("place") is not None and r["place"] <= 3]
            winners.append({"scoring": s["name"], "rows": top})
        out.append(
            {
                **summary(site, comp),
                "scorings": winners,
                "prizes": [p for p in d["prizes"] if p.get("fallen")],
                "version": d["version"],
            }
        )
    return out
