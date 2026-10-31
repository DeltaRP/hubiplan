"""Ämter: frühere Inhaber als freie Namenseinträge (Ralf 2026-10-31)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("access", "0013_aemter")]

    operations = [
        migrations.AddField(
            model_name="roleassignment",
            name="name",
            field=models.CharField(
                blank=True, max_length=200, verbose_name="Name (früherer Inhaber)"
            ),
        ),
    ]
