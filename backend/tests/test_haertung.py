"""Härtung: Postausgang-Frist und Django-Admin im Serverbetrieb."""

import datetime

import pytest
from django.utils import timezone

from outbox.backend import attachment_dir
from outbox.models import OutgoingMail
from outbox.purge import EMPTIED, purge_sent

pytestmark = pytest.mark.django_db


def _mail(org, status, days_old, attachments=None):
    mail = OutgoingMail.objects.create(
        organization=org,
        to="a@example.org",
        subject="Rechnung",
        body="Hallo Erika Mustermann, IBAN DE…",
        attachments=attachments or [],
        kind="rechnung",
        status=status,
    )
    OutgoingMail.objects.filter(pk=mail.pk).update(
        created_at=timezone.now() - datetime.timedelta(days=days_old)
    )
    return mail


def test_alte_zugestellte_mails_werden_geleert(orgs, settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"
    settings.OUTBOX_RETENTION_DAYS = 30
    folder = attachment_dir()
    folder.mkdir(parents=True)
    alt = folder / "alt.pdf"
    alt.write_bytes(b"pdf")
    geteilt = folder / "geteilt.pdf"
    geteilt.write_bytes(b"pdf")
    fremd = tmp_path / "private" / "documents" / "satzung.pdf"
    fremd.parent.mkdir(parents=True)
    fremd.write_bytes(b"pdf")

    def att(path):
        return {"name": path.name, "path": str(path.relative_to(settings.PRIVATE_ROOT))}

    old = _mail(orgs["a"], OutgoingMail.Status.SENT, 40, [att(alt), att(geteilt), att(fremd)])
    new = _mail(orgs["a"], OutgoingMail.Status.SENT, 5, [att(geteilt)])
    failed = _mail(orgs["a"], OutgoingMail.Status.FAILED, 40)
    stored = _mail(orgs["a"], OutgoingMail.Status.STORED, 40)

    assert purge_sent() == 1

    old.refresh_from_db()
    assert old.body == EMPTIED and old.attachments == []
    # Nachweis bleibt
    assert old.to == "a@example.org" and old.subject == "Rechnung" and old.kind == "rechnung"
    for mail in (new, failed, stored):
        mail.refresh_from_db()
        assert mail.body.startswith("Hallo")
    assert not alt.exists()
    # noch von einer neueren Mail genutzt bzw. gehört nicht dem Postausgang
    assert geteilt.exists() and fremd.exists()
    # Zweiter Lauf ändert nichts mehr
    assert purge_sent() == 0


@pytest.fixture
def reload_urls(settings):
    import importlib

    from django.urls import clear_url_caches

    import config.urls

    def _reload():
        clear_url_caches()
        importlib.reload(config.urls)

    yield _reload
    settings.ADMIN_ENABLED = True
    _reload()


def test_admin_im_serverbetrieb_aus(client, settings, reload_urls):
    settings.ADMIN_ENABLED = False
    reload_urls()
    assert client.get("/admin/").status_code == 404
    settings.ADMIN_ENABLED = True
    reload_urls()
    assert client.get("/admin/").status_code == 302


# --- Alarm-Mails ---


def _alarme():
    from django.core import mail

    return [m for m in mail.outbox if m.subject.startswith("[HUBIplan-Sicherheit]")]


def test_alarm_bei_neuem_superuser_und_plattformzugang(settings, django_user_model):
    from access.catalog import PLATFORM_MANAGE
    from organizations.models import Organization

    from .factories import give_role, make_user

    settings.SECURITY_ALERTS = True
    django_user_model.objects.create_superuser(email="chef@example.org", password="x-Test-12345")
    mails = _alarme()
    assert len(mails) == 1
    assert "Superuser" in mails[0].subject and mails[0].to == ["chef@example.org"]
    assert "chef@example.org" in mails[0].body

    settings.SECURITY_ALERT_EMAIL = "alarm@example.org"
    neu = make_user("neu@example.org")
    give_role(neu, Organization.platform(), [PLATFORM_MANAGE], name="Plattform")
    mails = _alarme()
    assert len(mails) == 2
    assert "Plattformzugang" in mails[1].subject and mails[1].to == ["alarm@example.org"]
    assert "neu@example.org" in mails[1].body


def test_kein_alarm_bei_vereinsrolle(settings, orgs):
    from .factories import give_role, make_user

    settings.SECURITY_ALERTS = True
    settings.SECURITY_ALERT_EMAIL = "alarm@example.org"
    give_role(make_user("vorstand@example.org"), orgs["a"], ["members.view"])
    assert _alarme() == []


def test_alarm_bei_grossem_export(settings, orgs):
    from core import alarm

    from .factories import make_user

    settings.SECURITY_ALERTS = True
    settings.SECURITY_ALERT_EMAIL = "alarm@example.org"
    settings.ALERT_EXPORT_ROWS = 200
    user = make_user("kassierer@example.org")
    alarm.export_finished(orgs["a"], user, "Liste (members)", 199)
    assert _alarme() == []
    alarm.export_finished(orgs["a"], user, "Liste (members)", 200)
    alarm.export_finished(orgs["a"], user, "vollständiger Datenexport", None)
    mails = _alarme()
    assert len(mails) == 2
    assert "200 Datensätze" in mails[0].subject
    assert "kassierer@example.org" in mails[0].body
    assert "alle Daten" in mails[1].subject
