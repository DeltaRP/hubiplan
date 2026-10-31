# Datenbank-Vorgaben für die neuen Spalten nachziehen, wo 0006 schon ohne sie lief
# (Testserver). So kann beim Ausrollen der alte Code weiter Einträge schreiben, solange
# die Migrationen laufen; seq bleibt leer und wird später versiegelt.
from django.db import migrations

SQL = """
ALTER TABLE audit_auditentry ALTER COLUMN prev_hash SET DEFAULT '';
ALTER TABLE audit_auditentry ALTER COLUMN hash SET DEFAULT '';
ALTER TABLE audit_auditentry ALTER COLUMN changes_hash SET DEFAULT '';
ALTER TABLE audit_auditentry ALTER COLUMN cleared SET DEFAULT false;
ALTER TABLE finance_yearclosing ALTER COLUMN purged_by_name SET DEFAULT '';
ALTER TABLE organizations_organization ALTER COLUMN reserves_enabled SET DEFAULT false;
ALTER TABLE members_honorarytitle ALTER COLUMN year_only SET DEFAULT false;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0006_protokollkette"),
        ("finance", "0018_aufbewahrungsende"),
        ("organizations", "0039_ruecklagen"),
        ("members", "0020_ehrung_nur_jahr"),
    ]

    operations = [migrations.RunSQL(SQL, migrations.RunSQL.noop)]
