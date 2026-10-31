"""Eine Rollenart: Rückverweise unter den bisherigen Namen (nach dem Umzug)."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("access", "0010_eine_rollenart_umzug"),
        ("members", "0013_eine_rollenart"),
        ("organizations", "0028_eine_rollenart"),
    ]

    operations = [
        migrations.AlterField(
            model_name="role",
            name="department",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="unit_roles",
                to="organizations.department",
            ),
        ),
        migrations.AlterField(
            model_name="roleassignment",
            name="membership",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="department_roles",
                to="members.membership",
            ),
        ),
    ]
