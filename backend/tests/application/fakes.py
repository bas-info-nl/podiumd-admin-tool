"""In-memory fakes of the ports, for application-layer tests."""

from __future__ import annotations

import contextlib
import copy
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from podiumd_admin.domain.audit import AuditEntry, UnauthenticatedFailureSummary
from podiumd_admin.domain.identity import LogoutNotice, VerifiedIdentity
from podiumd_admin.domain.session import Session, SessionTokens
from podiumd_admin.domain.sign_in import SignInAttempt
from podiumd_admin.ports.audit import AuditRepository
from podiumd_admin.ports.identity_provider import (
    IdentityProviderUnavailableError,
    InvalidLogoutTokenError,
    RefreshRefusedError,
    TokenExchangeError,
)
from podiumd_admin.ports.session import SessionStore, StoredSession
from podiumd_admin.ports.sign_in import SignInAttemptStore


@dataclass
class FakeAuditRepository:
    """Stores entries in a list; can be told to fail every insert."""

    events: list[str] = field(default_factory=list)
    entries: list[AuditEntry] = field(default_factory=list)
    error: Exception | BaseException | None = None

    async def add(self, entry: AuditEntry) -> None:
        self.events.append("insert")
        if self.error is not None:
            raise self.error
        self.entries.append(entry)


@dataclass
class FakeAuditSink:
    """Collects what would be written to stdout; can be told to fail the failure report."""

    stored: list[AuditEntry] = field(default_factory=list)
    write_failures: list[tuple[AuditEntry, Exception]] = field(default_factory=list)
    summaries: list[UnauthenticatedFailureSummary] = field(default_factory=list)
    report_error: Exception | None = None

    def entry_stored(self, entry: AuditEntry) -> None:
        self.stored.append(entry)

    def audit_write_failed(self, entry: AuditEntry, error: Exception) -> None:
        self.write_failures.append((entry, error))
        if self.report_error is not None:
            raise self.report_error

    def unauthenticated_failures(self, summary: UnauthenticatedFailureSummary) -> None:
        self.summaries.append(summary)


@dataclass
class FakeClock:
    """A clock that only moves when a test advances it."""

    current: datetime

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


# --- Sessions, sign-in attempts and transactions --------------------------------


def _ref(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()


@dataclass
class FakeSessionStore:
    """Sessions in a dict keyed by session identifier."""

    sessions: dict[str, Session] = field(default_factory=dict)

    async def add(self, session_id: str, session: Session) -> None:
        if session_id in self.sessions:
            raise ValueError("session id already in use")
        self.sessions[session_id] = session

    async def get(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    async def save(self, session_id: str, session: Session) -> bool:
        if session_id not in self.sessions:
            return False
        self.sessions[session_id] = session
        return True

    async def remove(self, session_id: str) -> bool:
        return self.sessions.pop(session_id, None) is not None

    async def remove_by_ref(self, ref: str) -> bool:
        for session_id in list(self.sessions):
            if _ref(session_id) == ref:
                del self.sessions[session_id]
                return True
        return False

    async def find_by_keycloak_session_id(self, keycloak_session_id: str) -> list[StoredSession]:
        return [
            StoredSession(ref=_ref(session_id), session=session)
            for session_id, session in self.sessions.items()
            if session.keycloak_session_id == keycloak_session_id
        ]

    async def find_expired(
        self, *, last_seen_before: datetime, now: datetime, limit: int
    ) -> list[StoredSession]:
        found = [
            StoredSession(ref=_ref(session_id), session=session)
            for session_id, session in self.sessions.items()
            if session.last_seen_at < last_seen_before or session.expires_at <= now
        ]
        return found[:limit]


@dataclass
class FakeSignInAttemptStore:
    """Sign-in attempts in a dict keyed by attempt identifier."""

    attempts: dict[str, SignInAttempt] = field(default_factory=dict)

    async def add(self, attempt_id: str, attempt: SignInAttempt) -> None:
        self.attempts[attempt_id] = attempt

    async def take(self, attempt_id: str) -> SignInAttempt | None:
        return self.attempts.pop(attempt_id, None)

    async def purge_expired(self, now: datetime) -> int:
        expired = [key for key, attempt in self.attempts.items() if attempt.is_expired(now)]
        for key in expired:
            del self.attempts[key]
        return len(expired)


class FakeTransactionAbortedError(RuntimeError):
    """Like the adapter's ``TransactionAbortedError``: a swallowed failure aborted the commit."""


@dataclass
class FakeTransaction:
    audit_repository: AuditRepository
    sessions: SessionStore
    sign_in_attempts: SignInAttemptStore


@dataclass
class FakeUnitOfWork:
    """Transactions over the fakes, with the commit rules of PostgreSQL.

    A block that raises rolls back. A failed Audit Entry insert aborts the
    transaction, as it does in PostgreSQL, even when the caller swallows the
    error: the commit then rolls back and raises ``FakeTransactionAbortedError``.
    Committed entries go to ``sink`` after the commit.
    """

    sink: FakeAuditSink
    audit: FakeAuditRepository = field(default_factory=FakeAuditRepository)
    sessions: FakeSessionStore = field(default_factory=FakeSessionStore)
    sign_in_attempts: FakeSignInAttemptStore = field(default_factory=FakeSignInAttemptStore)
    commits: int = 0
    rollbacks: int = 0

    @contextlib.asynccontextmanager
    async def begin(self) -> AsyncIterator[FakeTransaction]:
        sessions = copy.copy(self.sessions.sessions)
        attempts = copy.copy(self.sign_in_attempts.attempts)
        entries = len(self.audit.entries)
        inserts = self.audit.events.count("insert")

        def rollback() -> None:
            self.sessions.sessions = sessions
            self.sign_in_attempts.attempts = attempts
            del self.audit.entries[entries:]
            self.rollbacks += 1

        try:
            yield FakeTransaction(
                audit_repository=self.audit,
                sessions=self.sessions,
                sign_in_attempts=self.sign_in_attempts,
            )
        except BaseException:
            rollback()
            raise
        failed_inserts = (
            self.audit.events.count("insert") - inserts - (len(self.audit.entries) - entries)
        )
        if failed_inserts:
            rollback()
            raise FakeTransactionAbortedError("a failed insert aborted the transaction")
        self.commits += 1
        for entry in self.audit.entries[entries:]:
            self.sink.entry_stored(entry)


# --- Identity provider ------------------------------------------------------------

AUTHORIZATION_ENDPOINT = "https://keycloak.onsdorp.example/realms/podiumd/auth"
END_SESSION_ENDPOINT = "https://keycloak.onsdorp.example/realms/podiumd/logout"


def tokens(
    expires_at: datetime = datetime(2026, 11, 13, 9, 5, tzinfo=UTC), suffix: str = "1"
) -> SessionTokens:
    return SessionTokens(
        access_token=f"access-{suffix}",
        refresh_token=f"refresh-{suffix}",
        id_token=f"id-{suffix}",
        access_token_expires_at=expires_at,
    )


def identity(
    roles: list[str] | None = None,
    *,
    subject: str = "f3b2c1d0-0000-4000-8000-000000000001",
    username: str | None = "j.jansen",
    sid: str | None = "kc-sid-1",
    session_tokens: SessionTokens | None = None,
) -> VerifiedIdentity:
    claims: dict[str, object] = {"sub": subject}
    if roles is not None:
        claims["resource_access"] = {"podiumd-admin": {"roles": roles}}
    return VerifiedIdentity(
        subject=subject,
        username=username,
        keycloak_session_id=sid,
        tokens=session_tokens if session_tokens is not None else tokens(),
        claims=claims,
    )


@dataclass
class FakeIdentityProvider:
    """Answers like Keycloak would; a test sets the identity or the error."""

    identity: VerifiedIdentity = field(default_factory=lambda: identity(["viewer"]))
    refreshed: VerifiedIdentity | None = None
    unavailable: bool = False
    exchange_fails: bool = False
    refresh_refused: bool = False
    logout_sid: str | None = None
    exchanges: list[dict[str, str]] = field(default_factory=list)
    refreshes: list[str] = field(default_factory=list)

    async def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, code_verifier: str
    ) -> str:
        if self.unavailable:
            raise IdentityProviderUnavailableError("Keycloak cannot be reached")
        query = urlencode(
            {
                "redirect_uri": redirect_uri,
                "state": state,
                "nonce": nonce,
                "verifier": code_verifier,
            }
        )
        return f"{AUTHORIZATION_ENDPOINT}?{query}"

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str, nonce: str
    ) -> VerifiedIdentity:
        self.exchanges.append(
            {
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "nonce": nonce,
            }
        )
        if self.exchange_fails:
            raise TokenExchangeError("the code could not be exchanged")
        return self.identity

    async def refresh(self, refresh_token: str) -> VerifiedIdentity:
        self.refreshes.append(refresh_token)
        if self.unavailable:
            raise IdentityProviderUnavailableError("Keycloak cannot be reached")
        if self.refresh_refused:
            raise RefreshRefusedError("refused")
        return self.refreshed if self.refreshed is not None else self.identity

    async def verify_logout_token(self, logout_token: str) -> LogoutNotice:
        if self.logout_sid is None or logout_token != "valid-logout-token":  # noqa: S105
            raise InvalidLogoutTokenError("not a valid logout token")
        return LogoutNotice(self.logout_sid)

    async def end_session_url(
        self, *, id_token_hint: str | None, post_logout_redirect_uri: str
    ) -> str:
        query = {"post_logout_redirect_uri": post_logout_redirect_uri}
        if id_token_hint is not None:
            query["id_token_hint"] = id_token_hint
        return f"{END_SESSION_ENDPOINT}?{urlencode(query)}"
