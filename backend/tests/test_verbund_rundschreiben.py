# ruff: noqa: F811  (Fixtures aus test_verbund_kopplung)
"""Verbund Schritt 5: Rundschreiben zur Weitergabe nach unten (erfundene Daten)."""

import pytest
from django.core import mail

from circulars import services as circular_services
from circulars.models import Circular, CircularAttachment
from core.tenancy import tenant_context
from peering.models import RemoteCircular

from .factories import make_member, make_org
from .test_verbund_kopplung import VERBAND, VEREIN, _setup, api, couple, net, world  # noqa: F401
from .verbund_netz import release

pytestmark = pytest.mark.django_db
JSON = "application/json"


@pytest.fixture
def setup(net, world, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    club, fed = world["club"], world["fed"]
    with net.on(VEREIN):
        make_member(club, "Anna", "Aktiv", email="anna@verein.example")
        make_member(club, "Bert", "Aktiv", email="bert@verein.example")
    with net.on(VERBAND):
        fed.federation_member_access = "read"
        fed.contact_email = "info@verband.example"
        fed.save()
        nachbar = make_org("Nachbarverein Musterstadt", parent=fed)
        make_member(nachbar, "Gerd", "Gewechselt", email="gerd@nachbar.example")
    lower, upper = couple(net, world)
    return {"lower": lower, "upper": upper, "nachbar": nachbar}


def fed_circular(net, world, **extra):
    fed = world["fed"]
    with net.on(VERBAND):
        with tenant_context(fed.pk):
            circular = Circular.objects.create(
                organization=fed,
                audience="members",
                subject="Einladung zum Bundesfest",
                body="Hallo {Vorname},\n\nwir laden herzlich ein.",
                reply_to="info@verband.example",
                **extra,
            )
            from django.core.files.base import ContentFile

            CircularAttachment.objects.create(
                organization=fed,
                circular=circular,
                file=ContentFile(b"%PDF-1.4 erfunden", name="Programm.pdf"),
                name="Programm.pdf",
                size=17,
            )
            mail.outbox.clear()
            counts = circular_services.start_sending(circular, world["fed_board"])
    return circular, counts


class TestWeitergabePruefung:
    """Was von oben kommt, wird wie ein Upload behandelt (Härtung V6)."""

    def test_anhaenge_und_antwortadresse_geprueft(self, net, world, setup):
        import base64

        from peering import packet_circulars

        lower = setup["lower"]
        good = base64.b64encode(b"%PDF-1.4 erfunden").decode()
        bad = base64.b64encode(b"MZ kein pdf").decode()
        with net.on(VEREIN):
            packet_circulars.receive_forward(
                lower,
                {
                    "uid": "6f1c2b4e-0000-4000-8000-000000000001",
                    "subject": "Test",
                    "body": "Hallo",
                    "reply_to": "fremd@angreifer.example",
                    "attachments": [
                        {"name": "../../boese.exe", "data": bad},
                        {"name": "..\\Ordner\\Plan", "data": good},
                    ],
                },
            )
            with tenant_context(world["club"].pk):
                copy = Circular.objects.get(organization=world["club"], subject="Test")
                assert copy.reply_to == ""
                assert [a.name for a in copy.attachments.all()] == ["Plan.pdf"]


class TestWeitergabe:
    def test_entwurf_beim_verein_ohne_adressen_oben(self, net, world, setup):
        circular, counts = fed_circular(net, world)
        # Oben nur die eigenen Vereine: keine Adressen des fernen Vereins
        assert counts["mail"] == 1
        assert {m.to[0] for m in mail.outbox if m.subject == circular.subject} == {
            "gerd@nachbar.example"
        }
        copy = Circular.objects.get(organization=world["club"])
        assert copy.is_draft
        assert copy.body.startswith("Im Auftrag von Bürgerbund Musterstadt:")
        assert copy.reply_to == "info@verband.example"
        assert copy.attachments.get().name == "Programm.pdf"
        assert any("zur Weitergabe" in m.subject for m in mail.outbox)
        upper = RemoteCircular.objects.get(coupling=setup["upper"])
        assert upper.status == "draft"

    def test_verein_versendet_und_meldet_zahlen(self, net, world, setup):
        fed_circular(net, world)
        copy = Circular.objects.get(organization=world["club"])
        mail.outbox.clear()
        with net.on(VEREIN):
            with tenant_context(world["club"].pk):
                circular_services.start_sending(copy, world["club_board"])
        sent = [m for m in mail.outbox if m.subject == "Einladung zum Bundesfest"]
        assert sorted(m.to[0] for m in sent) == ["anna@verein.example", "bert@verein.example"]
        assert any("Hallo Anna" in m.body for m in sent)
        upper = RemoteCircular.objects.get(coupling=setup["upper"])
        assert upper.status == "sent"
        assert upper.report == {"mail": 2, "sent": 2, "failed": 0, "letter": 0}

    def test_automatisch_weitergeben(self, net, world, setup):
        with net.on(VEREIN):
            resp = api(world["club_board"]).patch(
                f"/api/orgs/{world['club'].pk}/peering/couplings/{setup['lower'].pk}/",
                {"options": {"circulars_auto": True}},
                content_type=JSON,
            )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["options"] == {"circulars_auto": True}
        fed_circular(net, world)
        copy = Circular.objects.get(organization=world["club"])
        assert not copy.is_draft
        upper = RemoteCircular.objects.get(coupling=setup["upper"])
        assert upper.status == "sent" and upper.report["sent"] == 2

    def test_ohne_freigabe_oder_nicht_gewaehlt(self, net, world, setup):
        with net.on(VERBAND):
            release(setup["upper"], {"unit": "on"})
        fed_circular(net, world)
        assert not Circular.objects.filter(organization=world["club"]).exists()
        with net.on(VERBAND):
            release(setup["upper"], {"unit": "on", "circulars": "on"})
        fed_circular(net, world, filters={"clubs": [setup["nachbar"].pk]})
        assert not Circular.objects.filter(organization=world["club"]).exists()
        fed_circular(net, world, filters={"clubs": [setup["upper"].remote_unit_id]})
        assert Circular.objects.filter(organization=world["club"]).count() == 1
