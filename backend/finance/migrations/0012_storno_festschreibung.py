import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0011_zuwendungen_steuerbeguenstigt"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="cancels",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cancellation",
                to="finance.booking",
                verbose_name="storniert Buchung",
            ),
        ),
        migrations.AddField(
            model_name="booking",
            name="cancel_reason",
            field=models.CharField(blank=True, max_length=300, verbose_name="Grund des Stornos"),
        ),
        migrations.AddField(
            model_name="receipt",
            name="hidden_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="ausgeblendet am"),
        ),
        migrations.AddField(
            model_name="receipt",
            name="hidden_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="receipt",
            name="hidden_reason",
            field=models.CharField(blank=True, max_length=300, verbose_name="Grund"),
        ),
    ]
