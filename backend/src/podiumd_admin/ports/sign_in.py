"""The SignInAttemptStore port: pre-auth records between sign-in start and callback.

Design D2. Like sessions, an attempt is found by an opaque random identifier
that only the browser holds; the store keeps only its hash.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from podiumd_admin.domain.sign_in import SignInAttempt


class SignInAttemptStore(Protocol):
    """Keeps sign-in attempts until their callback, or until they expire."""

    async def add(self, attempt_id: str, attempt: SignInAttempt) -> None:
        """Store ``attempt`` under ``attempt_id``."""
        ...

    async def take(self, attempt_id: str) -> SignInAttempt | None:
        """Remove and return the attempt, so it can be used only once; ``None`` if unknown."""
        ...

    async def purge_expired(self, now: datetime) -> int:
        """Remove the attempts that expired before ``now``; return how many."""
        ...
