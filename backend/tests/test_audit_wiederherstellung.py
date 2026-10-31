"""Regressionstests zum Datenaudit vom 25.10.2026: Wiederherstellbarkeit (DS06, K01, K04)."""

import datetime
import importlib
import os
import uuid

import pytest
from django.apps import apps
from django.core.files.base import ContentFile
from django.utils import timezone

from changes.models import ChangeRecord, ChangeSet
from circulars.models import Circular
from core.tenancy import rls_bypass, tenant_context
from documents import services as document_services
from documents.models import Document, DocumentVersion, Folder
from events.models import Event, EventCategory, EventException, EventResponse
from exchange.models import ExportTemplate, ImportTemplate
from members.models import Membership
from organizations.models import Organization

from .test_datatransfer import (  # noqa: F401
    _eager,
    _on_commit_now,
    as_doc,
    club_c,
    export,
    platform_admin,
    types,
    upload,
)

pytestmark = pytest.mark.django_db


class TestVollstaendigerExport:
    def test_ds06_termine_und_rueckmeldungen(self, api, club_c, board_c, platform_admin):  # noqa: F811
        club = club_c["club"]
        with tenant_context(club.pk):
            category = EventCategory.objects.create(organization=club, name="Versammlung")
            start = timezone.make_aware(datetime.datetime(2026, 3, 1, 19, 0))
            event = Event.objects.create(
                organization=club,
                title="Jahreshauptversammlung",
                category=category,
                starts_at=start,
                ends_at=start + datetime.timedelta(hours=2),
                rsvp_enabled=True,
            )
            serie = Event.objects.create(
                organization=club,
                department=club_c["dept"],
                title="Übungsabend",
                starts_at=start,
                ends_at=start + datetime.timedelta(hours=1),
                repeat="weekly",
            )
            EventException.objects.create(event=serie, original_start=start, is_cancelled=True)
            membership = Membership.objects.get(pk=club_c["erika"]["id"])
            EventResponse.objects.create(
                event=event, membership=membership, status="yes", guests=1, source="member"
            )
        content, _ = export(api(board_c), f"/api/orgs/{club.pk}")
        tables = as_doc(content)["organization"]["tables"]
        assert len(tables["events.event"]) == 2
        assert len(tables["events.eventresponse"]) == 1

        c = api(platform_admin)
        job = upload(c, "/api/platform", content)
        assert job["preview"]["error_count"] == 0, job["preview"]["errors"]
        c.post(f"/api/platform/datatransfer/imports/{job['id']}/run/")
        job = c.get(f"/api/platform/datatransfer/imports/{job['id']}/").json()
        assert job["status"] == "done", job
        with rls_bypass():
            new = Organization.objects.get(pk=job["result_organization"]["id"])
            events = {e.title: e for e in Event.objects.filter(organization=new)}
            assert events["Jahreshauptversammlung"].category.name == "Versammlung"
            assert events["Übungsabend"].department.organization == new
            assert events["Übungsabend"].exceptions.get().is_cancelled
            response = EventResponse.objects.get(event=events["Jahreshauptversammlung"])
            assert response.membership.organization == new
            assert response.membership.person.last_name == "Muster"
            assert (response.status, response.guests) == ("yes", 1)


class TestEinheitenMigration:
    def test_k01_json_verweise_auf_abteilungen(self, orgs):
        migration = importlib.import_module("organizations.migrations.0014_einheiten")
        club = orgs["a"]
        with tenant_context(club.pk):
            circular = Circular.objects.create(
                organization=club, subject="Info", filters={"departments": [11, 12, 99]}
            )
            template = ExportTemplate.objects.create(
                organization=club, name="Zug", columns=["name"], filters={"abteilung": "11"}
            )
            gone = ExportTemplate.objects.create(
                organization=club, name="Alt", columns=["name"], filters={"abteilung": 99}
            )
            imp = ImportTemplate.objects.create(
                organization=club,
                name="Liste",
                mapping={},
                value_mapping={"departments": {"Jägerzug": "12", "Alt": "99"}, "x": {"a": "1"}},
            )
        with rls_bypass():
            migration.remap_json_references(apps, "default", {11: 511, 12: 512})
            circular.refresh_from_db()
            template.refresh_from_db()
            gone.refresh_from_db()
            imp.refresh_from_db()
        assert circular.filters["departments"] == [511, 512]
        assert template.filters == {"abteilung": "511"}
        assert gone.filters == {}
        assert imp.value_mapping == {"departments": {"Jägerzug": "512"}, "x": {"a": "1"}}


class TestDateienBereinigen:
    def test_k04_datei_bleibt_solange_rueckgaengig_moeglich(self, orgs, settings, tmp_path):
        settings.PRIVATE_ROOT = tmp_path / "private"
        club = orgs["a"]
        with tenant_context(club.pk):
            folder = Folder.objects.create(
                organization=club, name="Protokolle", public_key=Folder.new_key()
            )
            doc = Document.objects.create(organization=club, folder=folder, title="JHV")
            version = DocumentVersion(
                organization=club, document=doc, name="jhv.pdf", size=3, content_type="x"
            )
            version.file.save("jhv.pdf", ContentFile(b"PDF"), save=False)
            version.save()
            storage, path = version.file.storage, version.file.name
            # Gerade gelöscht – die Datei selbst ist aber schon alt
            change_set = ChangeSet.objects.create(id=uuid.uuid4(), organization=club)
            ChangeRecord.objects.create(
                organization=club,
                change_set=change_set,
                seq=1,
                model="documents.documentversion",
                object_id=str(version.pk),
                operation="delete",
                before={"id": version.pk, "file": path},
            )
            version.delete()
        # Die Datei selbst ist schon 40 Tage alt
        old = (timezone.now() - datetime.timedelta(days=40)).timestamp()
        os.utime(storage.path(path), (old, old))
        document_services.purge()
        assert storage.exists(path)
        # Nach Ablauf des Pakets (30 Tage) darf die Datei weg
        document_services.purge(timezone.now() + datetime.timedelta(days=31))
        assert not storage.exists(path)
