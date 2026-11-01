"""Private Dateien verschlüsselt mit einem Schlüssel je Verein (core/crypto.py)."""

import io
import os

import pytest
from django.core.files.base import ContentFile
from django.core.management import call_command

from core import crypto
from core.models import DataKey
from core.privatefiles import local_copy
from exchange.models import ImportJob, private_storage

from .factories import make_org


@pytest.fixture(autouse=True)
def _private_root(settings, tmp_path):
    settings.PRIVATE_ROOT = tmp_path / "private"


def _version(org, content: bytes, name="protokoll.pdf"):
    job = ImportJob(organization=org, file_name=name)
    job.file.save(name, ContentFile(content), save=False)
    return job


def _raw(fieldfile) -> bytes:
    with open(fieldfile.storage.path(fieldfile.name), "rb") as handle:
        return handle.read()


class TestSchluesselquelle:
    def test_verpacken_und_entpacken(self):
        p = crypto.FileKeyProvider([crypto._b64(os.urandom(32))])
        key = os.urandom(32)
        wrapped = p.wrap(key, "org:5")
        assert wrapped.startswith("file:1:")
        assert p.unwrap(wrapped, "org:5") == key

    def test_falscher_verein_scheitert(self):
        p = crypto.FileKeyProvider([crypto._b64(os.urandom(32))])
        wrapped = p.wrap(os.urandom(32), "org:5")
        with pytest.raises(crypto.DecryptionError):
            p.unwrap(wrapped, "org:6")

    def test_schluesselwechsel(self):
        alt, neu = crypto._b64(os.urandom(32)), crypto._b64(os.urandom(32))
        key = os.urandom(32)
        wrapped = crypto.FileKeyProvider([alt]).wrap(key, "org:1")
        beide = crypto.FileKeyProvider([neu, alt])
        assert beide.unwrap(wrapped, "org:1") == key
        assert not beide.is_current(wrapped)
        with pytest.raises(crypto.DecryptionError):
            crypto.FileKeyProvider([neu]).unwrap(wrapped, "org:1")

    def test_hauptschluessel_aus_datei(self, settings, tmp_path):
        datei = tmp_path / "datenschluessel"
        datei.write_text("# Kommentar\n" + crypto._b64(os.urandom(32)) + "\n")
        settings.DATA_ENCRYPTION_KEY_FILE = str(datei)
        crypto.reset()
        assert crypto.unwrap_key(crypto.wrap_key(b"x" * 32, "org:1"), "org:1") == b"x" * 32

    def test_fehlende_datei_meldet_503(self, settings, tmp_path):
        settings.DATA_ENCRYPTION_KEY_FILE = str(tmp_path / "fehlt")
        crypto.reset()
        with pytest.raises(crypto.KeyUnavailable) as info:
            crypto.providers()
        assert info.value.status_code == 503
        assert not crypto.ready()


@pytest.mark.django_db
class TestDateien:
    def test_auf_der_platte_nur_chiffrat(self, orgs):
        inhalt = b"%PDF geheimes Protokoll " * 100
        version = _version(orgs["a"], inhalt)
        roh = _raw(version.file)
        assert roh.startswith(crypto.MAGIC)
        assert b"geheimes Protokoll" not in roh
        with version.file.open("rb") as handle:
            assert handle.read() == inhalt
        assert version.file.size == len(inhalt)

    def test_schluessel_je_verein(self, orgs):
        _version(orgs["a"], b"a")
        _version(orgs["b"], b"b")
        _version(orgs["a"], b"a2")
        keys = DataKey.objects.order_by("organization_id")
        assert [k.organization_id for k in keys] == sorted([orgs["a"].pk, orgs["b"].pk])
        assert all(k.wrapped.startswith("file:1:") for k in keys)

    def test_untereinheit_nutzt_schluessel_des_vereins(self, orgs):
        zug = make_org("1. Zug", "unit", parent=orgs["a"])
        _version(zug, b"zug")
        assert DataKey.objects.filter(organization=orgs["a"]).exists()
        assert not DataKey.objects.filter(organization=zug).exists()

    def test_grosse_datei_mit_springen(self, orgs):
        inhalt = os.urandom(3 * crypto.CHUNK + 123)
        version = _version(orgs["a"], inhalt, "gross.bin")
        with version.file.open("rb") as handle:
            handle.seek(crypto.CHUNK * 2 + 7)
            assert handle.read(10) == inhalt[crypto.CHUNK * 2 + 7 : crypto.CHUNK * 2 + 17]
            handle.seek(-5, io.SEEK_END)
            assert handle.read() == inhalt[-5:]
        assert version.file.size == len(inhalt)

    @pytest.mark.parametrize("laenge", [0, 1, crypto.CHUNK, crypto.CHUNK + 1, 2 * crypto.CHUNK])
    def test_blockgrenzen(self, orgs, laenge):
        inhalt = os.urandom(laenge)
        version = _version(orgs["a"], inhalt, f"x{laenge}.bin")
        assert version.file.size == laenge
        with version.file.open("rb") as handle:
            assert handle.read() == inhalt

    def test_abgeschnittene_datei_faellt_auf(self, orgs):
        version = _version(orgs["a"], os.urandom(2 * crypto.CHUNK + 10), "x.bin")
        path = version.file.storage.path(version.file.name)
        with open(path, "r+b") as handle:
            handle.truncate(crypto.HEADER + crypto.CHUNK + crypto.TAG)
        with pytest.raises(crypto.DecryptionError), version.file.open("rb") as handle:
            handle.read()

    def test_veraenderte_datei_faellt_auf(self, orgs):
        version = _version(orgs["a"], b"Inhalt" * 50)
        path = version.file.storage.path(version.file.name)
        roh = bytearray(_raw(version.file))
        roh[40] ^= 1
        with open(path, "wb") as handle:
            handle.write(roh)
        with pytest.raises(crypto.DecryptionError), version.file.open("rb") as handle:
            handle.read()

    def test_alte_klartextdatei_bleibt_lesbar(self, orgs, settings):
        os.makedirs(settings.PRIVATE_ROOT / "alt", exist_ok=True)
        (settings.PRIVATE_ROOT / "alt" / "a.txt").write_bytes(b"Klartext")
        with private_storage().open("alt/a.txt") as handle:
            assert handle.read() == b"Klartext"

    def test_lokale_kopie(self, orgs):
        version = _version(orgs["a"], b"Name;Vorname\n", "liste.csv")
        with local_copy(version.file, ".csv") as path:
            with open(path, "rb") as handle:
                assert handle.read() == b"Name;Vorname\n"
        assert not os.path.exists(path)

    def test_ohne_verein_im_strengen_modus_fehler(self, orgs):
        from django.core.exceptions import ImproperlyConfigured

        with pytest.raises(ImproperlyConfigured):
            private_storage().save("lose.txt", ContentFile(b"x"))

    def test_ohne_verein_sonst_plattformschluessel(self, orgs, settings):
        from organizations.models import Organization

        settings.DATA_ENCRYPTION_STRICT = False
        name = private_storage().save("lose.txt", ContentFile(b"x"))
        assert private_storage().is_encrypted(name)
        assert DataKey.objects.filter(organization=Organization.platform()).exists()

    def test_verein_geloescht_daten_unlesbar(self, orgs):
        version = _version(orgs["c"], b"weg")
        DataKey.objects.filter(organization=orgs["c"]).delete()
        crypto.reset()
        with pytest.raises(crypto.DecryptionError), version.file.open("rb") as handle:
            handle.read()


@pytest.mark.django_db
class TestKommandos:
    def test_verschluesseln_und_rueckweg(self, orgs, settings):
        version = _version(orgs["a"], b"neu")
        version.save()
        # Datei von vor der Umstellung: Klartext an derselben Stelle
        path = version.file.storage.path(version.file.name)
        with open(path, "wb") as handle:
            handle.write(b"alter Klartext")
        out = io.StringIO()
        call_command("dateien_verschluesseln", stdout=out)
        assert "1 Dateien verschlüsselt" in out.getvalue()
        assert _raw(version.file).startswith(crypto.MAGIC)
        with version.file.open("rb") as handle:
            assert handle.read() == b"alter Klartext"
        call_command("dateien_verschluesseln", stdout=out)
        assert "1 schon fertig" in out.getvalue()
        call_command("dateien_verschluesseln", "--entschluesseln", stdout=out)
        assert _raw(version.file) == b"alter Klartext"

    def test_umverpacken(self, orgs, settings):
        version = _version(orgs["a"], b"bleibt lesbar")
        alt = settings.DATA_ENCRYPTION_KEYS[0]
        neu = crypto._b64(os.urandom(32))
        settings.DATA_ENCRYPTION_KEYS = [neu, alt]
        crypto.reset()
        call_command("datenschluessel_umverpacken", stdout=io.StringIO())
        settings.DATA_ENCRYPTION_KEYS = [neu]
        crypto.reset()
        with version.file.open("rb") as handle:
            assert handle.read() == b"bleibt lesbar"
