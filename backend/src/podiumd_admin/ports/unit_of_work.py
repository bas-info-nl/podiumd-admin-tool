"""The UnitOfWork port: one transaction over the Audit Log, sessions and sign-in attempts.

Design D4: an allowed database-only action (such as ending a session) and its
Audit Entry commit together, in one transaction, and the stdout copy of each
stored Audit Entry is written only after the commit. The persistence adapter
implements this with ``audited_transaction``.

The transaction commits when the block ends normally and rolls back when it
raises. If it could not commit although the block ended normally (a swallowed
failure aborted it), the adapter raises an error, so a caller never reports
an action as done that was rolled back (issue #30).
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from podiumd_admin.ports.audit import AuditRepository
from podiumd_admin.ports.session import SessionStore
from podiumd_admin.ports.sign_in import SignInAttemptStore


class Transaction(Protocol):
    """The stores of one open transaction."""

    @property
    def audit_repository(self) -> AuditRepository: ...

    @property
    def sessions(self) -> SessionStore: ...

    @property
    def sign_in_attempts(self) -> SignInAttemptStore: ...


class UnitOfWork(Protocol):
    """Opens transactions."""

    def begin(self) -> AbstractAsyncContextManager[Transaction]:
        """A transaction that commits when the block ends normally."""
        ...
