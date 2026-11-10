"""Alembic environment: runs the migrations as the owner role (design D4, D8).

The connection comes from, in this order:

1. ``config.attributes["connection"]``: an open connection handed over by the
   caller, as the tests do;
2. the ``PODIUMD_ADMIN_DATABASE_OWNER_URL`` environment variable, as the Helm
   pre-install/pre-upgrade Job does.

Offline mode (``alembic upgrade head --sql``) prints the SQL instead, for an
installer who wants to review it first.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine
from sqlalchemy.pool import NullPool

from podiumd_admin.adapters.db.tables import metadata

OWNER_URL_ENV = "PODIUMD_ADMIN_DATABASE_OWNER_URL"

config = context.config


def _owner_url() -> str:
    url = os.environ.get(OWNER_URL_ENV, "").strip()
    if not url:
        raise RuntimeError(
            f"set {OWNER_URL_ENV} to the database URL of the owner role "
            "(postgresql+psycopg://podiumd_admin_owner:...@host:5432/database)"
        )
    return url


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=os.environ.get(OWNER_URL_ENV) or "postgresql+psycopg://",
        target_metadata=metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    given: Connection | None = config.attributes.get("connection")
    if given is not None:
        _run(given)
        return

    if config.config_file_name is not None:
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    engine = create_engine(_owner_url(), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            _run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
