import exchange.models
import finance.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("finance", "0012_storno_festschreibung")]

    operations = [
        migrations.AddField(
            model_name="bankstatement",
            name="source",
            field=models.FileField(
                blank=True,
                storage=exchange.models.private_storage,
                upload_to=finance.models.bank_statement_path,
                verbose_name="Originaldatei",
            ),
        ),
        migrations.AddField(
            model_name="bankstatement",
            name="source_sha256",
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
