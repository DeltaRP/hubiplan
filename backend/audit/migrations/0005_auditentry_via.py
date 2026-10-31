from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0004_auditentry_change_set"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditentry",
            name="via",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
    ]
