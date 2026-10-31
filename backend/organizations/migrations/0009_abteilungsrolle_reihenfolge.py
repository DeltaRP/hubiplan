from django.db import migrations, models


def number_existing(apps, schema_editor):
    """Vorhandene Rollen je Abteilung in bisheriger (alphabetischer) Reihenfolge nummerieren."""
    DepartmentRole = apps.get_model("organizations", "DepartmentRole")
    current, position = None, 0
    for role in DepartmentRole.objects.order_by("department_id", "name"):
        if role.department_id != current:
            current, position = role.department_id, 0
        position += 1
        role.position = position
        role.save(update_fields=["position"])


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0008_kontaktdaten_bestaetigung"),
    ]

    operations = [
        migrations.AddField(
            model_name="departmentrole",
            name="position",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="Reihenfolge"),
        ),
        migrations.AlterModelOptions(
            name="departmentrole",
            options={
                "ordering": ["position", "name"],
                "verbose_name": "Abteilungsrolle",
                "verbose_name_plural": "Abteilungsrollen",
            },
        ),
        migrations.RunPython(number_existing, migrations.RunPython.noop),
    ]
