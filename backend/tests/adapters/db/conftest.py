"""A real PostgreSQL for the persistence adapter tests (design D9).

One testcontainers PostgreSQL runs per test session. In it, the fixtures set
up what an installer sets up (design D4, Migration Plan):

- the ``podiumd_admin_owner`` role, which owns the database and runs the
  migrations, and the ``podiumd_admin_app`` role the application runs with;
- a database owned by the owner role, migrated to ``head`` with the real
  ``alembic.ini``.

Tests talk to the database as the app role, so the grants are exercised the
way they are in production. The owner role is used only to empty the tables
between tests, which the app role is not allowed to do.

The integration tests need Docker. They are part of the default test run, so
CI runs them; without Docker they fail rather than being skipped. Run
``uv run pytest -m "not integration"`` to leave them out locally.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Engine, create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

BACKEND_DIR = Path(__file__).resolve().parents[3]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

POSTGRES_IMAGE = "postgres:17-alpine"
SUPERUSER = "postgres"
OWNER_ROLE = "podiumd_admin_owner"
APP_ROLE = "podiumd_admin_app"


@dataclass(frozen=True, slots=True)
class Database:
    """One database in the test PostgreSQL, owned by the owner role."""

    host: str
    port: int
    name: str
    owner_password: str
    app_password: str

    def url(self, role: str, password: str) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=role,
            password=password,
            host=self.host,
            port=self.port,
            database=self.name,
        )

    @property
    def owner_url(self) -> URL:
        return self.url(OWNER_ROLE, self.owner_password)

    @property
    def app_url(self) -> URL:
        return self.url(APP_ROLE, self.app_password)


def alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


def migrate(database: Database, revision: str = "head") -> None:
    """Run ``alembic upgrade`` as the owner role, the way the Helm hook Job does."""
    engine = create_engine(database.owner_url, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
    finally:
        engine.dispose()


def downgrade(database: Database, revision: str) -> None:
    engine = create_engine(database.owner_url, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.downgrade(config, revision)
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    container = PostgresContainer(
        POSTGRES_IMAGE,
        username=SUPERUSER,
        password=secrets.token_hex(16),
        dbname="postgres",
        driver="psycopg",
    )
    with container:
        yield container


@pytest.fixture(scope="session")
def create_database(postgres: PostgresContainer) -> Callable[[], Database]:
    """Create the two roles once; return a function that creates a fresh database."""
    owner_password = secrets.token_hex(16)
    app_password = secrets.token_hex(16)
    superuser = create_engine(
        URL.create(
            "postgresql+psycopg",
            username=postgres.username,
            password=postgres.password,
            host=postgres.get_container_host_ip(),
            port=int(postgres.get_exposed_port(postgres.port)),
            database=postgres.dbname,
        ),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    with superuser.connect() as connection:
        # The passwords are random hex, so they are safe to put in the statement.
        connection.execute(text(f"CREATE ROLE {OWNER_ROLE} LOGIN PASSWORD '{owner_password}'"))
        connection.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{app_password}'"))

    counter = iter(range(1_000_000))

    def _create() -> Database:
        name = f"podiumd_admin_{next(counter)}"
        with superuser.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {name} OWNER {OWNER_ROLE}"))
        return Database(
            host=postgres.get_container_host_ip(),
            port=int(postgres.get_exposed_port(postgres.port)),
            name=name,
            owner_password=owner_password,
            app_password=app_password,
        )

    return _create


@pytest.fixture(scope="session")
def migrated_database(create_database: Callable[[], Database]) -> Database:
    database = create_database()
    migrate(database)
    return database


@pytest.fixture
def owner_engine(migrated_database: Database) -> Iterator[Engine]:
    """An owner-role engine; empties the tables first, so every test starts clean."""
    engine = create_engine(migrated_database.owner_url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_entries, sessions"))
    yield engine
    engine.dispose()


@pytest.fixture
async def app_engine(
    migrated_database: Database, owner_engine: Engine
) -> AsyncIterator[AsyncEngine]:
    """An async engine for the app role, the way the application connects."""
    engine = create_async_engine(migrated_database.app_url, poolclass=NullPool)
    yield engine
    await engine.dispose()
