"""Gesamtaudit I-F02: Das OpenAPI-Schema beschreibt jeden API-Endpunkt.

Früher prüfte der Test nur, ob /api/schema/ antwortet. Jetzt: Erzeugung ohne Fehler
und Warnungen von drf-spectacular, und jede Route unter /api/ steht mit allen ihren
Methoden im Schema."""

import re

from django.urls import URLResolver, get_resolver, path
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import EndpointEnumerator, SchemaGenerator
from rest_framework.response import Response
from rest_framework.views import APIView

# Diese Seiten liefern das Schema selbst aus
NOT_IN_SCHEMA = {"/api/schema/", "/api/docs/"}


def generate(patterns=None):
    GENERATOR_STATS.reset()
    with GENERATOR_STATS.silence():
        schema = SchemaGenerator(patterns=patterns).get_schema(request=None, public=True)
    return schema, sorted(GENERATOR_STATS._error_cache), sorted(GENERATOR_STATS._warn_cache)


def routes(patterns, prefix=""):
    """Alle Routen unter /api/ mit ihren Methoden, auch solche ohne Schema."""
    enumerator = EndpointEnumerator()
    for pattern in patterns:
        regex = prefix + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            yield from routes(pattern.url_patterns, regex)
            continue
        route = enumerator.get_path_from_regex(regex)
        if not route.startswith("/api/") or route in NOT_IN_SCHEMA:
            continue
        callback = pattern.callback
        if hasattr(callback, "cls"):
            methods = enumerator.get_allowed_methods(callback)
        else:
            methods = ["GET"]  # Django-View ohne DRF: taucht nie im Schema auf
        yield route, methods


def missing_operations(schema, patterns) -> list[tuple[str, str]]:
    def norm(route: str) -> str:
        return re.sub(r"\{\w+\}", "{}", route)

    described: dict[str, set[str]] = {}
    for route, operations in schema["paths"].items():
        described.setdefault(norm(route), set()).update(operations)
    return [
        (route, method)
        for route, methods in routes(patterns)
        for method in methods
        if method.lower() not in described.get(norm(route), set())
    ]


def test_schema_ohne_fehler_und_warnungen():
    _schema, errors, warnings = generate()
    assert errors == []
    assert warnings == []


def test_jede_route_steht_im_schema():
    schema, _errors, _warnings = generate()
    assert missing_operations(schema, get_resolver().url_patterns) == []


def test_downloads_und_anmeldelink_sind_beschrieben():
    schema, _errors, _warnings = generate()
    paths = schema["paths"]
    login = paths["/api/public/login-link/{token}/"]["post"]
    assert login["security"] == [{}]  # ohne Anmeldung erreichbar
    pdf = next(p for route, p in paths.items() if route.endswith("/pdf/") and "get" in p)
    assert "*/*" in pdf["get"]["responses"]["200"]["content"]


class Unbeschrieben(APIView):
    schema = None  # absichtlich aus dem Schema genommen

    def get(self, request):
        return Response({})


def test_fehlender_endpunkt_faellt_auf():
    patterns = [path("api/probe/", Unbeschrieben.as_view())]
    schema, _errors, _warnings = generate(patterns)
    assert missing_operations(schema, patterns) == [("/api/probe/", "GET")]
