"""Bilderverwaltung (Ralf 01.11.): Original und Ausschnitt aufbewahren, Bild einer
Untereinheit zuordnen, Fassung für neue Adressen nach neuem Ausschnitt.

Bestehende Bilder bekommen eine Zuordnung, wenn sie nur in Texten genau einer
Untereinheit stehen; alle anderen bleiben „Verein allgemein“."""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import exchange.models
import website.content_models


def assign_units(apps, schema_editor):
    WebsiteImage = apps.get_model("website", "WebsiteImage")
    WebsiteText = apps.get_model("website", "WebsiteText")
    texts = list(WebsiteText.objects.all())
    for image in WebsiteImage.objects.all():
        marker = f"bild:{image.key}"
        units = set()
        general = False
        for t in texts:
            if t.website_id != image.website_id:
                continue
            used = (
                image.pk in (t.image_id, t.published_image_id)
                or image.pk in (t.gallery or [])
                or image.pk in (t.published_gallery or [])
                or marker in (t.body or "")
                or marker in (t.published_body or "")
            )
            if not used:
                continue
            if t.kind == "unit" and t.department_id:
                units.add(t.department_id)
            else:
                general = True
        if len(units) == 1 and not general:
            image.department_id = units.pop()
            image.save(update_fields=["department"])


class Migration(migrations.Migration):
    dependencies = [
        ("website", "0022_wuerdentraeger_immer"),
        ("organizations", "0042_dokumentbudget"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="websiteimage",
            name="original",
            field=models.FileField(
                blank=True,
                storage=exchange.models.private_storage,
                upload_to=website.content_models.image_path,
                verbose_name="Original",
            ),
        ),
        migrations.AddField(
            model_name="websiteimage",
            name="crop",
            field=models.JSONField(blank=True, default=dict, verbose_name="Ausschnitt"),
        ),
        migrations.AddField(
            model_name="websiteimage",
            name="department",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="organizations.department",
                verbose_name="gehört zu",
            ),
        ),
        migrations.AddField(
            model_name="websiteimage",
            name="version",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="websiteimage",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="websiteimage",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(assign_units, migrations.RunPython.noop),
    ]
