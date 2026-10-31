import uuid

from django.db import migrations, models


def fill(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    for pk in Organization.objects.values_list("pk", flat=True):
        Organization.objects.filter(pk=pk).update(uuid=uuid.uuid4())


class Migration(migrations.Migration):
    dependencies = [("organizations", "0028_eine_rollenart")]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="uuid",
            field=models.UUIDField(editable=False, null=True, verbose_name="feste Kennung"),
        ),
        migrations.RunPython(fill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="organization",
            name="uuid",
            field=models.UUIDField(
                default=uuid.uuid4, editable=False, unique=True, verbose_name="feste Kennung"
            ),
        ),
    ]
