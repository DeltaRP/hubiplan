from django.db import migrations, models


def fill(apps, schema_editor):
    """Bestehende Untereinheiten: selbst verwaltet, wenn sie schon Zugänge brauchen."""
    from core.tenancy import rls_bypass

    Organization = apps.get_model("organizations", "Organization")
    Role = apps.get_model("access", "Role")
    with rls_bypass():
        with_rights = set(
            Role.objects.filter(department__isnull=False)
            .exclude(permissions=[])
            .values_list("department_id", flat=True)
        )
        units = Organization.objects.filter(type="unit")
        units.filter(own_workspace=True).update(self_managed=True)
        units.filter(pk__in=with_rights).update(self_managed=True)


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0031_verbund_anmeldung"),
        ("access", "0011_eine_rollenart_rueckverweise"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="self_managed",
            field=models.BooleanField(
                default=False,
                help_text="Rolleninhaber der Untereinheit bekommen Zugänge mit Rechten.",
                verbose_name="verwaltet sich selbst",
            ),
        ),
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]
