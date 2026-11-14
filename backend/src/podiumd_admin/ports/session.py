"""The SessionStore port: where Sessions are kept server-side.

Design D1 and D2. The browser holds only an opaque, random session
identifier. The store never keeps that identifier itself, only its hash, and
keeps the tokens encrypted; both are adapter concerns behind this port.

Back-channel logout and the expiry sweep find sessions without knowing their
identifier. They get a ``StoredSession`` with an opaque ``ref``, which
identifies the stored session but cannot be presented as a session identifier.

Ending a Session because it expired uses the conditional removals: the expiry
is checked again in the same step that removes the Session, so a request that
touched it after it was read keeps it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from podiumd_admin.domain.session import Session


@dataclass(frozen=True, slots=True)
class StoredSession:
    """A stored Session, with the opaque reference the store knows it by."""

    ref: str
    session: Session


class SessionStore(Protocol):
    """Keeps Sessions, found by the session identifier the browser presents."""

    async def add(self, session_id: str, session: Session) -> None:
        """Store ``session`` under ``session_id``. Raises if that identifier is already used."""
        ...

    async def get(self, session_id: str) -> Session | None:
        """Return the Session for ``session_id``, or ``None`` if the store does not know it."""
        ...

    async def save(self, session_id: str, session: Session) -> bool:
        """Replace the Session for ``session_id``; ``False`` if it is no longer stored."""
        ...

    async def remove(self, session_id: str) -> bool:
        """Remove the Session and its tokens; ``False`` if it was not stored."""
        ...

    async def remove_by_ref(self, ref: str) -> bool:
        """Remove the Session ``ref`` points to; ``False`` if it was not stored."""
        ...

    async def remove_expired(
        self, session_id: str, *, last_seen_until: datetime, now: datetime
    ) -> bool:
        """Remove the Session only if it is still expired; ``True`` if this call removed it.

        Expired means as in ``find_expired``. The check and the removal are
        one step, so a Session touched by a concurrent request is kept.
        """
        ...

    async def remove_expired_by_ref(
        self, ref: str, *, last_seen_until: datetime, now: datetime
    ) -> bool:
        """Like ``remove_expired``, for the Session ``ref`` points to."""
        ...

    async def find_by_keycloak_session_id(self, keycloak_session_id: str) -> list[StoredSession]:
        """The Sessions created in the Keycloak session ``keycloak_session_id`` (``sid``)."""
        ...

    async def find_expired(
        self, *, last_seen_until: datetime, now: datetime, limit: int
    ) -> list[StoredSession]:
        """At most ``limit`` expired Sessions: idle or past their lifetime.

        A Session is idle when it was last seen at or before
        ``last_seen_until`` (now minus the idle timeout), and past its
        lifetime when its ``expires_at`` is not after ``now``, as in the
        domain's ``expiry_reason``.
        """
        ...
