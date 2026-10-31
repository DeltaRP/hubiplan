"""SQL-Bausteine für Row-Level Security, genutzt von den Migrationen."""

APP_ROLE = "hubiplan_app"

ORG = "NULLIF(current_setting('app.org_id', true), '')::bigint"
USER = "NULLIF(current_setting('app.user_id', true), '')::bigint"
BYPASS = "current_setting('app.bypass_rls', true) = 'on'"
SCOPE = "NULLIF(current_setting('app.scope_id', true), '')::bigint"


def create_app_role_sql() -> str:
    """Eingeschränkte Rolle ohne Superuser- und BYPASSRLS-Recht anlegen."""
    return f"""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS;
        END IF;
    END $$;
    GRANT {APP_ROLE} TO CURRENT_USER;
    GRANT USAGE ON SCHEMA public TO {APP_ROLE};
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE};
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE};
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE};
    """


def app_login_sql(password: str, connection) -> str:
    """Rolle hubiplan_app mit Passwort anmeldefähig machen (ohne Superuser-Rechte).

    Im Echtbetrieb meldet sich die Anwendung direkt als hubiplan_app an. So kann
    auch Schadcode in der Anwendung die Rolle nicht per ``RESET ROLE`` verlassen.
    """
    from psycopg import sql

    return (
        sql.SQL(
            "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}"
        )
        .format(sql.Identifier(APP_ROLE), sql.Literal(password))
        .as_string(connection)
    )


def enable_rls_sql(table: str, extra_using: str = "") -> str:
    """RLS für eine mandantenbezogene Tabelle (Spalte organization_id)."""
    using = f"organization_id = {ORG} OR {BYPASS}"
    if extra_using:
        using = f"{using} OR {extra_using}"
    return f"""
    ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON {table};
    CREATE POLICY tenant_isolation ON {table}
        USING ({using})
        WITH CHECK (organization_id = {ORG} OR {BYPASS});
    """


def disable_rls_sql(table: str) -> str:
    return f"""
    DROP POLICY IF EXISTS tenant_isolation ON {table};
    ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
    """


def enable_policy_sql(table: str, using: str, check: str | None = None) -> str:
    """RLS mit frei formulierter Regel (z. B. Verbandsbereich statt Organisation)."""
    return f"""
    ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON {table};
    CREATE POLICY tenant_isolation ON {table}
        USING (({using}) OR {BYPASS})
        WITH CHECK (({check or using}) OR {BYPASS});
    """
