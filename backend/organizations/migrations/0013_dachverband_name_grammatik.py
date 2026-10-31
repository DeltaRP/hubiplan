from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0012_kurzname"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="name_gender",
            field=models.CharField(
                choices=[("f", "die (weiblich)"), ("m", "der (männlich)"), ("n", "das (sächlich)")],
                default="m",
                help_text="Für Texte der Vereine, z. B. „an den BSV melden“.",
                max_length=1,
                verbose_name="Artikel des Namens",
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="name_genitive",
            field=models.CharField(
                blank=True,
                help_text="Leer: Der Name bleibt unverändert (des BSV).",
                max_length=200,
                verbose_name="Name im Genitiv, falls abweichend",
            ),
        ),
    ]
