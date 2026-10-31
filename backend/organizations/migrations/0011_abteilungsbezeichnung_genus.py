from django.db import migrations, models

# Häufige Bezeichnungen und ihr Genus, damit bestehende Vereine gleich richtige Texte sehen
KNOWN = {
    "zug": "m",
    "korps": "n",
    "corps": "n",
    "bataillon": "n",
    "regiment": "n",
    "team": "n",
    "kommando": "n",
    "geschwader": "n",
    "kreis": "m",
    "club": "m",
    "klub": "m",
    "bereich": "m",
    "fachbereich": "m",
    "stamm": "m",
    "trupp": "m",
    "zweig": "m",
    "ortsverband": "m",
    "verband": "m",
}


def guess_gender(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    for org in Organization.objects.exclude(department_label="Abteilung"):
        word = org.department_label.strip().lower()
        gender = KNOWN.get(word)
        if gender:
            org.department_label_gender = gender
            if word in ("korps", "corps"):
                org.department_label_genitive = org.department_label.strip()
            org.save(update_fields=["department_label_gender", "department_label_genitive"])


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0010_genauigkeit_mitgliedschaften"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="department_label_gender",
            field=models.CharField(
                choices=[("f", "die (weiblich)"), ("m", "der (männlich)"), ("n", "das (sächlich)")],
                default="f",
                max_length=1,
                verbose_name="Bezeichnung für Abteilungen (Genus)",
            ),
        ),
        migrations.AddField(
            model_name="organization",
            name="department_label_genitive",
            field=models.CharField(
                blank=True,
                help_text="Leer: wird gebildet (des Zugs, des Kreises). Nur bei Ausnahmen eintragen.",
                max_length=50,
                verbose_name="Bezeichnung für Abteilungen (Genitiv, falls abweichend)",
            ),
        ),
        migrations.RunPython(guess_gender, migrations.RunPython.noop),
    ]
