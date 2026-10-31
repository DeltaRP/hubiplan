"""Blättern und Suchen in langen Listen (Protokoll, Postausgang)."""

from __future__ import annotations

import datetime

from django.db.models import Q, QuerySet
from rest_framework.pagination import PageNumberPagination


class ListPagination(PageNumberPagination):
    """Seiten zu 50 Einträgen; Antwort mit ``count``, ``page``, ``pages`` und ``results``."""

    page_size = 50
    page_query_param = "seite"
    page_size_query_param = "pro_seite"
    max_page_size = 200

    def get_paginated_response(self, data):
        from rest_framework.response import Response

        return Response(
            {
                "count": self.page.paginator.count,
                "page": self.page.number,
                "pages": self.page.paginator.num_pages,
                "results": data,
            }
        )

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "page": {"type": "integer"},
                "pages": {"type": "integer"},
                "results": schema,
            },
        }


def _date(value: str | None) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def search(qs: QuerySet, params, text_fields: tuple[str, ...], date_field: str) -> QuerySet:
    """Filter ``q`` (alle Wörter in einem der Textfelder), ``von`` und ``bis`` (Datum)."""
    for word in (params.get("q") or "").split():
        cond = Q()
        for field in text_fields:
            cond |= Q(**{f"{field}__icontains": word})
        qs = qs.filter(cond)
    if start := _date(params.get("von")):
        qs = qs.filter(**{f"{date_field}__date__gte": start})
    if end := _date(params.get("bis")):
        qs = qs.filter(**{f"{date_field}__date__lte": end})
    return qs
