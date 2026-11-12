"""Alembic environment: runs the migrations as the owner role (design D4, D8).

The connection comes from, in this order:

1. ``config.attributes["connection"]``: an open connection handed over by the
   caller, as the tests do;
2. the ``PODIUMD_ADMIN_DATABASE_OWNER_URL`` environment variable, as the Helm
   pre-install/pre-upgrade Job does. It is read and validated by
   ``podiumd_admin.config.load_owner_database_url``; the running instance
   uses ``PODIUMD_ADMIN_DATABASE_APP_URL`` instead.

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
from podiumd_admin.config import DATABASE_OWNER_URL, load_owner_database_url

config = context.config


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=os.environ.get(DATABASE_OWNER_URL) or "postgresql+psycopg://",
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
    engine = create_engine(load_owner_database_url(), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            _run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
