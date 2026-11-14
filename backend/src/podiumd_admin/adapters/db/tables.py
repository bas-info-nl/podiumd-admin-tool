"""The database tables, as SQLAlchemy Core definitions (design D1, D2, D4).

The migrations in ``migrations/versions`` create the schema; these
definitions describe the same schema for the repositories. A test compares
the two, so they cannot drift apart.

Column sizes and allowed values mirror the domain: the text limits of
``podiumd_admin.domain.audit``, the ``Outcome``, ``ReasonCode``, ``Stage`` and
``Role`` enums. The database repeats these rules as constraints, so even a
statement that bypasses the domain cannot store what the domain forbids.
"""

from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB

from podiumd_admin.domain.audit import (
    MAX_ACTION_LENGTH,
    MAX_CORRELATION_ID_LENGTH,
    MAX_TARGET_LENGTH,
    MAX_USER_SUBJECT_LENGTH,
    MAX_USERNAME_LENGTH,
    UNAUTHENTICATED_REASONS,
    Outcome,
    ReasonCode,
)
from podiumd_admin.domain.environment import Stage
from podiumd_admin.domain.roles import Role
from podiumd_admin.domain.session import MAX_KEYCLOAK_SESSION_ID_LENGTH
from podiumd_admin.domain.sign_in import MAX_RANDOM_VALUE_LENGTH, MAX_RETURN_PATH_LENGTH

SESSION_ID_HASH_LENGTH = 32
"""Bytes in a SHA-256 digest: the key of the ``sessions`` table."""

STORED_REASONS = tuple(reason for reason in ReasonCode if reason not in UNAUTHENTICATED_REASONS)
"""Reason codes an Audit Entry may hold: unauthenticated failures go to stdout only."""


def _sql_list(values: tuple[str, ...] | list[str]) -> str:
    """A SQL list of string literals; only ever called with our own enum values."""
    return ", ".join(f"'{value}'" for value in values)


def _one_of(column: str, values: tuple[str, ...] | list[str]) -> str:
    return f"{column} IN ({_sql_list(values)})"


metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

audit_entries = Table(
    "audit_entries",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("environment_municipality", Text(), nullable=False),
    Column("environment_stage", String(4), nullable=False),
    Column("environment_label", Text(), nullable=True),
    Column("action", String(MAX_ACTION_LENGTH), nullable=False),
    Column("target", String(MAX_TARGET_LENGTH), nullable=True),
    Column("outcome", String(9), nullable=False),
    Column("reason", String(32), nullable=True),
    Column("user_subject", String(MAX_USER_SUBJECT_LENGTH), nullable=True),
    Column("username", String(MAX_USERNAME_LENGTH), nullable=True),
    Column("parameters", JSONB(), nullable=False, server_default=text("'{}'::jsonb")),
    Column("correlation_id", String(MAX_CORRELATION_ID_LENGTH), nullable=False),
    Column("client_ip", INET(), nullable=True),
    Index("ix_audit_entries_occurred_at", text("occurred_at DESC")),
    Index("ix_audit_entries_user_subject", "user_subject"),
    Index("ix_audit_entries_action", "action"),
    Index("ix_audit_entries_outcome", "outcome"),
    CheckConstraint(_one_of("outcome", [o.value for o in Outcome]), name="outcome"),
    CheckConstraint(
        f"reason IS NULL OR {_one_of('reason', [r.value for r in STORED_REASONS])}",
        name="reason",
    ),
    CheckConstraint(
        f"(outcome NOT IN ('{Outcome.DENIED}', '{Outcome.INFO}') OR reason IS NOT NULL)"
        f" AND (outcome NOT IN ('{Outcome.ALLOWED}', '{Outcome.SUCCEEDED}') OR reason IS NULL)",
        name="reason_matches_outcome",
    ),
    CheckConstraint(
        _one_of("environment_stage", [s.value for s in Stage]), name="environment_stage"
    ),
    CheckConstraint("jsonb_typeof(parameters) = 'object'", name="parameters_object"),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id_hash", LargeBinary(), primary_key=True),
    Column("user_subject", String(MAX_USER_SUBJECT_LENGTH), nullable=False),
    Column("username", String(MAX_USERNAME_LENGTH), nullable=True),
    Column("keycloak_session_id", String(MAX_KEYCLOAK_SESSION_ID_LENGTH), nullable=True),
    Column("roles", ARRAY(Text()), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("tokens", LargeBinary(), nullable=True),
    Index("ix_sessions_keycloak_session_id", "keycloak_session_id"),
    Index("ix_sessions_last_seen_at", "last_seen_at"),
    Index("ix_sessions_expires_at", "expires_at"),
    CheckConstraint(f"octet_length(id_hash) = {SESSION_ID_HASH_LENGTH}", name="id_hash_length"),
    CheckConstraint(f"roles <@ ARRAY[{_sql_list([r.value for r in Role])}]::text[]", name="roles"),
    CheckConstraint("last_seen_at >= created_at", name="last_seen_after_created"),
    CheckConstraint("expires_at > created_at", name="expires_after_created"),
)

sign_in_attempts = Table(
    "sign_in_attempts",
    metadata,
    Column("id_hash", LargeBinary(), primary_key=True),
    Column("state", String(MAX_RANDOM_VALUE_LENGTH), nullable=False),
    Column("nonce", String(MAX_RANDOM_VALUE_LENGTH), nullable=False),
    Column("code_verifier", String(128), nullable=False),
    Column("return_path", String(MAX_RETURN_PATH_LENGTH), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Index("ix_sign_in_attempts_expires_at", "expires_at"),
    CheckConstraint(f"octet_length(id_hash) = {SESSION_ID_HASH_LENGTH}", name="id_hash_length"),
    CheckConstraint("return_path LIKE '/%'", name="return_path_relative"),
    CheckConstraint("expires_at > created_at", name="expires_after_created"),
)
