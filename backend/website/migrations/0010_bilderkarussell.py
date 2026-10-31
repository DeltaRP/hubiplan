from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("website", "0009_termine_von_oben"),
    ]

    operations = [
        migrations.AddField(
            model_name="websitetext",
            name="gallery",
            field=models.JSONField(blank=True, default=list, verbose_name="Bilderkarussell"),
        ),
        migrations.AddField(
            model_name="websitetext",
            name="published_gallery",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="websiterevision",
            name="gallery",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
