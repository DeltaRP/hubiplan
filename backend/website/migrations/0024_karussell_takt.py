"""Bilderkarussell: Wechselzeit und zufälliges Startbild je Karussell (Ralf 01.11.)."""

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("website", "0023_bilderverwaltung"),
    ]

    operations = [
        migrations.AddField(
            model_name="websiterevision",
            name="gallery_interval",
            field=models.PositiveSmallIntegerField(default=7),
        ),
        migrations.AddField(
            model_name="websiterevision",
            name="gallery_random",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="websitetext",
            name="gallery_interval",
            field=models.PositiveSmallIntegerField(
                default=7,
                validators=[
                    django.core.validators.MinValueValidator(3),
                    django.core.validators.MaxValueValidator(30),
                ],
                verbose_name="Wechsel nach (Sekunden)",
            ),
        ),
        migrations.AddField(
            model_name="websitetext",
            name="gallery_random",
            field=models.BooleanField(
                default=False, verbose_name="zufälliges Startbild"
            ),
        ),
        migrations.AddField(
            model_name="websitetext",
            name="published_gallery_interval",
            field=models.PositiveSmallIntegerField(default=7),
        ),
        migrations.AddField(
            model_name="websitetext",
            name="published_gallery_random",
            field=models.BooleanField(default=False),
        ),
    ]
