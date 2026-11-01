"""Sprache der Oberfläche (konzepte/englisch.md, Schritt Ü0)."""
# ruff: noqa: F811  (Fixtures aus test_m12_events als Parameter)

import pytest
from django.test import Client, override_settings
from django.utils import translation
from django.utils.translation import gettext

from accounts.models import User
from core import i18n
from organizations.models import Organization

from .conftest import csrf_headers
from .factories import make_user
from .test_app_devices import APP, app, member, pair, pairing_code, token  # noqa: F401
from .test_m12_events import JSON, cal, org_base  # noqa: F401

pytestmark = pytest.mark.django_db
URL = "/api/me/language/"
BOTH = override_settings(HUBIPLAN_LANGUAGES=["de", "en"])


def login(email: str) -> tuple[Client, dict[str, str], User]:
    user = make_user(email)
    c = Client(enforce_csrf_checks=True)
    c.force_login(user)
    return c, csrf_headers(c), user


def test_standard_ist_deutsch():
    user = make_user("neu@example.org")
    assert user.language == "de"
    assert Organization.objects.first() is None or Organization.objects.first().language == "de"


def test_ohne_freischaltung_nur_deutsch():
    c, headers, user = login("a@example.org")
    data = c.get(URL).json()
    assert [o["code"] for o in data["languages"]] == ["de"]
    resp = c.patch(URL, {"language": "en"}, content_type=JSON, headers=headers)
    assert resp.status_code == 400
    assert resp.json()["language"] == ["Diese Sprache gibt es nicht."]
    user.refresh_from_db()
    assert user.language == "de"


@BOTH
def test_sprache_im_profil_setzen():
    c, headers, user = login("b@example.org")
    data = c.get(URL).json()
    assert data["languages"] == [
        {"code": "de", "name": "Deutsch"},
        {"code": "en", "name": "English"},
    ]
    assert data["language"] == "de"
    resp = c.patch(URL, {"language": "en"}, content_type=JSON, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["language"] == "en"
    assert resp.cookies[i18n.COOKIE].value == "en"
    user.refresh_from_db()
    assert user.language == "en"
    # Die nächste Anfrage antwortet auf Englisch, auch mit deutschem Cookie
    c.cookies[i18n.COOKIE] = "de"
    resp = c.patch(URL, {"language": "fr"}, content_type=JSON, headers=headers)
    assert resp.headers["Content-Language"] == "en"
    assert resp.json()["language"] == ["This language is not available."]
    assert resp.cookies[i18n.COOKIE].value == "en"


@BOTH
def test_vor_der_anmeldung_cookie_statt_browsersprache():
    c = Client()
    # Die Browsersprache zählt nicht (Fachfrage F2)
    resp = c.get("/api/public/languages/", HTTP_ACCEPT_LANGUAGE="en")
    assert resp.headers["Content-Language"] == "de"
    c.cookies[i18n.COOKIE] = "en"
    resp = c.get("/api/public/languages/")
    assert resp.headers["Content-Language"] == "en"
    assert "language" not in resp.json()


def test_cookie_mit_nicht_freigeschalteter_sprache_bleibt_deutsch():
    c = Client()
    c.cookies[i18n.COOKIE] = "en"
    assert c.get("/api/public/languages/").headers["Content-Language"] == "de"


@BOTH
def test_sitzung_meldet_die_sprache():
    c, _, user = login("c@example.org")
    user.language = "en"
    user.save(update_fields=["language"])
    data = c.get("/_allauth/browser/v1/auth/session").json()
    assert data["data"]["user"]["language"] == "en"


@BOTH
def test_hilfsfunktionen_fuer_mails_und_belege():
    user = make_user("d@example.org")
    user.language = "en"
    with i18n.language_of(user):
        assert gettext("Diese Sprache gibt es nicht.") == "This language is not available."
    org = Organization(name="Testverein")
    with i18n.language_of_org(org):
        assert translation.get_language() == "de"
    assert i18n.normalize("EN") == "en"
    assert i18n.normalize("fr") == "de"


@BOTH
def test_app_liest_und_setzt_die_sprache(member, token):  # noqa: F811
    user, _ = member
    data = app(token).get(f"{APP}me/").json()
    assert data["user"]["language"] == "de"
    assert data["user"]["languages"] == ["de", "en"]
    resp = app(token).patch(f"{APP}me/language/", {"language": "en"}, content_type=JSON)
    assert resp.status_code == 200, resp.content
    user.refresh_from_db()
    assert user.language == "en"
    # Fehlermeldungen kommen danach auf Englisch
    resp = app(token).patch(f"{APP}me/language/", {"language": "xx"}, content_type=JSON)
    assert resp.json()["language"] == ["This language is not available."]


def test_abteilungsformen_auf_englisch():
    from organizations.terms import build_terms_en, department_terms, fill

    tm = build_terms_en("Abteilung", "Abteilungen")
    assert (tm["gen"], tm["ein"], tm["im"], tm["Pl"]) == (
        "the department",
        "a department",
        "in the department",
        "Departments",
    )
    assert build_terms_en("Einheit", "Einheiten")["ein"] == "a unit"
    assert build_terms_en("x", "y", "f")["adj"] == ""
    # Eigene Bezeichnung ohne englische Form bleibt deutsch, mit englischer Form englisch
    club = Organization(name="Testverein", type="club", label="Verein", department_label="Zug")
    club.department_label_plural = "Züge"
    club.department_label_gender = "m"
    with translation.override("en"):
        assert fill("Members of {gen}", club) == "Members of the Zug"
        club.department_label_en = "platoon"
        club.department_label_plural_en = "platoons"
        terms = department_terms(club)
        assert (terms["gen"], terms["ein"], terms["pl"]) == ("the platoon", "a platoon", "platoons")
        assert terms["e_im"] == "in the club"
    with translation.override("de"):
        assert department_terms(club)["gen"] == "des Zugs"


def test_rechtekatalog_auf_englisch():
    from access.catalog import catalog_for

    with translation.override("en"):
        modules = {m["id"]: m for m in catalog_for("club")}
    assert modules["members"]["label"] == "Members"
    assert modules["members"]["permissions"][0]["label"] == "Read members"
    with translation.override("de"):
        assert catalog_for("club")[0]["label"] == "Mitglieder"


# --- Schritt Ü4: Mails und Push in der Sprache des Empfängers ---


def _english_user(email: str) -> User:
    user = make_user(email)
    user.language = "en"
    user.save(update_fields=["language"])
    return user


@BOTH
def test_geraete_hinweis_in_der_sprache_des_kontos(mailoutbox, django_capture_on_commit_callbacks):
    from types import SimpleNamespace

    from devices import notify

    english = _english_user("en@example.org")
    german = make_user("de@example.org")
    device = SimpleNamespace(name="Pixel", pk=1)
    # Die Anfrage selbst läuft auf Deutsch: die Mail richtet sich nach dem Empfänger
    with translation.override("de"), django_capture_on_commit_callbacks(execute=True):
        notify.device_added(english, device)
        notify.device_added(german, device)
    en, de = mailoutbox
    assert en.subject == "New device connected to your account"
    assert "The device “Pixel” has been connected" in en.body
    assert "Time: " in en.body and " Uhr" not in en.body
    assert "This message was sent via HUBIplan." in en.body
    assert de.subject == "Neues Gerät mit deinem Zugang verbunden"
    assert "Diese Nachricht wurde über HUBIplan versandt." in de.body


@BOTH
def test_passwort_link_auf_englisch(mailoutbox):
    from accounts.invitations import send_password_link

    user = _english_user("pw@example.org")
    with translation.override("de"):
        assert send_password_link(user)
    (msg,) = mailoutbox
    assert msg.subject == "HUBIplan: set your password"
    assert msg.body.startswith("Hello,\n\nHUBIplan no longer sends initial passwords.")


@BOTH
def test_mailrahmen_sprache_und_fusszeile(mailoutbox):
    from outbox import mail

    with translation.override("de"):
        mail.send("x@example.org", "Test", "Text", html="<p>Text</p>", language="en")
        mail.send("y@example.org", "Test", "Text", html="<p>Text</p>")
    en, de = mailoutbox
    assert '<html lang="en">' in en.alternatives[0][0]
    assert ">Legal notice</a>" in en.alternatives[0][0]
    assert '<html lang="de">' in de.alternatives[0][0]
    assert ">Impressum</a>" in de.alternatives[0][0]


def test_mailrahmen_ohne_freischaltung_deutsch(mailoutbox):
    from outbox import mail

    mail.send("x@example.org", "Test", "Text", html="<p>Text</p>", language="en")
    assert '<html lang="de">' in mailoutbox[0].alternatives[0][0]


@BOTH
def test_push_titel_in_der_sprache_des_kontos(monkeypatch, member):  # noqa: F811
    from devices import push, tasks

    sent = []
    monkeypatch.setattr(push, "send_to_user", lambda user_id, data, **kw: sent.append(data) or 1)
    user, access = member
    user.language = "en"
    user.save(update_fields=["language"])
    tasks.notify_membership(access.membership_id, "Dein Foto wurde freigegeben", "Testverein")
    assert sent[0]["title"] == "Your photo has been approved"
    assert sent[0]["text"] == "Testverein"


@BOTH
def test_finanzbelege_bleiben_deutsch():
    import datetime

    from django.utils.translation import gettext_lazy

    with translation.override("en"):
        assert str(gettext_lazy("Zusage")) == "Yes"
        assert i18n.german(gettext_lazy("Zusage")) == "Zusage"
        assert i18n.date_text(datetime.date(2026, 11, 1)) == "01/11/2026"
    assert i18n.date_text(datetime.date(2026, 11, 1)) == "01.11.2026"
