from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0006_membership_pays_fee_self"),
    ]

    operations = [
        migrations.AddField(
            model_name="membership",
            name="info_opt_out_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Informationen per Mail abbestellt am"
            ),
        ),
    ]
