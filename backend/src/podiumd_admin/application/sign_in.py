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

from dataclasses import dataclass
from typing import Final

from podiumd_admin.application.authentication import AuthSettings, new_random_value
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.domain.audit import ReasonCode
from podiumd_admin.domain.sign_in import SignInAttempt
from podiumd_admin.ports.audit import AuditSink
from podiumd_admin.ports.clock import Clock
from podiumd_admin.ports.identity_provider import IdentityProvider
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
