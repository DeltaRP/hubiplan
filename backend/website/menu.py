"""Menü der Webseite als Baum (Ralf 2026-10-31): Reihenfolge per Ziehen, ein Punkt
auf einen anderen gezogen wird sein Unterpunkt, herausgezogen wieder Hauptpunkt.

Gespeichert wird nur die Anordnung (``Website.menu``): ``[{"key": …, "children":
[{"key": …}]}]``, höchstens zwei Ebenen. Ein- und ausgeschaltet werden die Bereiche
weiter über ``Website.blocks``. Punkte, die es (noch) nicht gibt, fallen weg; neue
Punkte kommen an ihren Standardplatz.

Schlüssel: die Bausteine aus ``BLOCKS`` (ohne „social“), ``page:<id>`` für eigene
Textseiten, ``dignity:<id>`` und ``honorary`` für die Unterpunkte von „Würdenträger“
(einzeln ausschaltbar über ``blocks`` mit demselben Schlüssel) und ``group:history``
für die Überschrift „Geschichte“. Überschriften (``heading``)
haben keine eigene Seite; ohne Unterpunkte entfallen sie, mit nur einem steht dieser
direkt im Menü.
"""

from __future__ import annotations

from .models import BLOCK_HINTS, BLOCKS, Website

# Bausteine, die kein Menüpunkt sind
NOT_IN_MENU = {"social"}
# Überschriften ohne eigene Seite: Schlüssel → (Bezeichnung, Standard-Unterpunkte)
HEADINGS = {"group:history": ("Geschichte", ("history", "offices"))}
# Textseite „Geschichte“ ist der Baustein „history“, kein eigener Menüpunkt
HISTORY_SLUG = "geschichte"


def _block_keys() -> list[str]:
    return [k for k in BLOCKS if k not in NOT_IN_MENU]


def items(website: Website, *, public_site=None) -> dict[str, dict]:
    """Alle möglichen Menüpunkte in Standardreihenfolge.

    Je Punkt: ``label``, ``hint``, ``toggle`` (Baustein-Schlüssel für ein/aus oder
    None), ``heading`` (Überschrift ohne eigene Seite), ``parent`` (Standard-
    Oberpunkt oder None). Mit ``public_site`` (SiteView) kommen öffentliche Angaben
    dazu (``visible``, ``slug``, ``id``)."""

    from .content_models import WebsiteText
    from .public import SiteView

    org = website.organization
    site = public_site or SiteView(website)
    result: dict[str, dict] = {}
    heading_of = {child: key for key, (_l, children) in HEADINGS.items() for child in children}

    def add(key, label, *, hint="", toggle=None, heading=False, parent=None, **extra):
        result[key] = {
            "label": label,
            "hint": hint,
            "toggle": toggle,
            "heading": heading,
            "parent": parent,
            **extra,
        }

    pages = list(
        WebsiteText.objects.filter(website=website, kind=WebsiteText.Kind.PAGE)
        .exclude(slug=HISTORY_SLUG)
        .order_by("menu_position", "title", "pk")
    )
    for key in _block_keys():
        if key in heading_of and heading_of[key] not in result:
            label, _children = HEADINGS[heading_of[key]]
            add(heading_of[key], label, hint="Überschrift ohne eigene Seite", heading=True)
        if key == "statutes":
            # Eigene Textseiten stehen vor „Dokumente“
            for p in pages:
                state = []
                if p.published_at is None:
                    state.append("noch nicht veröffentlicht")
                if not p.show_in_menu:
                    state.append("unter Webseite › Texte aus dem Menü genommen")
                add(
                    f"page:{p.pk}",
                    p.title or p.published_title or p.slug,
                    hint="eigene Textseite" + (f" · {', '.join(state)}" if state else ""),
                    slug=p.slug,
                    visible=p.published_at is not None and p.show_in_menu,
                    public_label=p.published_title or p.slug,
                )
        if key == "results" and "competitions" not in (org.enabled_modules or []):
            continue
        label = BLOCKS[key]
        if key == "units":
            label = org.department_label_plural or label
        if key == "honors":
            add(
                "honors",
                "Würdenträger",
                hint="Überschrift mit den Würden und Ehrungen",
                toggle="honors",
                heading=True,
            )
            for qs, _view, _owner, origins in site.dignity_sources():
                for d in site._with_reigns(qs, origins):
                    add(
                        f"dignity:{d.pk}",
                        d.plural if d.reign_count > 1 else d.name,
                        hint="Würde",
                        toggle=f"dignity:{d.pk}",
                        parent="honors",
                        id=site.token("dignity", d.pk),
                        visible=website.block_on("honors") and website.block_on(f"dignity:{d.pk}"),
                    )
            honorary = site.honorary()
            if honorary:
                add(
                    "honorary",
                    honorary[0]["heading"] if len(honorary) == 1 else "Ehrungen",
                    hint="Ehrungen und ihre Träger",
                    toggle="honorary",
                    parent="honors",
                    visible=website.block_on("honorary"),
                )
            continue
        add(key, label, hint=BLOCK_HINTS.get(key, ""), toggle=key, parent=heading_of.get(key))
    return result


def _clean(value) -> list[dict]:
    """Gespeicherte Anordnung → Liste von {key, children} (nur gültige Form)."""
    result = []
    for node in value if isinstance(value, list) else []:
        if not isinstance(node, dict) or not isinstance(node.get("key"), str):
            continue
        children = [
            {"key": c["key"]}
            for c in node.get("children") or []
            if isinstance(c, dict) and isinstance(c.get("key"), str)
        ]
        result.append({"key": node["key"], "children": children})
    return result


def normalize(value, known: dict[str, dict]) -> list[dict]:
    """Anordnung auf die bekannten Punkte bringen: Unbekanntes und Doppeltes fällt
    weg, Überschriften und Punkte mit Unterpunkten stehen oben, Fehlendes kommt an
    seinen Standardplatz (unter den Standard-Oberpunkt oder hinter den letzten
    Hauptpunkt, der in der Standardreihenfolge davor steht)."""
    order = {key: i for i, key in enumerate(known)}
    seen: set[str] = set()
    tree: list[dict] = []
    for node in _clean(value):
        key = node["key"]
        if key not in known or key in seen:
            continue
        seen.add(key)
        children = []
        for c in node["children"]:
            ck = c["key"]
            # Überschriften stehen immer oben (sie kommen unten an ihren Standardplatz)
            if ck in known and ck not in seen and not known[ck]["heading"]:
                seen.add(ck)
                children.append({"key": ck, "children": []})
        tree.append({"key": key, "children": children})
    for key, item in known.items():
        if key in seen:
            continue
        seen.add(key)
        new = {"key": key, "children": []}
        parent = item.get("parent")
        holder = next((n for n in tree if n["key"] == parent), None) if parent else None
        if holder is not None:
            siblings = holder["children"]
            at = next(
                (i for i, c in enumerate(siblings) if order.get(c["key"], 0) > order[key]),
                len(siblings),
            )
            siblings.insert(at, new)
            continue
        # hinter den letzten Hauptpunkt, der in der Standardreihenfolge davor steht
        before = [i for i, n in enumerate(tree) if order.get(n["key"], 0) < order[key]]
        tree.insert(before[-1] + 1 if before else 0, new)
    return tree


def validate(value, known: dict[str, dict]) -> list[dict]:
    """Prüft eine neue Anordnung aus der Verwaltung (wirft ValueError)."""
    if not isinstance(value, list):
        raise ValueError("Bitte das Menü als Liste angeben.")
    for node in _clean(value):
        if node["key"] not in known:
            continue
        if node["children"] and any(
            c["key"] in known and known[c["key"]]["heading"] for c in node["children"]
        ):
            raise ValueError("Eine Überschrift kann kein Unterpunkt sein.")
    for node in value:
        for c in (node.get("children") or []) if isinstance(node, dict) else []:
            if isinstance(c, dict) and c.get("children"):
                raise ValueError("Das Menü hat höchstens zwei Ebenen.")
    return normalize(value, known)


def public_nav(site) -> list[dict]:
    """Menü für die Webseite: nur sichtbare Punkte, je Punkt ``key``, ``label``,
    bei Textseiten ``slug``, bei Würden ``id``, bei Überschriften ``heading`` und
    bei Unterpunkten ``children``."""
    website = site.site
    known = items(website, public_site=site)

    def visible(key: str) -> bool:
        item = known[key]
        if "visible" in item:
            return bool(item["visible"])
        if item["heading"]:
            return True
        return _available(site, key)

    def entry(key: str) -> dict:
        item = known[key]
        out = {"key": key.split(":", 1)[0], "label": item.get("public_label") or item["label"]}
        if key.startswith("page:"):
            out["slug"] = item["slug"]
        if key.startswith("dignity:"):
            out["id"] = item["id"]
        if key == "honors" and not item["heading"]:
            out["label"] = site.honors_label()
        if item["heading"]:
            out["heading"] = True
        return out

    result = []
    for node in normalize(website.menu, known):
        children = [entry(c["key"]) for c in node["children"] if visible(c["key"])]
        if not visible(node["key"]) and not known[node["key"]]["heading"]:
            # Ausgeschalteter Oberpunkt: seine Unterpunkte rücken nach oben
            result += children
            continue
        top = entry(node["key"])
        if top.get("heading"):
            if not children:
                continue
            if len(children) == 1:
                result.append(children[0])
                continue
        if children:
            top["children"] = children
        result.append(top)
    return result


def _available(site, key: str) -> bool:
    """Ist der Bereich eingeschaltet und hat er Inhalt (wie bisher das Menü der Webseite)?"""
    website = site.site
    if key not in BLOCKS or not website.block_on(key):
        return False
    if key == "posts":
        return any(site.posts_available().values())
    if key == "units":
        return bool(site.units)
    if key == "statutes":
        from .public_views import DOCUMENT_KINDS, _statute_publication

        # Satzung, Beitragsordnung oder Gründungsurkunde öffentlich
        return any(_statute_publication(site, kind) is not None for kind in DOCUMENT_KINDS)
    if key == "history":
        return site.page(HISTORY_SLUG) is not None
    if key == "offices":
        return bool(site.chairs())
    if key == "results":
        from . import results

        return results.available(site)
    return True
