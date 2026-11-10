"""Create the audit_entries and sessions tables, their indexes and the app grants.

Design D2 and D4:

- ``audit_entries`` is append-only by privilege: the app role
  ``podiumd_admin_app`` gets SELECT and INSERT only, never UPDATE, DELETE or
  TRUNCATE;
- ``sessions`` is keyed by the SHA-256 digest of the session identifier and
  holds the tokens encrypted; the app role gets SELECT, INSERT, UPDATE and
  DELETE.

The allowed values are written out here instead of imported from the domain,
so this migration keeps creating the same schema when the domain moves on.

Revision ID: 0001
Revises:
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "podiumd_admin_app"

OUTCOMES = ("allowed", "denied", "succeeded", "failed", "info")
# Unauthenticated-failure reasons are absent on purpose: they go to stdout only.
STORED_REASONS = (
    "no-role",
    "missing-permission",
    "csrf",
    "idle",
    "max-lifetime",
    "refresh-refused",
    "backchannel-logout",
)
STAGES = ("test", "accp", "prod")
ROLES = ("viewer", "operator")


def _sql_list(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("environment_municipality", sa.Text(), nullable=False),
        sa.Column("environment_stage", sa.String(4), nullable=False),
        sa.Column("environment_label", sa.Text(), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target", sa.String(500), nullable=True),
        sa.Column("outcome", sa.String(9), nullable=False),
        sa.Column("reason", sa.String(32), nullable=True),
        sa.Column("user_subject", sa.String(255), nullable=True),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column(
            "parameters",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(100), nullable=False),
        sa.Column("client_ip", postgresql.INET(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_entries"),
        sa.CheckConstraint(f"outcome IN ({_sql_list(OUTCOMES)})", name="ck_audit_entries_outcome"),
        sa.CheckConstraint(
            f"reason IS NULL OR reason IN ({_sql_list(STORED_REASONS)})",
            name="ck_audit_entries_reason",
        ),
        sa.CheckConstraint(
            "(outcome NOT IN ('denied', 'info') OR reason IS NOT NULL)"
            " AND (outcome NOT IN ('allowed', 'succeeded') OR reason IS NULL)",
            name="ck_audit_entries_reason_matches_outcome",
        ),
        sa.CheckConstraint(
            f"environment_stage IN ({_sql_list(STAGES)})",
            name="ck_audit_entries_environment_stage",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(parameters) = 'object'", name="ck_audit_entries_parameters_object"
        ),
    )
    op.create_index("ix_audit_entries_occurred_at", "audit_entries", [sa.text("occurred_at DESC")])
    op.create_index("ix_audit_entries_user_subject", "audit_entries", ["user_subject"])
    op.create_index("ix_audit_entries_action", "audit_entries", ["action"])
    op.create_index("ix_audit_entries_outcome", "audit_entries", ["outcome"])

    op.create_table(
        "sessions",
        sa.Column("id_hash", sa.LargeBinary(), nullable=False),
        sa.Column("user_subject", sa.String(255), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("keycloak_session_id", sa.String(255), nullable=True),
        sa.Column("roles", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tokens", sa.LargeBinary(), nullable=True),
        sa.PrimaryKeyConstraint("id_hash", name="pk_sessions"),
        sa.CheckConstraint("octet_length(id_hash) = 32", name="ck_sessions_id_hash_length"),
        sa.CheckConstraint(f"roles <@ ARRAY[{_sql_list(ROLES)}]::text[]", name="ck_sessions_roles"),
        sa.CheckConstraint(
            "last_seen_at >= created_at", name="ck_sessions_last_seen_after_created"
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_sessions_expires_after_created"),
    )
    op.create_index("ix_sessions_keycloak_session_id", "sessions", ["keycloak_session_id"])
    op.create_index("ix_sessions_last_seen_at", "sessions", ["last_seen_at"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    # Grants (design D4). Start from no privileges at all: default privileges
    # the owner role may have (ALTER DEFAULT PRIVILEGES ... GRANT ALL) would
    # otherwise give PUBLIC or the app role UPDATE, DELETE or TRUNCATE on
    # audit_entries, or access to alembic_version, which Alembic creates in
    # this same session. Then grant exactly what the app role needs; it gets
    # nothing on alembic_version.
    op.execute(f"REVOKE ALL ON audit_entries, sessions, alembic_version FROM PUBLIC, {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON audit_entries TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON sessions TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("sessions")
    op.drop_table("audit_entries")
