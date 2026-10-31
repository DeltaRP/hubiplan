from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("organizations", "0035_beitragsfrei")]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="finance_locked_until",
            field=models.DateField(
                blank=True, null=True, verbose_name="Kasse festgeschrieben bis"
            ),
        ),
    ]
