from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0041_homepage_vorschaubild"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="document_budget_gb",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="Speicherbudget Dokumente (GB)"
            ),
        ),
    ]
