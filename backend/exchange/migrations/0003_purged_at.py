from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("exchange", "0002_private_storage_callable")]

    operations = [
        migrations.AddField(
            model_name="exportjob",
            name="purged_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="importjob",
            name="purged_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
