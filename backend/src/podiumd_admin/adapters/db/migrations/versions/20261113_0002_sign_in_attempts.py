"""Create the sign_in_attempts table for pre-auth records, and its app grants.

Design D2: a pre-auth record holds ``state``, ``nonce``, the PKCE verifier and
the validated return path, from the sign-in start until its callback. It is
keyed by the SHA-256 digest of the attempt identifier in the browser's
sign-in cookie, used once and purged when it expires.

The app role gets SELECT, INSERT and DELETE: an attempt is never changed.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "podiumd_admin_app"


def upgrade() -> None:
    op.create_table(
        "sign_in_attempts",
        sa.Column("id_hash", sa.LargeBinary(), nullable=False),
        sa.Column("state", sa.String(255), nullable=False),
        sa.Column("nonce", sa.String(255), nullable=False),
        sa.Column("code_verifier", sa.String(128), nullable=False),
        sa.Column("return_path", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id_hash", name="pk_sign_in_attempts"),
        sa.CheckConstraint("octet_length(id_hash) = 32", name="ck_sign_in_attempts_id_hash_length"),
        sa.CheckConstraint(
            "return_path LIKE '/%'", name="ck_sign_in_attempts_return_path_relative"
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_sign_in_attempts_expires_after_created"
        ),
    )
    op.create_index("ix_sign_in_attempts_expires_at", "sign_in_attempts", ["expires_at"])

    # As in 0001: start from no privileges, whatever the owner's default
    # privileges are, then grant exactly what the app role needs.
    op.execute(f"REVOKE ALL ON sign_in_attempts FROM PUBLIC, {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON sign_in_attempts TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("sign_in_attempts")
