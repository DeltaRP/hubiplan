# ruff: noqa: F811  (Fixtures aus test_m5_exchange)
"""Gesamtaudit 30.10.a (B-S03): Listen-Exporte 7 Tage, Importe 30 Tage aufbewahren."""

import datetime
import os

import pytest
from django.utils import timezone

from audit.models import AuditEntry
from exchange import tasks
from exchange.models import ExportJob, ImportJob, private_storage
from members.models import Membership

from .test_m2_members import admit
from .test_m5_exchange import JSON, awards, base_rows, configure, types, upload  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _eager(settings, tmp_path):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.PRIVATE_ROOT = tmp_path / "private"


def _age(model, pk, days, **fields):
    past = timezone.now() - datetime.timedelta(days=days)
    model.objects.filter(pk=pk).update(**{f: past for f in fields or ["created_at"]})


def _export(c, org):
    resp = c.post(
        f"/api/orgs/{org.pk}/exports/",
        {"kind": "members", "file_format": "xlsx", "columns": ["last_name"]},
        content_type=JSON,
    )
    assert resp.status_code == 201, resp.json()
    return ExportJob.objects.get(pk=resp.json()["id"])


class TestExporte:
    def test_nach_sieben_tagen_geloescht(self, api, orgs, types, board_a):
        c = api(board_a)
        org = orgs["a"]
        admit(c, org, types["a"]["aktiv"], last_name="Adler")
        alt, neu = _export(c, org), _export(c, org)
        path = alt.file.path
        assert os.path.exists(path)
        _age(ExportJob, alt.pk, 8, finished_at=True, created_at=True)
        _age(ExportJob, neu.pk, 6, finished_at=True, created_at=True)

        counts = tasks.purge_expired()

        assert counts["exports"] == 1
        assert not os.path.exists(path)
        alt.refresh_from_db()
        assert alt.purged_at and not alt.file
        assert c.get(f"/api/orgs/{org.pk}/exports/{alt.pk}/").json()["purged_at"]
        resp = c.get(f"/api/orgs/{org.pk}/exports/{alt.pk}/download/")
        assert resp.status_code == 400
        assert "7 Tagen" in str(resp.json())
        # der jüngere bleibt abrufbar
        assert c.get(f"/api/orgs/{org.pk}/exports/{neu.pk}/download/").status_code == 200


class TestImporte:
    def _imported(self, c, org, types, awards):
        job = upload(c, org, base_rows()).json()
        configure(c, org, job, types, awards)
        c.post(f"/api/orgs/{org.pk}/imports/{job['id']}/validate/")
        done = c.post(f"/api/orgs/{org.pk}/imports/{job['id']}/run/").json()
        assert done["status"] == "imported", done
        return ImportJob.objects.get(pk=job["id"])

    def test_rueckgaengig_innerhalb_der_frist(self, api, orgs, types, board_a, awards):
        c = api(board_a)
        org = orgs["a"]
        job = self._imported(c, org, types["a"], awards)
        _age(ImportJob, job.pk, 29, created_at=True, imported_at=True)
        # die importierten Mitgliedschaften entsprechend älter machen
        past = timezone.now() - datetime.timedelta(days=30)
        Membership.objects.filter(pk__in=job.created["memberships"]).update(updated_at=past)
        AuditEntry.objects.filter(organization=org).update(timestamp=past)
        assert tasks.purge_expired()["imports"] == 0
        resp = c.post(f"/api/orgs/{org.pk}/imports/{job.pk}/undo/")
        assert resp.status_code == 200, resp.json()

    def test_nach_dreissig_tagen_geloescht(
        self, api, orgs, types, board_a, awards, django_capture_on_commit_callbacks
    ):
        c = api(board_a)
        org = orgs["a"]
        job = self._imported(c, org, types["a"], awards)
        paths = [job.file.path, job.error_file.path]
        assert all(os.path.exists(p) for p in paths)
        _age(ImportJob, job.pk, 31, created_at=True, imported_at=True)

        # Dateien werden erst nach dem Speichern gelöscht (Audit 31.10. R-X-01)
        with django_capture_on_commit_callbacks(execute=True):
            assert tasks.purge_expired()["imports"] == 1

        assert not any(os.path.exists(p) for p in paths)
        job.refresh_from_db()
        assert job.purged_at
        assert (job.headers, job.sample, job.preview, job.created) == ([], [], [], {})
        data = c.get(f"/api/orgs/{org.pk}/imports/{job.pk}/").json()
        assert "abgelaufen" in data["undo_blockers"][0]
        for action in ("undo", "validate", "run"):
            assert c.post(f"/api/orgs/{org.pk}/imports/{job.pk}/{action}/").status_code == 400
        assert c.get(f"/api/orgs/{org.pk}/imports/{job.pk}/errors/").status_code == 400
        resp = c.patch(f"/api/orgs/{org.pk}/imports/{job.pk}/", {"options": {}}, content_type=JSON)
        assert resp.status_code == 400

    def test_frist_ab_dem_letzten_schritt(self, api, orgs, types, board_a, awards):
        # vor 40 Tagen hochgeladen, aber erst vor 10 Tagen importiert: bleibt
        c = api(board_a)
        job = self._imported(c, orgs["a"], types["a"], awards)
        _age(ImportJob, job.pk, 40, created_at=True)
        _age(ImportJob, job.pk, 10, imported_at=True)
        assert tasks.purge_expired()["imports"] == 0

    def test_nie_geprueft_nach_dreissig_tagen(self, api, orgs, types, board_a):
        c = api(board_a)
        job = upload(c, orgs["a"], base_rows()).json()
        _age(ImportJob, job["id"], 31)
        assert tasks.purge_expired()["imports"] == 1


def test_verwaiste_dateien(settings):
    # Lose Dateien ohne Datensatz (sonst ordnet PrivateFileField sie einem Verein zu)
    settings.DATA_ENCRYPTION_STRICT = False
    storage = private_storage()
    alt = storage.save("exports/99/vergessen.xlsx", _content())
    neu = storage.save("imports/99/gerade.xlsx", _content())
    old = (timezone.now() - datetime.timedelta(days=2)).timestamp()
    os.utime(storage.path(alt), (old, old))

    assert tasks.purge_expired()["orphans"] == 1
    assert not storage.exists(alt)
    assert storage.exists(neu)  # jünger als ein Tag: womöglich noch in Arbeit


def _content():
    from django.core.files.base import ContentFile

    return ContentFile(b"x")
