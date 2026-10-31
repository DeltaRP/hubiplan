from django.db import migrations

from core.rls import APP_ROLE, create_app_role_sql


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(create_app_role_sql())


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        # Rolle bleibt bestehen (clusterweit); nur Rechte in dieser DB entziehen.
        schema_editor.execute(
            f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}; "
            f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE};"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
