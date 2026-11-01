"""Auszeichnungen und Geschichte (Konzept Abschnitte 5.4 und 12, Schritt 4).

Beim Abschluss („endgültig“) vergibt HUBIplan die eingerichteten Auszeichnungen nach den
Plätzen der Rangliste bzw. den Pfändern: Titel („Vereinsmeister 2027“), Preise,
Wanderpokale und Würdenvorschläge. Eine Würde entsteht erst, wenn der Vorstand den
Vorschlag bestätigt (``honors.Reign``). Verlässt der Wettbewerb „endgültig“ wieder
(Korrektur), fallen die noch nicht entschiedenen Vergaben weg und entstehen beim nächsten
Abschluss neu.
"""

from __future__ import annotations

from django.db import transaction
from django.utils.translation import gettext

from .models import Award, AwardGrant, Competition, Scoring, Series, Starter, Trophy

DECIDED = (AwardGrant.DignityState.CONFIRMED, AwardGrant.DignityState.REJECTED)


def _undecided(comp: Competition):
    return AwardGrant.objects.filter(competition=comp, manual=False).exclude(
        dignity_state__in=DECIDED
    )


def _rows_for(award: Award, data_by_scoring: dict) -> list[dict]:
    rows = data_by_scoring.get(award.scoring_id, {}).get("rows", [])
    return [
        r
        for r in rows
        if r.get("place") is not None and award.place_from <= r["place"] <= award.place_to
    ]


@transaction.atomic
def grant(comp: Competition) -> list[AwardGrant]:
    """Vergibt die Auszeichnungen eines endgültigen Wettbewerbs (wiederholbar)."""
    from . import services

    _undecided(comp).delete()
    kept = {
        (g.award_id, g.starter_id, g.unit_id)
        for g in AwardGrant.objects.filter(competition=comp, manual=False)
    }
    awards = list(Award.objects.filter(competition=comp).select_related("scoring", "prize__winner"))
    if not awards:
        return []
    data = services.standings(comp)
    by_scoring = {s["scoring"]: s for s in data.get("scorings", [])}
    starters = {
        s.pk: s for s in Starter.objects.filter(competition=comp).select_related("membership")
    }
    year = comp.date.year
    out = []
    for award in awards:
        targets = []  # (starter, unit_id, name, place, value_text, scoring_name)
        if award.prize_id:
            p = award.prize
            if p.fallen:
                targets.append(
                    (p.winner, None, p.winner.name if p.winner else p.winner_name, None, "", p.name)
                )
        elif award.scoring_id:
            for r in _rows_for(award, by_scoring):
                st = starters.get(r.get("starter")) if r.get("starter") else None
                unit = r.get("unit") if award.scoring.kind == Scoring.Kind.UNIT else None
                targets.append(
                    (
                        st,
                        unit,
                        r.get("name", ""),
                        r["place"],
                        r.get("value_text", ""),
                        award.scoring.name,
                    )
                )
        for st, unit_id, name, place, value_text, scoring_name in targets:
            if (award.pk, st.pk if st else None, unit_id) in kept:
                continue
            person_like = st is not None or (award.prize_id and name)
            dignity = award.dignity if (award.dignity_id and person_like and not unit_id) else None
            g = AwardGrant.objects.create(
                organization=comp.organization,
                award=award,
                competition=comp,
                series=comp.series,
                year=year,
                title=award.title,
                item=award.item,
                scoring_name=scoring_name,
                place=place,
                value_text=value_text,
                starter=st,
                membership=st.membership if st else None,
                unit_id=unit_id,
                name=(name or "")[:200],
                trophy=award.trophy,
                dignity=dignity,
                dignity_state=AwardGrant.DignityState.PROPOSED if dignity else "",
            )
            out.append(g)
    return out


def withdraw(comp: Competition) -> int:
    """Wettbewerb verlässt „endgültig“: offene Vergaben entfernen."""
    n, _ = _undecided(comp).delete()
    return n


def confirm_dignity(org, user, g: AwardGrant):
    """Würdenvorschlag bestätigen: legt die Regentschaft an (Herkunft = Untereinheit)."""
    from audit.log import diff, record, snapshot
    from honors.models import Reign

    if g.dignity_state != AwardGrant.DignityState.PROPOSED or g.dignity_id is None:
        from rest_framework.exceptions import ValidationError

        raise ValidationError(gettext("Dieser Vorschlag ist schon entschieden."))
    person = g.membership.person if g.membership_id else None
    origin = g.starter.unit if g.starter_id and g.starter.unit_id else None
    reign = Reign.objects.create(
        organization=org,
        dignity=g.dignity,
        year=g.year,
        person=person,
        name=g.name,
        origin_id=origin.pk if origin else None,
        note=(g.competition.title if g.competition_id else "")[:200],
    )
    record(org, user, "create", reign, diff({}, snapshot(reign)))
    g.reign = reign
    g.dignity_state = AwardGrant.DignityState.CONFIRMED
    g.save(update_fields=["reign", "dignity_state"])
    return reign


# --- Geschichte ---


def _year(g: AwardGrant) -> int:
    return g.year


def trophy_holders(trophy: Trophy) -> list[dict]:
    """Inhaber über die Jahre (neueste zuerst) und ob er in den Besitz übergegangen ist."""
    grants = list(
        AwardGrant.objects.filter(trophy=trophy).order_by("year", "pk").select_related("unit")
    )
    out = []
    streak_key, streak = None, 0
    for g in grants:
        key = (g.membership_id, g.unit_id, "" if (g.membership_id or g.unit_id) else g.name)
        streak = streak + 1 if key == streak_key else 1
        streak_key = key
        out.append(
            {
                "id": g.pk,
                "year": g.year,
                "name": g.name,
                "membership": g.membership_id,
                "unit": g.unit_id,
                "competition": g.competition_id,
                "streak": streak,
                "kept": bool(trophy.keep_after and streak >= trophy.keep_after),
                "manual": g.manual,
            }
        )
    out.reverse()
    return out


def grant_data(g: AwardGrant) -> dict:
    return {
        "id": g.pk,
        "year": g.year,
        "title": g.title,
        "item": g.item,
        "full_title": g.full_title,
        "scoring_name": g.scoring_name,
        "place": g.place,
        "value_text": g.value_text,
        "name": g.name,
        "membership": g.membership_id,
        "unit": g.unit_id,
        "competition": g.competition_id,
        "competition_title": g.competition.title if g.competition_id else "",
        "series": g.series_id,
        "trophy": g.trophy_id,
        "trophy_name": g.trophy.name if g.trophy_id else "",
        "dignity": g.dignity_id,
        "dignity_name": g.dignity.name if g.dignity_id else "",
        "dignity_state": g.dignity_state,
        "reign": g.reign_id,
        "manual": g.manual,
        "note": g.note,
    }


def _comparable(sc: Scoring) -> tuple:
    """Jahre mit gleicher Messgröße und gleicher Zahl gewerteter Schüsse sind vergleichbar."""
    return (sc.kind, sc.name, sc.unit_label, sc.counted_shots or sc.shots, sc.method, sc.team_size)


def series_archive(series: Series, *, public: bool = False) -> dict:
    """Archiv einer Reihe: je Jahr die Sieger je Wertung, Titel und Vergleich der eigenen
    Untereinheiten; Bestenliste je vergleichbarer Wertung. ``public``: nur endgültige
    Wettbewerbe (für die Webseite gelten dazu deren Regeln, siehe website.public)."""
    from . import services

    comps = list(
        Competition.objects.filter(series=series)
        .exclude(status=Competition.Status.PREPARATION)
        .order_by("-date", "-pk")
    )
    if public:
        comps = [c for c in comps if c.status == Competition.Status.FINAL]
    years = []
    records: dict[tuple, dict] = {}
    units: dict[int, dict] = {}
    for comp in comps:
        data = services.standings(comp)
        scorings = {sc.pk: sc for sc in comp.scorings.all()}
        winners = []
        for s in data.get("scorings", []):
            placed = [r for r in s["rows"] if r.get("place") is not None]
            top = [r for r in placed if r["place"] <= 3]
            winners.append(
                {
                    "scoring": s["name"],
                    "kind": s["kind"],
                    "podium": [
                        {
                            "place": r["place"],
                            "name": r.get("name", ""),
                            "membership": None,
                            "starter": r.get("starter"),
                            "unit": r.get("unit"),
                            "unit_name": r.get("unit_name", ""),
                            "value_text": r.get("value_text", ""),
                        }
                        for r in top
                    ],
                    "field": len(placed),
                }
            )
            sc = scorings.get(s["scoring"])
            if sc is None or not comp.own:
                continue
            if s["kind"] == Scoring.Kind.UNIT:
                for r in placed:
                    if r.get("unit"):
                        u = units.setdefault(
                            r["unit"], {"unit": r["unit"], "name": r.get("name", ""), "years": []}
                        )
                        u["years"].append(
                            {"year": comp.date.year, "place": r["place"], "scoring": s["name"]}
                        )
            best = placed[0] if placed else None
            if best is not None and best.get("value") is not None:
                key = _comparable(sc)
                cur = records.get(key)
                if cur is None:
                    better = True
                elif sc.higher_better:
                    better = best["value"] > cur["_value"]
                else:
                    better = best["value"] < cur["_value"]
                if better:
                    records[key] = {
                        "scoring": sc.name,
                        "unit_label": sc.unit_label,
                        "counted_shots": sc.counted_shots or sc.shots,
                        "name": best.get("name", ""),
                        "starter": best.get("starter"),
                        "value_text": best.get("value_text", ""),
                        "year": comp.date.year,
                        "_value": best["value"],
                    }
        if comp.form == Competition.Form.BIRD:
            winners = [
                {
                    "scoring": p.name,
                    "kind": "pfand",
                    "podium": [
                        {
                            "place": None,
                            "name": p.winner.name if p.winner_id else p.winner_name,
                            "starter": p.winner_id,
                            "unit": p.winner.unit_id if p.winner_id else None,
                            "unit_name": p.winner.unit.name
                            if p.winner_id and p.winner.unit_id
                            else "",
                            "value_text": "",
                        }
                    ]
                    if p.fallen
                    else [],
                    "field": None,
                }
                for p in comp.prizes.select_related("winner__unit")
            ]
        years.append(
            {
                "competition": comp.pk,
                "title": comp.title,
                "date": comp.date.isoformat(),
                "year": comp.date.year,
                "status": comp.status,
                "winners": winners,
            }
        )
    grants = AwardGrant.objects.filter(series=series).select_related(
        "competition", "trophy", "dignity"
    )
    titles = [grant_data(g) for g in grants if g.title or g.trophy_id]
    for r in records.values():
        r.pop("_value")
    return {
        "id": series.pk,
        "name": series.name,
        "description": series.description,
        "years": years,
        "titles": titles,
        "records": sorted(records.values(), key=lambda r: r["scoring"]),
        "units": sorted(units.values(), key=lambda u: u["name"]),
    }


def member_history(org, membership_ids: list[int]) -> dict:
    """Reiter „Wettbewerbe“ der Mitgliedsakte: alle Starts mit Platz und Wert, dazu Titel
    und Auszeichnungen (auch von Hand eingetragene aus früheren Jahren)."""
    from . import services

    starters = list(
        Starter.objects.filter(organization=org, membership_id__in=membership_ids)
        .select_related("competition", "unit")
        .order_by("-competition__date", "-competition__pk")
    )
    starts = []
    for st in starters:
        comp = st.competition
        results = []
        if comp.status != Competition.Status.PREPARATION:
            data = services.standings(comp)
            for s in data.get("scorings", []):
                for r in s["rows"]:
                    if r.get("starter") == st.pk:
                        results.append(
                            {
                                "scoring": s["name"],
                                "place": r.get("place"),
                                "value_text": r.get("value_text", ""),
                                "field": len([x for x in s["rows"] if x.get("place")])
                                or s.get("field_size"),
                            }
                        )
            if comp.form == Competition.Form.BIRD:
                for p in comp.prizes.filter(winner=st):
                    results.append(
                        {"scoring": p.name, "place": None, "value_text": "", "field": None}
                    )
        starts.append(
            {
                "competition": comp.pk,
                "title": comp.title,
                "date": comp.date.isoformat(),
                "status": comp.status,
                "status_label": comp.get_status_display(),
                "own": comp.own,
                "unit_name": st.unit.name if st.unit_id else "",
                "results": results,
            }
        )
    grants = AwardGrant.objects.filter(
        organization=org, membership_id__in=membership_ids
    ).select_related("competition", "trophy", "dignity")
    return {"starts": starts, "grants": [grant_data(g) for g in grants]}


def title_summary(org, membership_ids) -> dict[int, str]:
    """Spalte im Mitglieder-Export: „Vereinsmeister: 2019, 2023; Wanderpokal: 2021“."""
    by_member: dict[int, dict[str, list[int]]] = {}
    for g in (
        AwardGrant.objects.filter(organization=org, membership_id__in=membership_ids)
        .exclude(title="", trophy=None)
        .select_related("trophy")
    ):
        label = g.title or (g.trophy.name if g.trophy_id else "")
        if not label:
            continue
        by_member.setdefault(g.membership_id, {}).setdefault(label, []).append(g.year)
    out = {}
    for mid, d in by_member.items():
        out[mid] = "; ".join(
            f"{t}: {', '.join(str(y) for y in sorted(ys))}" for t, ys in sorted(d.items())
        )
    return out
