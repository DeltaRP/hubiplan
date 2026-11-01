"""Scheibenkatalog und Trefferpunkte (Schießscheiben Schritt 1).

- ``GET competitions/targets/``: Scheiben, Wertungsarten und Gleichstandsregeln für die
  Oberfläche (zum Auswählen und später zum Zeichnen der Scheibe).
- ``GET/PUT competitions/<id>/hits/``: Treffer eines Starters in einer Einzelwertung lesen
  bzw. ersetzen. Mit Wertungsart Ringe, Zehntel oder Teiler rechnet HUBIplan daraus den
  Wert des Starters; bei „frei“ bleiben die Treffer nur Angabe.
- ``POST competitions/<id>/photo/`` (und über den Standzugang): Treffer auf einem Foto der
  Scheibe vorschlagen (Schritt 4). Das Foto wird nur im Speicher ausgewertet, nie
  gespeichert; gespeichert wird erst, was jemand im Antipp-Bild bestätigt.
- ``GET/PATCH/DELETE competitions/photo-samples/``: Einwilligung des Vereins, bestätigte
  Spiegelausschnitte zu sammeln, und Löschen aller gesammelten (Schritt 6, ``samples.py``).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.log import diff, record, snapshot

from . import samples, services, targets, tiebreak
from .models import Hit, PhotoSample, PhotoSampleConsent, Scoring, Starter
from .views import _Mixin, _open_for_entries, set_score

# Treffer weiter draußen sind sicher Tippfehler (größte Scheibe: 50 cm)
MAX_MM = Decimal(1000)
MAX_HITS = 200
MAX_PHOTO_BYTES = 15 * 1024 * 1024
PHOTO_RATE = (60, 600)  # Fotos je 10 Minuten (je Konto bzw. Standzugang)


class TargetCatalogView(_Mixin, APIView):
    manage_only = False

    def get(self, request, org_id: int):
        return Response(
            {
                "targets": targets.catalog(),
                "custom": targets.CUSTOM,
                "methods": [{"value": v, "label": label} for v, label in Scoring.Method.choices],
                "tie_breaks": [{"value": k, "label": label} for k, label in tiebreak.CRITERIA],
                "presets": tiebreak.PRESETS,
            }
        )


def _coord(raw, field: str) -> Decimal:
    try:
        value = Decimal(str(raw).replace(",", ".").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValidationError(
            {"hits": gettext("{field}: Bitte eine Zahl angeben.").format(field=field)}
        ) from exc
    if not value.is_finite() or abs(value) > MAX_MM:
        raise ValidationError(
            {"hits": gettext("{field}: Treffer liegt außerhalb der Scheibe.").format(field=field)}
        )
    return value.quantize(Decimal("0.001"))


def hits_data(scoring: Scoring, starter: Starter) -> dict:
    hits = list(Hit.objects.filter(scoring=scoring, starter=starter).order_by("number"))
    values = services.shot_values(scoring, hits)
    method = scoring.method
    counted = targets.counted_shots(
        method if method != targets.METHOD_FREE else targets.METHOD_RINGS,
        values,
        scoring.counted_shots or None,
    )
    counted_ids = {id(v) for v in counted}
    total = (
        targets.total(method, values, scoring.counted_shots or None)
        if method != targets.METHOD_FREE
        else None
    )
    return {
        "scoring": scoring.pk,
        "starter": starter.pk,
        "target": scoring.target,
        "method": method,
        "hits": [
            {
                "number": h.number,
                "x": str(h.x),
                "y": str(h.y),
                "spot": h.spot,
                "source": h.source,
                **(v.as_dict() if v else {}),
                "counted": id(v) in counted_ids if v else False,
            }
            for h, v in zip(hits, values or [None] * len(hits), strict=True)
        ],
        "total": None if total is None else str(total),
    }


@transaction.atomic
def set_hits(
    org,
    user,
    comp,
    scoring: Scoring,
    starter: Starter,
    raw,
    source=None,
    at=None,
    sample_keys=None,
) -> dict:
    """Treffer eines Starters ersetzen; Wert neu rechnen (außer bei „frei“).

    ``at``: Zeitpunkt der Eingabe auf dem Gerät (Standmodus offline). Wurden die Treffer
    auf dem Server danach geändert, gilt die spätere Eingabe; zurück kommt dann der
    gültige Stand mit ``conflict``. ``sample_keys``: bereitgelegte Spiegelausschnitte vom
    Foto, die mit diesen bestätigten Treffern gesammelt werden (nur mit Einwilligung)."""
    _open_for_entries(comp)
    if scoring.kind != Scoring.Kind.INDIVIDUAL:
        raise ValidationError(gettext("Treffer gibt es nur in Einzelwertungen."))
    if services.target_of(scoring) is None:
        raise ValidationError(gettext("Für diese Wertung ist keine Scheibe eingestellt."))
    if not isinstance(raw, list):
        raise ValidationError({"hits": gettext("Bitte eine Liste von Treffern senden.")})
    limit = scoring.shots or MAX_HITS
    if len(raw) > limit:
        raise ValidationError(
            {"hits": gettext("Höchstens {limit} Treffer je Schütze.").format(limit=limit)}
        )
    src = source or Hit.Source.TAP
    if src not in Hit.Source.values:
        raise ValidationError({"source": gettext("Unbekannte Quelle.")})
    wanted = []
    for n, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValidationError({"hits": gettext("Ungültiger Treffer.")})
        spot = item.get("spot")
        if spot not in (None, ""):
            try:
                spot = int(spot)
            except (TypeError, ValueError) as exc:
                raise ValidationError({"hits": gettext("Ungültiger Spiegel.")}) from exc
            if spot < 1 or spot > 20:
                raise ValidationError({"hits": gettext("Ungültiger Spiegel.")})
        else:
            spot = None
        wanted.append(
            {
                "number": n,
                "x": _coord(item.get("x"), f"Schuss {n}"),
                "y": _coord(item.get("y"), f"Schuss {n}"),
                "spot": spot,
                "source": item.get("source") if item.get("source") in Hit.Source.values else src,
            }
        )
    existing = {
        h.number: h
        for h in Hit.objects.select_for_update().filter(scoring=scoring, starter=starter)
    }
    if at is not None and existing and max(h.updated_at for h in existing.values()) > at:
        same = len(existing) == len(wanted) and all(
            (existing[w["number"]].x, existing[w["number"]].y) == (w["x"], w["y"])
            for w in wanted
            if w["number"] in existing
        )
        if not same:
            return {**hits_data(scoring, starter), "conflict": True}
    for w in wanted:
        h = existing.pop(w["number"], None)
        if h is None:
            h = Hit.objects.create(organization=org, scoring=scoring, starter=starter, **w)
            record(org, user, "create", h, diff({}, snapshot(h)))
            continue
        before = snapshot(h)
        for k, v in w.items():
            setattr(h, k, v)
        h.save()
        changes = diff(before, snapshot(h))
        if changes:
            record(org, user, "update", h, changes)
    for h in existing.values():
        record(org, user, "delete", h, diff(snapshot(h), {}))
        h.delete()
    recompute(org, user, comp, scoring, starter)
    samples.store(org, scoring, sample_keys, wanted)
    return hits_data(scoring, starter)


def recompute(org, user, comp, scoring: Scoring, starter: Starter) -> None:
    """Wert des Starters aus seinen Treffern (nur Ringe, Zehntel, Teiler)."""
    if scoring.method == targets.METHOD_FREE or services.target_of(scoring) is None:
        return
    hits = list(Hit.objects.filter(scoring=scoring, starter=starter).order_by("number"))
    value = targets.total(
        scoring.method, services.shot_values(scoring, hits), scoring.counted_shots or None
    )
    set_score(org, user, comp, scoring, starter, None if value is None else str(value))


def recompute_all(org, user, comp, scoring: Scoring) -> None:
    """Nach Änderung von Scheibe, Wertungsart oder gewerteten Schüssen."""
    if comp.status == comp.Status.FINAL:
        return
    ids = set(Hit.objects.filter(scoring=scoring).values_list("starter_id", flat=True))
    for starter in Starter.objects.filter(pk__in=ids):
        recompute(org, user, comp, scoring, starter)


class HitsView(_Mixin, APIView):
    """GET ?scoring=&starter=: Treffer mit Wertung; PUT {scoring, starter, hits, source}."""

    manage_only = False

    def _objects(self, comp, data):
        scoring = get_object_or_404(
            Scoring, pk=data.get("scoring"), competition=comp, kind=Scoring.Kind.INDIVIDUAL
        )
        starter = get_object_or_404(Starter, pk=data.get("starter"), competition=comp)
        return scoring, starter

    def get(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        scoring, starter = self._objects(comp, request.query_params)
        return Response(hits_data(scoring, starter))

    def put(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        scoring, starter = self._objects(comp, request.data)
        return Response(
            set_hits(
                self.org,
                request.user,
                comp,
                scoring,
                starter,
                request.data.get("hits"),
                request.data.get("source"),
                sample_keys=request.data.get("samples"),
            )
        )


# --- Foto (Schritt 4) ---


def photo_rate(key: str) -> None:
    """Fotos kosten Rechenzeit: höchstens ``PHOTO_RATE`` je Konto bzw. Standzugang."""
    key = f"scheibenfoto:{key}"
    count = cache.get(key, 0)
    if count >= PHOTO_RATE[0]:
        raise Throttled(detail=gettext("Zu viele Fotos in kurzer Zeit. Bitte kurz warten."))
    cache.set(key, count + 1, PHOTO_RATE[1])


def detect_photo(comp, data, files) -> dict:
    """Treffer auf dem Foto vorschlagen (nichts wird gespeichert)."""
    scoring = get_object_or_404(
        Scoring, pk=data.get("scoring"), competition=comp, kind=Scoring.Kind.INDIVIDUAL
    )
    target = services.target_of(scoring)
    if target is None:
        raise ValidationError(gettext("Für diese Wertung ist keine Scheibe eingestellt."))
    upload = files.get("photo")
    if upload is None:
        raise ValidationError({"photo": gettext("Bitte ein Foto der Scheibe senden.")})
    if upload.size > MAX_PHOTO_BYTES:
        raise ValidationError({"photo": gettext("Das Foto ist zu groß (höchstens 15 MB).")})
    # erst hier laden: OpenCV braucht Speicher, den nicht jeder Aufruf braucht
    from .vision import detect

    reason = detect.unsupported(target)
    if reason:
        raise ValidationError({"photo": reason})
    collect = samples.enabled(comp.organization)
    try:
        found = detect.detect(upload.read(), target, scoring.shots or None, crops=collect)
    except detect.DetectError as exc:
        raise ValidationError({"photo": str(exc)}) from exc
    return {
        "scoring": scoring.pk,
        "hits": [
            {
                "x": f"{x:.3f}",
                "y": f"{y:.3f}",
                "spot": found.spots[i] if found.spots else None,
                "source": Hit.Source.PHOTO,
            }
            for i, (x, y) in enumerate(found.hits)
        ],
        "needs_review": found.needs_review,
        "note": found.note,
        # nur mit Einwilligung des Vereins: Schlüssel der bereitgelegten Spiegelausschnitte
        "samples": (
            samples.keep(comp.organization, scoring, target, found, detect.PX_PER_MM)
            if collect
            else []
        ),
    }


class PhotoView(_Mixin, APIView):
    """POST (multipart) photo, scoring: Vorschlag ``{hits, needs_review, note}``."""

    manage_only = False
    parser_classes = [MultiPartParser]

    def post(self, request, org_id: int, competition_id: int):
        comp = self.competition(competition_id)
        photo_rate(f"u{request.user.pk}")
        return Response(detect_photo(comp, request.data, request.FILES))


class PhotoSamplesView(_Mixin, APIView):
    """Bestätigte Spiegelausschnitte sammeln (Schritt 6): GET Stand, PATCH {enabled},
    DELETE löscht alle gesammelten Ausschnitte des Vereins."""

    def data(self) -> dict:
        consent = PhotoSampleConsent.objects.filter(organization=self.org).first()
        return {
            "enabled": bool(consent and consent.enabled),
            "changed_at": consent.changed_at if consent else None,
            "count": PhotoSample.objects.filter(organization=self.org).count(),
            "can_manage": self.can_manage,
        }

    def get(self, request, org_id: int):
        return Response(self.data())

    @transaction.atomic
    def patch(self, request, org_id: int):
        value = request.data.get("enabled")
        if not isinstance(value, bool):
            raise ValidationError({"enabled": gettext("Bitte ja oder nein angeben.")})
        consent, _ = PhotoSampleConsent.objects.select_for_update().get_or_create(
            organization=self.org
        )
        if consent.enabled != value:
            record(
                self.org,
                request.user,
                "update",
                consent,
                {
                    "Spiegelausschnitte sammeln": [
                        "nein" if value else "ja",
                        "ja" if value else "nein",
                    ]
                },
            )
            consent.enabled = value
            consent.save()
        return Response(self.data())

    @transaction.atomic
    def delete(self, request, org_id: int):
        count, _ = PhotoSample.objects.filter(organization=self.org).delete()
        if count:
            record(
                self.org,
                request.user,
                "delete",
                PhotoSampleConsent.objects.get_or_create(organization=self.org)[0],
                {"Spiegelausschnitte gelöscht": [str(count), "0"]},
            )
        return Response(self.data())
