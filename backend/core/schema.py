"""OpenAPI-Beschreibung (drf-spectacular) auch für APIViews ohne Serializer.

Viele Endpunkte sind schlanke APIViews ohne ``serializer_class``. drf-spectacular
meldet dann „unable to guess serializer“ und beschreibt nur Pfad und Parameter. Hier
bekommen solche Views eine allgemeine Beschreibung: beliebiges JSON bei Anfragen mit
Inhalt, Datei-Antworten bei Download-Endpunkten. So taucht jeder Endpunkt mit
Methoden, Parametern und Anmeldepflicht im Schema auf, und die Schemaprüfung
(tests/test_gesamtaudit_schema.py) kann echte Fehler von dieser Lücke unterscheiden.
Wer einen Endpunkt genauer beschreiben will, nutzt wie gewohnt ``@extend_schema``.
"""

from __future__ import annotations

import re

from drf_spectacular.openapi import AutoSchema as BaseAutoSchema
from drf_spectacular.types import OpenApiTypes
from rest_framework.generics import GenericAPIView

# Views, die Dateien ausliefern (PDF, Kalender, Anhänge, Downloads)
FILE_VIEW = re.compile(
    r"(Pdf|Ics|Download|Attachment|ErrorFile|Letters|ResponseExport|CardPhoto|Receipt|Version)View$"
)
WRITE_METHODS = {"POST", "PUT", "PATCH"}
SCOPE_PARAMS = {"org_id", "dept_id", "access_id"}


class AutoSchema(BaseAutoSchema):
    def _describes_itself(self) -> bool:
        view = self.view
        if isinstance(view, GenericAPIView):
            try:
                return view.get_serializer_class() is not None
            except AssertionError:
                return False
        hooks = ("get_serializer", "get_serializer_class")
        return any(callable(getattr(view, name, None)) for name in hooks) or hasattr(
            view, "serializer_class"
        )

    def _is_file_view(self) -> bool:
        return self.method == "GET" and bool(FILE_VIEW.search(type(self.view).__name__))

    def get_request_serializer(self):
        if self._describes_itself():
            return super().get_request_serializer()
        return OpenApiTypes.OBJECT if self.method in WRITE_METHODS else None

    def get_response_serializers(self):
        if self._describes_itself():
            return super().get_response_serializers()
        if self._is_file_view():
            return {(200, "*/*"): OpenApiTypes.BINARY}
        if self.method == "DELETE":
            return {204: None}
        return OpenApiTypes.ANY

    def get_operation_id(self) -> str:
        operation_id = super().get_operation_id()
        if self._describes_itself():
            return operation_id
        # APIViews: Liste und Einzelobjekt unterscheiden und die Parameter nennen, die
        # das Objekt bestimmen (ohne die Organisation am Anfang des Pfads)
        base, action = operation_id.rsplit("_", 1)
        if self.method == "GET":
            action = "retrieve" if re.search(r"\}/?$", self.path) else "list"
        params = [p for p in re.findall(r"\{(\w+)\}", self.path) if p not in SCOPE_PARAMS]
        if params:
            base = f"{base}_by_{'_'.join(params)}"
        return f"{base}_{action}"

    def _resolve_path_parameters(self, variables):
        # ViewSets bauen ihren Queryset erst mit der Organisation aus der Anfrage; für
        # die Typen der Pfadparameter genügt das Modell aus dem Serializer
        view = self.view
        if getattr(view, "queryset", None) is None and isinstance(view, GenericAPIView):
            try:
                model = view.get_serializer_class().Meta.model
            except (AssertionError, AttributeError):
                model = None
            if model is not None:
                view.queryset = model._default_manager.none()
        return super()._resolve_path_parameters(variables)
