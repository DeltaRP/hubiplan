"""Eine Reihenfolge der Rollen für HUBIplan und Webseite (Ralf 31.10.).

Bisher gab es „Reihenfolge“ und „Reihenfolge auf der Webseite“ als Zahlenfelder.
Jetzt legt man die Reihenfolge per Ziehen fest. Startwert ist die bisher gezeigte
Reihenfolge: Rollen der Einheit wie in der Rollenliste (zuerst die auf der Webseite,
nach ihrer Webseiten-Reihenfolge), Rollen einer Untereinheit wie auf der Webseite.
"""

from itertools import groupby

from django.db import migrations


def renumber(apps, schema_editor):
    from core.tenancy import rls_bypass

    Role = apps.get_model("access", "Role")
    with rls_bypass():
        own = Role.objects.filter(department__isnull=True).order_by(
            "organization_id", "-on_website", "website_position", "position", "name"
        )
        units = Role.objects.filter(department__isnull=False).order_by(
            "department_id", "website_position", "position", "name"
        )
        changed = []
        for rows, key in ((own, "organization_id"), (units, "department_id")):
            for _, group in groupby(rows, key=lambda r: getattr(r, key)):
                for i, role in enumerate(group, start=1):
                    if role.position != i or role.website_position != i:
                        role.position = i
                        role.website_position = i
                        changed.append(role)
        Role.objects.bulk_update(changed, ["position", "website_position"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("access", "0011_eine_rollenart_rueckverweise")]

    operations = [migrations.RunPython(renumber, migrations.RunPython.noop)]
