# Geburtsdatum verschlüsselt (Spalte text). Rückwärts zurück nach date, sofern die Werte
# vorher mit `daten_verschluesseln --entschluesseln` entschlüsselt wurden (zurueck.sh).

import core.encfields
from django.db import migrations

SQL = 'ALTER TABLE "members_person" ALTER COLUMN "birth_date" TYPE {}'


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0021_kontakt_verschluesselt"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="person",
            name="members_per_scope_i_d9ac59_idx",
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="person",
                    name="birth_date",
                    field=core.encfields.EncryptedDateField(verbose_name="Geburtsdatum"),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    SQL.format("text"),
                    reverse_sql=SQL.format('date USING "birth_date"::date'),
                ),
            ],
        ),
    ]
