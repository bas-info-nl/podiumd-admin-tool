"""Signing in: starting the Authorization Code flow and completing it.

Spec: authentication, "Sign-in through the Environment's Keycloak", "Safe
return after sign-in and sign-out" and "Sessions are held by the server";
access-control, "Users without a role are refused". Design D2:

- ``start`` creates a pre-auth record (``state``, ``nonce``, PKCE verifier,
  validated return path), bound to the browser by an opaque attempt
  identifier, and returns the Keycloak sign-in URL;
- ``complete`` uses that record once. A user with a role gets a brand-new
  session (rotation prevents fixation) and exactly one ``sign-in``/``allowed``
  Audit Entry, written first in the same transaction; a user without a role
  gets no session and exactly one ``sign-in``/``denied``/``no-role`` entry.
  A failed callback creates no session and goes to the stdout aggregator only.
"""

from __future__ import annotations

import contextlib
import hmac
from dataclasses import dataclass
from typing import Final

from podiumd_admin.application.audit import AuditRecorder
from podiumd_admin.application.authentication import AuthSettings, new_random_value
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.domain.audit import AuditEntry, Outcome, ReasonCode
from podiumd_admin.domain.roles import role_from_claims
from podiumd_admin.domain.session import Session
from podiumd_admin.domain.sign_in import SignInAttempt
from podiumd_admin.ports.audit import AuditSink
from podiumd_admin.ports.clock import Clock
from podiumd_admin.ports.identity_provider import IdentityProvider, TokenExchangeError
from podiumd_admin.ports.unit_of_work import UnitOfWork

SIGN_IN_ACTION: Final = "sign-in"


@dataclass(frozen=True, slots=True)
class SignInStarted:
    """A started sign-in: the browser keeps ``attempt_id`` and goes to ``authorization_url``."""

    attempt_id: str
    authorization_url: str


@dataclass(frozen=True, slots=True)
class SignedIn:
    """A new session; the browser gets ``session_id`` and returns to ``return_path``."""

    session_id: str
    return_path: str


@dataclass(frozen=True, slots=True)
class NoAccess:
    """The user signed in at Keycloak but holds neither role; no session was created."""


@dataclass(frozen=True, slots=True)
class SignInFailed:
    """The callback failed; no session was created and no Audit Entry stored."""

    reason: ReasonCode


type SignInResult = SignedIn | NoAccess | SignInFailed


class SignIn:
    """Starts and completes sign-ins through the Environment's Keycloak."""

    def __init__(
        self,
        *,
        settings: AuthSettings,
        identity_provider: IdentityProvider,
        unit_of_work: UnitOfWork,
        audit_sink: AuditSink,
        failures: UnauthenticatedFailureAggregator,
        clock: Clock,
    ) -> None:
        self._settings = settings
        self._identity_provider = identity_provider
        self._unit_of_work = unit_of_work
        self._audit_sink = audit_sink
        self._failures = failures
        self._clock = clock

    async def start(self, return_path: str | None) -> SignInStarted:
        """Create a pre-auth record and return where to send the browser.

        Raises ``IdentityProviderUnavailableError`` without storing anything
        if Keycloak cannot be reached.
        """
        attempt = SignInAttempt(
            state=new_random_value(),
            nonce=new_random_value(),
            code_verifier=new_random_value(),
            return_path=return_path or "/",
            created_at=self._clock.now(),
        )
        url = await self._identity_provider.authorization_url(
            redirect_uri=self._settings.redirect_uri,
            state=attempt.state,
            nonce=attempt.nonce,
            code_verifier=attempt.code_verifier,
        )
        attempt_id = new_random_value()
        async with self._unit_of_work.begin() as transaction:
            await transaction.sign_in_attempts.add(attempt_id, attempt)
        return SignInStarted(attempt_id=attempt_id, authorization_url=url)

    async def complete(
        self,
        *,
        attempt_id: str | None,
        state: str | None,
        code: str | None,
        error: str | None,
        client_ip: str | None,
        correlation_id: str,
    ) -> SignInResult:
        """Use the attempt once and, if Keycloak vouches for the user, sign them in.

        ``error`` is only checked for presence: Keycloak's free text is never
        stored. Raises ``AuditWriteFailedError`` if the ``sign-in`` Audit Entry
        could not be stored, and the unit of work's error if its transaction
        was aborted (issue #30); no session exists then.
        """
        attempt = await self._take(attempt_id)
        now = self._clock.now()
        if (
            attempt is None
            or attempt.is_expired(now)
            or state is None
            or not hmac.compare_digest(attempt.state.encode(), state.encode())
        ):
            return self._failed(ReasonCode.INVALID_STATE, client_ip)
        if error is not None or not code:
            return self._failed(ReasonCode.CALLBACK_ERROR, client_ip)
        try:
            identity = await self._identity_provider.exchange_code(
                code=code,
                redirect_uri=self._settings.redirect_uri,
                code_verifier=attempt.code_verifier,
                nonce=attempt.nonce,
            )
        except TokenExchangeError:
            return self._failed(ReasonCode.TOKEN_EXCHANGE_FAILED, client_ip)

        def entry(outcome: Outcome, reason: ReasonCode | None = None) -> AuditEntry:
            return AuditEntry(
                occurred_at=now,
                environment=self._settings.environment,
                action=SIGN_IN_ACTION,
                outcome=outcome,
                reason=reason,
                user_subject=identity.subject,
                username=identity.username,
                correlation_id=correlation_id,
                client_ip=client_ip,
            )

        role = role_from_claims(identity.claims, self._settings.role_mapping)
        if role is None:
            await self._record_denial(entry(Outcome.DENIED, ReasonCode.NO_ROLE))
            return NoAccess()

        session_id = new_random_value()
        session = Session(
            user_subject=identity.subject,
            username=identity.username,
            keycloak_session_id=identity.keycloak_session_id,
            roles=frozenset({role}),
            created_at=now,
            last_seen_at=now,
            expires_at=now + self._settings.timeouts.absolute_lifetime,
            tokens=identity.tokens,
        )
        async with self._unit_of_work.begin() as transaction:
            recorder = AuditRecorder(repository=transaction.audit_repository, sink=self._audit_sink)
            await recorder.record_then_act(
                entry(Outcome.ALLOWED), lambda: transaction.sessions.add(session_id, session)
            )
        return SignedIn(session_id=session_id, return_path=attempt.return_path)

    async def _take(self, attempt_id: str | None) -> SignInAttempt | None:
        """Remove the attempt in its own transaction, so it is used once whatever follows."""
        if not attempt_id:
            return None
        async with self._unit_of_work.begin() as transaction:
            return await transaction.sign_in_attempts.take(attempt_id)

    async def _record_denial(self, entry: AuditEntry) -> None:
        """Store a denial; the user is refused whether or not it could be stored.

        A failed insert is written to stdout by ``record_denial``; the commit
        of the transaction it aborted then raises, which is swallowed here.
        """
        with contextlib.suppress(Exception):
            async with self._unit_of_work.begin() as transaction:
                recorder = AuditRecorder(
                    repository=transaction.audit_repository, sink=self._audit_sink
                )
                await recorder.record_denial(entry)

    def _failed(self, reason: ReasonCode, client_ip: str | None) -> SignInFailed:
        """Count the failure for stdout; without a client IP there is nothing to count it under."""
        if client_ip is not None:
            self._failures.record(client_ip, reason)
        return SignInFailed(reason)
