"""The SessionStore port: where Sessions are kept server-side.

Design D1 and D2. The browser holds only an opaque, random session
identifier. The store never keeps that identifier itself, only its hash, and
keeps the tokens encrypted; both are adapter concerns behind this port.
"""

from __future__ import annotations

from typing import Protocol

from podiumd_admin.domain.session import Session


class SessionStore(Protocol):
    """Keeps Sessions, found by the session identifier the browser presents."""

    async def add(self, session_id: str, session: Session) -> None:
        """Store ``session`` under ``session_id``. Raises if that identifier is already used."""
        ...

    async def get(self, session_id: str) -> Session | None:
        """Return the Session for ``session_id``, or ``None`` if the store does not know it."""
        ...
