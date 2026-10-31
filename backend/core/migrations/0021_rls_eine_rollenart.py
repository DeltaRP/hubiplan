"""Eine Rollenart: Row-Level Security der gemeinsamen Inhabertabelle.

``access_roleassignment`` enthält jetzt auch die Inhaber der Rollen von
Untereinheiten (früher ``members_departmentroleholder``). Deren Regel kommt dazu:
Ein Dachverband mit Mitgliederzugriff liest bzw. ändert die Inhaber bei den
Mitgliedschaften seines Verbandsbereichs. Eigene Zuordnungen bleiben immer sichtbar.
"""

from django.db import migrations

from core.rls import ORG, USER, enable_policy_sql, enable_rls_sql

FED_READ = "current_setting('app.fed_access', true) IN ('read', 'write')"
FED_WRITE = "current_setting('app.fed_access', true) = 'write'"
MEMBERSHIPS_OF_ORG = f"(SELECT id FROM members_membership WHERE scope_id = {ORG})"
OWN = f"organization_id = {ORG}"
FED = f"membership_id IN {MEMBERSHIPS_OF_ORG}"


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        enable_policy_sql(
            "access_roleassignment",
            f"{OWN} OR user_id = {USER} OR ({FED_READ} AND {FED})",
            f"{OWN} OR ({FED_WRITE} AND {FED})",
        )
    )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(enable_rls_sql("access_roleassignment", f"user_id = {USER}"))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0020_rls_termine_weitergabe"),
        ("access", "0011_eine_rollenart_rueckverweise"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
