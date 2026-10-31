# ruff: noqa: F811  (Fixtures aus test_verbund_kopplung)
"""Härtung des Verbunds (Konzept haertung-austausch.md, erfundene Daten)."""

import pytest

from core.tenancy import rls_bypass, unit_context
from members.models import Membership

from .factories import make_member, make_org
from .test_verbund_kopplung import VERBAND, VEREIN, _setup, couple, net, world  # noqa: F401
from .verbund_netz import app_role

pytestmark = pytest.mark.django_db


def test_unit_context_hebt_umgehung_auf():
    a = make_org("Verein A")
    b = make_org("Verein B")
    make_member(a, "Anna", "Aktiv")
    make_member(b, "Bert", "Fremd")
    with app_role(), rls_bypass():
        assert Membership.objects.count() == 2
        with unit_context(a.pk):
            # Auch innerhalb einer Umgehung nur die eigene Einheit
            assert list(Membership.objects.values_list("organization_id", flat=True)) == [a.pk]
        assert Membership.objects.count() == 2


def test_bekannter_absender_erst_unterschrift(net, world):
    """Gefälschtes Paket eines bekannten Absenders: 403, ohne erst zu entschlüsseln."""
    import json as _json
    import uuid

    from django.test import Client
    from django.utils import timezone

    from peering import crypto, identity, transport

    couple(net, world)
    with net.on(VEREIN):
        sender = identity.identity().instance_id
    with net.on(VERBAND):
        body = _json.dumps({"format": crypto.ENVELOPE, "from": sender, "to": "x"}).encode()
        resp = Client().post(
            "/api/peering/v1/inbox/",
            data=body,
            content_type="application/json",
            headers={
                transport.H_INSTANCE: sender,
                transport.H_DATE: timezone.now().isoformat(),
                transport.H_NONCE: uuid.uuid4().hex,
                transport.H_SIGNATURE: "AAAA",
            },
        )
    assert resp.status_code == 403
    assert "Unterschrift" in resp.json()["error"]


def test_fremde_dateien_abgeschottet():
    from django.http import HttpResponse

    from peering.api import _foreign_file

    resp = _foreign_file(HttpResponse(b"%PDF-"))
    assert resp["Content-Security-Policy"] == "sandbox"
    assert resp["X-Content-Type-Options"] == "nosniff"
