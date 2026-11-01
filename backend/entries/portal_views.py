"""Mitgliederbereich: „Wofür bin ich gemeldet?“ (Meldungen Schritt 2).

Gezeigt wird nur, was der Verein dem Veranstalter tatsächlich gemeldet hat, also die
Personen der letzten Fassung, nicht ein Entwurf oder eine noch nicht gemeldete Änderung.
"""

from __future__ import annotations

import datetime

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core.tenancy import tenant_context
from portal.views import _portal_access

from .models import Entry, EntryPerson, EntryVersion

MODULE = "entries"
# Vergangene Anlässe noch so lange zeigen
PAST_DAYS = 365


def _sent_persons(entry: Entry) -> set[tuple[int, str]]:
    """(Eintrag, Name) der letzten Fassung. Der Name gehört dazu, weil ein Ersatz denselben
    Eintrag behält: Bis zur nächsten Fassung ist noch der Ersetzte gemeldet."""
    last = entry.versions.order_by("-number").first()
    if last is None or last.kind == EntryVersion.Kind.WITHDRAWAL:
        return set()
    out: set[tuple[int, str]] = set()
    for b in (last.data or {}).get("blocks", []):
        for group in [*b.get("teams", []), b]:
            out |= {(p.get("id"), p.get("name")) for p in group.get("persons", [])}
    return out


class PortalEntriesView(APIView):
    """GET: Anlässe, für die das Mitglied gemeldet ist (kommende zuerst)."""

    def get(self, request, access_id: int):
        access = _portal_access(request.user, access_id)
        club = access.organization
        if MODULE not in (club.enabled_modules or []):
            return Response([])
        since = timezone.localdate() - datetime.timedelta(days=PAST_DAYS)
        out = []
        with tenant_context(club.pk, request.user.pk):
            persons = (
                EntryPerson.objects.filter(
                    entry__organization=club,
                    membership_id=access.membership_id,
                    entry__status__in=(Entry.Status.SUBMITTED, Entry.Status.CONFIRMED),
                )
                .exclude(entry__call__date__lt=since)
                .select_related("entry__call", "team", "block")
            )
            sent: dict[int, set[tuple[int, str]]] = {}
            for p in persons:
                entry = p.entry
                if entry.pk not in sent:
                    sent[entry.pk] = _sent_persons(entry)
                if (p.pk, p.name) not in sent[entry.pk]:
                    continue
                call = entry.call
                out.append(
                    {
                        "id": p.pk,
                        "title": call.title,
                        "organizer": call.organizer,
                        "date": call.date,
                        "location": call.location,
                        "event": call.event_id,
                        "group": p.team.name if p.team_id else p.block.label,
                        "position": p.position,
                        "substitute": p.substitute,
                        "confirmed": entry.status == Entry.Status.CONFIRMED,
                    }
                )
        today = timezone.localdate()

        def order(r):
            day = r["date"] or datetime.date.max
            past = day < today
            return (past, -day.toordinal() if past else day.toordinal())

        out.sort(key=order)
        return Response(out)
