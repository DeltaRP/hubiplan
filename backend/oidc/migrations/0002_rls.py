"""Nextcloud-Anmeldung: Row-Level Security (nur die eigene Einheit)."""

from django.db import migrations

from core.rls import disable_rls_sql, enable_rls_sql


class Migration(migrations.Migration):
    dependencies = [("oidc", "0001_nextcloud_anmeldung")]

    operations = [
        migrations.RunSQL(enable_rls_sql("oidc_client"), disable_rls_sql("oidc_client")),
    ]
