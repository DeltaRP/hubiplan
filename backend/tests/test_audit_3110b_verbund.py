"""Gesamtaudit 31.10.b: Verbund, Finanzexport, Backup-Stand, Excel-Grenzen (erfundene Daten)."""

import io
import time
import zipfile

import pytest

from core import backup_status
from exchange.reading import ReadError, _check_zip
from finance.gobd_export import _csv
from peering import services

from .test_verbund_kopplung import VEREIN, _setup, couple, net, world  # noqa: F401

pytestmark = pytest.mark.django_db


# --- INF-S01: Rundschreiben und Rechnungen nur mit Zustimmung des Empfängers ---


def test_rundschreiben_und_rechnungen_nur_mit_zustimmung(net, world):  # noqa: F811
    lower, _ = couple(net, world)
    with net.on(VEREIN):
        lower.refresh_from_db()
        accepted = services.accepted(lower)
        assert {"circulars", "invoices"} <= set(accepted)
        lower.options = {
            **(lower.options or {}),
            "accept": {k: v for k, v in accepted.items() if k not in ("circulars", "invoices")},
        }
        lower.save(update_fields=["options"])
        for kind in ("circular.forward", "invoice.issue"):
            with pytest.raises(services.Refused) as exc:
                services._process(lower, kind, {"uid": "erfunden-1"})
            assert exc.value.status == 422


# --- FIN-S03: Formeln im Prüfexport als Text ---


def test_pruefexport_neutralisiert_formeln():
    text = _csv([["=SUMME(A1)", "+49 171", "@Kasse", "-12,50", "-1.234,00", "Beitrag"]])
    line = text.decode("utf-8-sig").strip()
    assert line == "'=SUMME(A1);'+49 171;'@Kasse;-12,50;-1.234,00;Beitrag"


# --- INF-F03/F04: Backup-Stand ---


def test_backup_stand_meldet_fehler_luecken_und_alter():
    now = time.time()
    assert backup_status.problem({"state": "ok", "last_ok": str(int(now))}, now, 26) is None
    assert "fehlgeschlagen" in backup_status.problem(
        {"state": "fehler", "last_ok": str(int(now)), "text": "pg_dump"}, now, 26
    )
    assert "unvollständig" in backup_status.problem(
        {"state": "unvollstaendig", "last_ok": str(int(now)), "text": "2 Dateien fehlen"}, now, 26
    )
    old = str(int(now - 30 * 3600))
    assert "seit 30 Stunden" in backup_status.problem({"state": "ok", "last_ok": old}, now, 26)
    assert "noch keinen Stand" in backup_status.problem(None, now, 26)


def test_backup_alarm_einmal_je_tag(tmp_path, settings):
    from django.core import mail

    settings.SECURITY_ALERTS = True
    settings.SECURITY_ALERT_EMAIL = "betrieb@example.org"
    settings.BACKUP_STATUS_DIR = str(tmp_path)
    (tmp_path / "status").write_text("state=fehler\nlast_ok=0\ntext=pg_dump abgebrochen\n")
    assert "fehlgeschlagen" in backup_status.check_backup()
    backup_status.check_backup()
    subjects = [m.subject for m in mail.outbox if "Backup prüfen" in m.subject]
    assert len(subjects) == 1


def test_ohne_statusordner_nichts_zu_tun(settings):
    settings.BACKUP_STATUS_DIR = ""
    assert backup_status.check_backup() is None


# --- INF-S02: Excel-Datei entpackt begrenzt ---


def test_excel_entpackt_zu_gross(tmp_path):
    path = tmp_path / "liste.xlsx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/sharedStrings.xml", "a" * (5 * 1024 * 1024))
    with pytest.raises(ReadError):
        _check_zip(path)
    ok = io.BytesIO()
    with zipfile.ZipFile(ok, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml", "<workbook>Mitglieder</workbook>")
    small = tmp_path / "klein.xlsx"
    small.write_bytes(ok.getvalue())
    _check_zip(small)
