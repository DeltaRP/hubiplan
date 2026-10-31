"""Eine Rollenart: neue Felder an Rolle und Rollenzuordnung (Umzug in 0010)."""

import access.models
import django.db.models.deletion
import django.db.models.manager
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("access", "0008_webseite"),
        ("members", "0012_geschlecht"),
        ("organizations", "0026_termine_weitergabe"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="role",
            options={
                "default_manager_name": "all_objects",
                "ordering": ["position", "name"],
                "verbose_name": "Rolle",
                "verbose_name_plural": "Rollen",
            },
        ),
        migrations.AlterModelOptions(
            name="roleassignment",
            options={
                "default_manager_name": "all_objects",
                "ordering": ["-valid_from"],
                "verbose_name": "Rollenzuordnung",
                "verbose_name_plural": "Rollenzuordnungen",
            },
        ),
        migrations.AlterModelManagers(
            name="role",
            managers=[
                ("all_objects", django.db.models.manager.Manager()),
                ("objects", access.models.OrgRoleManager()),
            ],
        ),
        migrations.AlterModelManagers(
            name="roleassignment",
            managers=[
                ("all_objects", django.db.models.manager.Manager()),
                ("objects", access.models.OrgAssignmentManager()),
            ],
        ),
        migrations.RemoveConstraint(
            model_name="role",
            name="rolle_name_je_org",
        ),
        migrations.AddField(
            model_name="role",
            name="department",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="organizations.department",
            ),
        ),
        migrations.AddField(
            model_name="role",
            name="position",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Reihenfolge"),
        ),
        migrations.AddField(
            model_name="roleassignment",
            name="membership",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="members.membership",
            ),
        ),
        migrations.AlterField(
            model_name="roleassignment",
            name="role",
            field=models.ForeignKey(
                on_delete=access.models.protect_unit_holders,
                related_name="assignments",
                to="access.role",
            ),
        ),
        migrations.AddConstraint(
            model_name="role",
            constraint=models.UniqueConstraint(
                condition=models.Q(("department__isnull", True)),
                fields=("organization", "name"),
                name="rolle_name_je_org",
            ),
        ),
        migrations.AddConstraint(
            model_name="role",
            constraint=models.UniqueConstraint(
                condition=models.Q(("department__isnull", False)),
                fields=("department", "name"),
                name="rolle_name_je_untereinheit",
            ),
        ),
    ]
