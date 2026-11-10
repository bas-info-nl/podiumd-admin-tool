"""The Alembic migrations: tables, indexes and grants (design D4).

``podiumd_admin_owner`` owns the schema and runs the migrations;
``podiumd_admin_app`` may only read and insert Audit Entries, and has the
normal privileges on sessions.
"""

from __future__ import annotations

from collections.abc import Callable

import psycopg.errors
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.pool import NullPool

from podiumd_admin.adapters.db.tables import metadata
from tests.adapters.db.conftest import APP_ROLE, OWNER_ROLE, Database, downgrade, migrate

pytestmark = pytest.mark.integration


def _privileges(engine: Engine, table: str) -> dict[str, bool]:
    with engine.connect() as connection:
        return {
            privilege: bool(
                connection.execute(
                    text("SELECT has_table_privilege(:role, :table, :privilege)"),
                    {"role": APP_ROLE, "table": table, "privilege": privilege},
                ).scalar_one()
            )
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
        }


def test_the_app_role_may_only_read_and_insert_audit_entries(owner_engine: Engine) -> None:
    assert _privileges(owner_engine, "audit_entries") == {
        "SELECT": True,
        "INSERT": True,
        "UPDATE": False,
        "DELETE": False,
        "TRUNCATE": False,
    }


def test_the_app_role_has_the_normal_privileges_on_sessions(owner_engine: Engine) -> None:
    assert _privileges(owner_engine, "sessions") == {
        "SELECT": True,
        "INSERT": True,
        "UPDATE": True,
        "DELETE": True,
        "TRUNCATE": False,
    }


@pytest.mark.parametrize("table", ["audit_entries", "sessions", "alembic_version"])
def test_the_owner_role_owns_the_tables(owner_engine: Engine, table: str) -> None:
    with owner_engine.connect() as connection:
        owner = connection.execute(
            text("SELECT tableowner FROM pg_tables WHERE tablename = :table"), {"table": table}
        ).scalar_one()

    assert owner == OWNER_ROLE


def test_the_app_role_cannot_touch_the_migration_bookkeeping(owner_engine: Engine) -> None:
    assert not any(_privileges(owner_engine, "alembic_version").values())


def _index_definitions(engine: Engine, table: str) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = :table"),
            {"table": table},
        )
        return {str(name): str(definition) for name, definition in rows}


def test_audit_entries_have_the_d4_indexes(owner_engine: Engine) -> None:
    indexes = _index_definitions(owner_engine, "audit_entries")

    assert "(occurred_at DESC)" in indexes["ix_audit_entries_occurred_at"]
    assert "(user_subject)" in indexes["ix_audit_entries_user_subject"]
    assert "(action)" in indexes["ix_audit_entries_action"]
    assert "(outcome)" in indexes["ix_audit_entries_outcome"]


def test_sessions_are_indexed_for_back_channel_logout_and_the_expiry_sweep(
    owner_engine: Engine,
) -> None:
    indexes = _index_definitions(owner_engine, "sessions")

    assert "(keycloak_session_id)" in indexes["ix_sessions_keycloak_session_id"]
    assert "(last_seen_at)" in indexes["ix_sessions_last_seen_at"]
    assert "(expires_at)" in indexes["ix_sessions_expires_at"]


def test_the_table_definitions_match_the_migrations(owner_engine: Engine) -> None:
    """The adapter's SQLAlchemy tables and the migrated schema must not drift apart."""
    with owner_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        differences = compare_metadata(context, metadata)

    assert differences == []


def test_the_migrations_downgrade_and_upgrade_again(
    create_database: Callable[[], Database],
) -> None:
    database = create_database()
    migrate(database)

    downgrade(database, "base")
    engine = create_engine(database.owner_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}

        migrate(database)
        with engine.connect() as connection:
            assert {"audit_entries", "sessions"} <= set(inspect(connection).get_table_names())
    finally:
        engine.dispose()


def test_owner_default_privileges_do_not_widen_the_grants(
    create_database: Callable[[], Database],
) -> None:
    """A DBA's ``ALTER DEFAULT PRIVILEGES ... GRANT ALL`` must not undo design D4."""
    database = create_database()
    owner = create_engine(database.owner_url, poolclass=NullPool)
    try:
        with owner.begin() as connection:
            connection.execute(
                text(
                    f"ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER_ROLE} "
                    f"GRANT ALL ON TABLES TO {APP_ROLE}, PUBLIC"
                )
            )
        migrate(database)

        assert _privileges(owner, "audit_entries") == {
            "SELECT": True,
            "INSERT": True,
            "UPDATE": False,
            "DELETE": False,
            "TRUNCATE": False,
        }
        assert _privileges(owner, "sessions") == {
            "SELECT": True,
            "INSERT": True,
            "UPDATE": True,
            "DELETE": True,
            "TRUNCATE": False,
        }
        assert not any(_privileges(owner, "alembic_version").values())
    finally:
        owner.dispose()

    app = create_engine(database.app_url, poolclass=NullPool)
    try:
        for statement in (
            "UPDATE audit_entries SET action = action",
            "DELETE FROM audit_entries",
            "TRUNCATE audit_entries",
            "TRUNCATE sessions",
            "SELECT * FROM alembic_version",
            "UPDATE alembic_version SET version_num = version_num",
        ):
            with app.connect() as connection, pytest.raises(ProgrammingError) as raised:
                connection.execute(text(statement))
            assert isinstance(raised.value.orig, psycopg.errors.InsufficientPrivilege), statement
    finally:
        app.dispose()
