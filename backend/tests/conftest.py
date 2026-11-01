import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.test import Client

from .factories import PASSWORD, give_role, make_org, make_user


def pytest_configure(config):
    # Schneller Hasher nur in Tests: PBKDF2 mit 1 Mio. Runden kostet je Passwort ~0,2 s,
    # bei Tausenden Testzugängen ein gutes Viertel der Laufzeit. Im Betrieb bleibt PBKDF2.
    django_settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def pytest_collection_modifyitems(config, items):
    # Langsame Tests zuerst: Mit pytest-xdist hängen sie sonst am Ende allein auf einem Kern.
    # Zusammen mit --maxschedchunk=2 (scripts/test.sh) landen sie auf verschiedenen Workern.
    items.sort(key=lambda item: item.get_closest_marker("langsam") is None)


# Zeilen aus Datenmigrationen (z. B. die Plattform-Organisation). Tests mit
# transaction=True leeren am Ende alle Tabellen; danach fehlen diese Zeilen den folgenden
# Tests im selben Worker, und deren Ergebnis hinge von der Reihenfolge ab.
_migrationsdaten: list = []
_db_blocker = None


@pytest.fixture(scope="session", autouse=True)
def _migrationsdaten_merken(django_db_setup, django_db_blocker):
    global _db_blocker
    from django.apps import apps
    from django.core import serializers

    _db_blocker = django_db_blocker
    with django_db_blocker.unblock():
        objs = [
            obj
            for model in apps.get_models()
            if model._meta.managed
            and not model._meta.proxy
            and model._meta.app_label not in ("auth", "contenttypes")
            for obj in model._base_manager.all()
        ]
        daten = serializers.serialize("json", objs)
    _migrationsdaten[:] = list(serializers.deserialize("json", daten))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    result = yield
    marker = item.get_closest_marker("django_db")
    transactional = (marker and marker.kwargs.get("transaction")) or (
        "transactional_db" in getattr(item, "fixturenames", ())
    )
    # Letzter Test eines Workers (nextitem None): Die Test-Datenbank ist dann schon
    # abgebaut, Zurückschreiben schlüge fehl und wäre ohnehin überflüssig.
    if transactional and nextitem is not None and _db_blocker is not None:
        from django.db import transaction

        with _db_blocker.unblock(), transaction.atomic():
            for obj in _migrationsdaten:
                obj.save()
    return result


@pytest.fixture(autouse=True)
def _clear_cache():
    # allauth merkt sich verwendete TOTP-Codes und Fehlversuche im Cache.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _media_root(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    # VAPID-Schlüssel für Push je Test neu (nicht im Arbeitsverzeichnis)
    settings.PUSH_VAPID_KEY_FILE = str(tmp_path / "vapid.json")
    # Alarm-Mails nur in den Tests, die sie prüfen (sonst zählen sie im Postausgang mit)
    settings.SECURITY_ALERTS = False
    # Jede private Datei muss einem Verein zugeordnet sein (core/crypto.py)
    settings.DATA_ENCRYPTION_STRICT = True
    from core import crypto

    crypto.reset()


@pytest.fixture
def password() -> str:
    return PASSWORD


@pytest.fixture
def user(db, django_user_model):
    return django_user_model.objects.create_user(
        email="kassenwart@example.org", password=PASSWORD, first_name="Karla"
    )


@pytest.fixture
def client() -> Client:
    # Wie der Browser: CSRF-Prüfung ist aktiv.
    return Client(enforce_csrf_checks=True)


def csrf_headers(client: Client) -> dict[str, str]:
    """Holt das CSRF-Cookie und gibt den passenden Header zurück."""
    client.get("/api/csrf/")
    return {"X-CSRFToken": client.cookies["csrftoken"].value}


@pytest.fixture
def orgs(db):
    """Ein Dachverband mit zwei Vereinen und ein Verein ohne Dachverband."""
    federation = make_org("Testbund", "federation")
    club_a = make_org("Verein A", parent=federation)
    club_b = make_org("Verein B", parent=federation)
    club_c = make_org("Verein C ohne Verband")
    return {"federation": federation, "a": club_a, "b": club_b, "c": club_c}


@pytest.fixture
def board_a(orgs):
    user = make_user("vorstand-a@example.org")
    give_role(user, orgs["a"])
    return user


@pytest.fixture
def board_b(orgs):
    user = make_user("vorstand-b@example.org")
    give_role(user, orgs["b"])
    return user


@pytest.fixture
def board_c(orgs):
    user = make_user("vorstand-c@example.org")
    give_role(user, orgs["c"])
    return user


@pytest.fixture
def api():
    """API-Client ohne CSRF-Prüfung, angemeldet per force_login."""

    def _client(user):
        c = Client()
        c.force_login(user)
        return c

    return _client
