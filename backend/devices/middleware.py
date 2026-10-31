"""Kopfzeile für die App: welches Unterschriftsformat dieser Server kennt (BSEC-02).

Die App unterschreibt Vorstandsanfragen erst im Format 2 (mit Zufallskennung), wenn der
Server es angekündigt hat; ältere Instanzen bekommen weiter Format 1.
"""

from __future__ import annotations

SIGNATURE_FORMAT_HEADER = "X-Hubiplan-Signature-Format"


class SignatureFormatMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/app/"):
            response[SIGNATURE_FORMAT_HEADER] = "2"
        return response
