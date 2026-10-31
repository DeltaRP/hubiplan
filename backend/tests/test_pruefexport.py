"""Vollständiger Prüfer-Export (A4) und Original-Kontoauszug (B3), erfundene Daten."""
# ruff: noqa: F811  (Fixtures als Parameter)

import hashlib
import io
import xml.etree.ElementTree as ET
import zipfile

import pytest

from finance.models import BankStatement

from .test_kontoauszug import camt_xml, entry, fin, upload  # noqa: F401
from .test_m9_billing import JSON, base, c, club, members, setup, zug  # noqa: F401

pytestmark = pytest.mark.django_db


def _zip(c, fin, year=2025):
    resp = c.get(f"{fin}/export/?jahr={year}")
    assert resp.status_code == 200
    return zipfile.ZipFile(io.BytesIO(b"".join(resp.streaming_content)))


def test_original_wird_mit_pruefsumme_gespeichert(c, fin):
    data = camt_xml([entry("10.00"), entry("5.00", False, name="Bäcker")])
    assert upload(c, fin, data, name="März 2025.xml").status_code == 201
    st = BankStatement.objects.get()
    assert st.source_sha256 == hashlib.sha256(data).hexdigest()
    with st.source.open("rb") as fh:
        assert fh.read() == data


def test_loeschen_entfernt_original(c, fin, django_capture_on_commit_callbacks):
    assert upload(c, fin, camt_xml([entry("10.00")])).status_code == 201
    st = BankStatement.objects.get()
    storage, name = st.source.storage, st.source.name
    assert storage.exists(name)
    with django_capture_on_commit_callbacks(execute=True):
        assert c.delete(f"{fin}/bank-statements/{st.pk}/").status_code == 204
    assert not storage.exists(name)


def test_export_enthaelt_alles_fuer_die_pruefung(c, fin):
    data = camt_xml([entry("10.00", purpose="Spende")])
    assert upload(c, fin, data).status_code == 201
    zf = _zip(c, fin)
    names = set(zf.namelist())
    assert {
        "buchungen.csv",
        "konten.csv",
        "quittungen.csv",
        "rechnungen.csv",
        "rechnungsposten.csv",
        "zahlungen.csv",
        "mahnungen.csv",
        "lastschriften.csv",
        "lastschriftposten.csv",
        "zuwendungen.csv",
        "zuwendungsbestaetigungen.csv",
        "kontoauszuege.csv",
        "kontoumsaetze.csv",
        "kassenzaehlungen.csv",
        "protokoll.csv",
        "index.xml",
        "LIESMICH.txt",
        "pruefsummen.txt",
    } <= names
    originals = [n for n in names if n.startswith("kontoauszuege/")]
    assert len(originals) == 1 and zf.read(originals[0]) == data
    assert "10,00" in zf.read("kontoumsaetze.csv").decode("utf-8-sig")
    assert "Kontoauszug" in zf.read("protokoll.csv").decode("utf-8-sig")

    # index.xml beschreibt jede CSV-Datei, und jede beschriebene Datei liegt bei
    root = ET.fromstring(zf.read("index.xml"))  # noqa: S314 (selbst erzeugt)
    urls = {u.text for u in root.iter("URL")}
    assert urls == {n for n in names if n.endswith(".csv")}

    # Prüfsummen stimmen
    for line in zf.read("pruefsummen.txt").decode().splitlines():
        digest, _, path = line.partition("  ")
        if path:
            assert hashlib.sha256(zf.read(path)).hexdigest() == digest


def test_export_zeigt_keine_daten_anderer_jahre(c, fin):
    assert upload(c, fin, camt_xml([entry("10.00")])).status_code == 201
    zf = _zip(c, fin, year=2024)
    assert not [n for n in zf.namelist() if n.startswith("kontoauszuege/")]
    assert "10,00" not in zf.read("kontoumsaetze.csv").decode("utf-8-sig")
