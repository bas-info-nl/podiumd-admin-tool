"""Sessions after sign-in: resuming, refreshing, ending and expiring them.

Spec: authentication, "Session lifetime and expiry" and "Sign-out";
access-control, "Roles". Design D2 and D4:

- every request resumes its Session: one past its idle timeout or absolute
  lifetime ends; an expired access token is refreshed before the request is
  authorised, and the roles are read again from the new token; a refused
  refresh ends the Session;
- a Session that ends by itself gets exactly one ``session-expired``/``info``
  Audit Entry with the reason. Removing the Session (which purges its
  tokens) and inserting that entry happen in one transaction, and the entry
  is only inserted if this call removed the Session, so two requests (or a
  request and the sweep) can never both record the same expiry. A Session
  that ends because it expired is only removed while it is still expired, so
  a request that touched it after it was read keeps it, and no entry is
  recorded for it. If the entry cannot be stored, the transaction rolls back
  and the Session stays, so the expiry sweep records it later;
- the expiry sweep (``expire_abandoned``) finds Sessions whose user never
  returned, ends them the same way, without a client IP, and purges expired
  sign-in attempts. The app runs it every minute, in its single replica
  (ADR 0010).
"""

from __future__ import annotations

import contextlib
import dataclasses
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from podiumd_admin.application.audit import AuditRecorder
from podiumd_admin.application.authentication import AuthSettings
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.domain.audit import AuditEntry, Outcome, ReasonCode
from podiumd_admin.domain.authorisation import User
from podiumd_admin.domain.identity import VerifiedIdentity
from podiumd_admin.domain.roles import role_from_claims
from podiumd_admin.domain.session import (
    Session,
    SessionTokens,
    access_token_expired,
    expiry_reason,
    highest_role,
)
from podiumd_admin.ports.audit import AuditSink
from podiumd_admin.ports.clock import Clock
from podiumd_admin.ports.identity_provider import (
    IdentityProvider,
    InvalidLogoutTokenError,
    RefreshRefusedError,
)
from podiumd_admin.ports.session import SessionStore
from podiumd_admin.ports.unit_of_work import UnitOfWork

SESSION_EXPIRED_ACTION: Final = "session-expired"
SIGN_OUT_ACTION: Final = "sign-out"
SWEEP_BATCH_SIZE: Final = 100
"""How many expired Sessions the sweep reads at a time."""


@dataclass(frozen=True, slots=True)
class ActiveSession:
    """The Session of the current request, after it was resumed."""

    session_id: str
    session: Session

    @property
    def user(self) -> User:
        """The signed-in user, as far as authorisation is concerned."""
        return User(subject=self.session.user_subject, role=highest_role(self.session.roles))


@dataclass(frozen=True, slots=True)
class _Ending:
    """Which stored Session to end: by its identifier or by the store's ref.

    ``expired_at`` is set when the Session ends because it expired at that
    moment: it is then only removed if it is still expired, so a Session that
    a concurrent request touched after it was read is kept.
    """

    session: Session
    session_id: str | None = None
    ref: str | None = None
    expired_at: datetime | None = None


class Sessions:
    """Resumes, refreshes and ends Sessions."""

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

    async def resume(
        self, session_id: str | None, *, client_ip: str | None, correlation_id: str
    ) -> ActiveSession | None:
        """The Session for ``session_id``, refreshed and touched; ``None`` if there is none.

        Raises ``IdentityProviderUnavailableError`` if the access token must be
        refreshed but Keycloak cannot be reached; the Session is kept then.
        """
        session = await self._get(session_id)
        if session_id is None or session is None or session.tokens is None:
            self._count_failure(client_ip)
            return None

        now = self._clock.now()
        reason = expiry_reason(session, now, self._settings.timeouts)
        if reason is not None:
            await self._end_quietly(
                _Ending(session=session, session_id=session_id, expired_at=now),
                reason,
                client_ip,
                correlation_id,
            )
            return None

        if access_token_expired(session.tokens, now):
            refreshed = await self._refresh(session, session.tokens)
            if refreshed is None:
                await self._end_quietly(
                    _Ending(session=session, session_id=session_id),
                    ReasonCode.REFRESH_REFUSED,
                    client_ip,
                    correlation_id,
                )
                return None
            session = refreshed

        session = dataclasses.replace(session, last_seen_at=now)
        async with self._unit_of_work.begin() as transaction:
            saved = await transaction.sessions.save(session_id, session)
        if not saved:
            return None
        return ActiveSession(session_id=session_id, session=session)

    async def sign_out(
        self, active: ActiveSession, *, client_ip: str | None, correlation_id: str
    ) -> str:
        """End the Session after recording ``sign-out``/``allowed``; return the Keycloak logout URL.

        The caller has authorised the request. The URL is Keycloak's
        ``end_session_endpoint`` with ``id_token_hint`` and the configured
        post-sign-out redirect URI; it is built first, so nothing is ended if
        Keycloak's metadata cannot be read. Raises ``AuditWriteFailedError``
        (or the unit of work's error for an aborted transaction) if the entry
        could not be stored; the Session is kept then.
        """
        tokens = active.session.tokens
        url = await self._identity_provider.end_session_url(
            id_token_hint=tokens.id_token if tokens is not None else None,
            post_logout_redirect_uri=self._settings.post_logout_redirect_uri,
        )
        entry = AuditEntry(
            occurred_at=self._clock.now(),
            environment=self._settings.environment,
            action=SIGN_OUT_ACTION,
            outcome=Outcome.ALLOWED,
            user_subject=active.session.user_subject,
            username=active.session.username,
            correlation_id=correlation_id,
            client_ip=client_ip,
        )
        async with self._unit_of_work.begin() as transaction:
            recorder = AuditRecorder(repository=transaction.audit_repository, sink=self._audit_sink)
            await recorder.record_then_act(
                entry, lambda: transaction.sessions.remove(active.session_id)
            )
        return url

    async def end_by_logout_token(
        self, logout_token: str, *, client_ip: str | None, correlation_id: str
    ) -> int:
        """End the Sessions of the Keycloak session a back-channel logout names.

        Returns how many were ended. Raises ``InvalidLogoutTokenError`` for an
        invalid token, which is counted on stdout under ``client_ip``. Every
        Session is tried; if an entry could not be stored, its Session stays
        and the first error is raised afterwards, so Keycloak sees a failure.
        The entries carry no client IP: the request comes from Keycloak, not
        from the user's browser.
        """
        try:
            notice = await self._identity_provider.verify_logout_token(logout_token)
        except InvalidLogoutTokenError:
            if client_ip is not None:
                self._failures.record(client_ip, ReasonCode.INVALID_LOGOUT_TOKEN)
            raise
        async with self._unit_of_work.begin() as transaction:
            found = await transaction.sessions.find_by_keycloak_session_id(
                notice.keycloak_session_id
            )
        ended = 0
        first_error: Exception | None = None
        for stored in found:
            ending = _Ending(session=stored.session, ref=stored.ref)
            try:
                if await self._end(ending, ReasonCode.BACKCHANNEL_LOGOUT, None, correlation_id):
                    ended += 1
            except Exception as error:
                first_error = first_error or error
        if first_error is not None:
            raise first_error
        return ended

    async def expire_abandoned(self) -> int:
        """End every Session past its idle timeout or absolute lifetime; return how many.

        All entries of one sweep share a correlation id. A Session whose entry
        cannot be stored stays, and is tried again by the next sweep.
        """
        now = self._clock.now()
        correlation_id = f"expiry-sweep-{uuid.uuid4().hex}"
        idle_since = now - self._settings.timeouts.idle_timeout
        ended = 0
        while True:
            async with self._unit_of_work.begin() as transaction:
                found = await transaction.sessions.find_expired(
                    last_seen_until=idle_since, now=now, limit=SWEEP_BATCH_SIZE
                )
            ended_in_batch = 0
            for stored in found:
                reason = expiry_reason(stored.session, now, self._settings.timeouts)
                ending = _Ending(session=stored.session, ref=stored.ref, expired_at=now)
                with contextlib.suppress(Exception):
                    if await self._end(ending, reason or ReasonCode.IDLE, None, correlation_id):
                        ended_in_batch += 1
            ended += ended_in_batch
            # A short batch was the last one. A batch in which nothing could
            # be ended would be found again, so the next sweep retries it.
            if len(found) < SWEEP_BATCH_SIZE or ended_in_batch == 0:
                break
        async with self._unit_of_work.begin() as transaction:
            await transaction.sign_in_attempts.purge_expired(now)
        return ended

    async def _get(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        async with self._unit_of_work.begin() as transaction:
            return await transaction.sessions.get(session_id)

    async def _refresh(self, session: Session, tokens: SessionTokens) -> Session | None:
        """The Session with new tokens and roles; ``None`` if Keycloak refuses."""
        if tokens.refresh_token is None:
            return None
        try:
            identity = await self._identity_provider.refresh(tokens.refresh_token)
        except RefreshRefusedError:
            return None
        if identity.subject != session.user_subject:
            return None
        return self._with_identity(session, tokens, identity)

    def _with_identity(
        self, session: Session, tokens: SessionTokens, identity: VerifiedIdentity
    ) -> Session:
        role = role_from_claims(identity.claims, self._settings.role_mapping)
        fresh = identity.tokens
        return dataclasses.replace(
            session,
            username=identity.username or session.username,
            roles=frozenset({role}) if role is not None else frozenset(),
            tokens=SessionTokens(
                access_token=fresh.access_token,
                refresh_token=fresh.refresh_token or tokens.refresh_token,
                id_token=fresh.id_token or tokens.id_token,
                access_token_expires_at=fresh.access_token_expires_at,
            ),
        )

    async def _end(
        self,
        ending: _Ending,
        reason: ReasonCode,
        client_ip: str | None,
        correlation_id: str,
    ) -> bool:
        """Remove the Session and record its ``session-expired`` entry, both or neither.

        Returns whether this call ended it. Raises if the entry could not be
        stored; the failure is written to stdout first, and the Session stays.
        """
        entry = AuditEntry(
            occurred_at=self._clock.now(),
            environment=self._settings.environment,
            action=SESSION_EXPIRED_ACTION,
            outcome=Outcome.INFO,
            reason=reason,
            user_subject=ending.session.user_subject,
            username=ending.session.username,
            correlation_id=correlation_id,
            client_ip=client_ip,
        )
        async with self._unit_of_work.begin() as transaction:
            removed = await self._remove(transaction.sessions, ending)
            if removed:
                try:
                    await transaction.audit_repository.add(entry)
                except Exception as error:
                    with contextlib.suppress(Exception):
                        self._audit_sink.audit_write_failed(entry, error)
                    raise
        return removed

    async def _remove(self, store: SessionStore, ending: _Ending) -> bool:
        """Remove the Session ``ending`` names; only while still expired if it expired."""
        if ending.expired_at is None:
            if ending.session_id is not None:
                return await store.remove(ending.session_id)
            if ending.ref is not None:
                return await store.remove_by_ref(ending.ref)
        else:
            idle_since = ending.expired_at - self._settings.timeouts.idle_timeout
            if ending.session_id is not None:
                return await store.remove_expired(
                    ending.session_id, last_seen_until=idle_since, now=ending.expired_at
                )
            if ending.ref is not None:
                return await store.remove_expired_by_ref(
                    ending.ref, last_seen_until=idle_since, now=ending.expired_at
                )
        raise ValueError("an ending needs a session id or a ref")  # pragma: no cover

    async def _end_quietly(
        self,
        ending: _Ending,
        reason: ReasonCode,
        client_ip: str | None,
        correlation_id: str,
    ) -> None:
        """End the Session during a request, which gets a 401 either way.

        A failure to record the expiry is already on stdout; the Session then
        stays and the expiry sweep records it later.
        """
        with contextlib.suppress(Exception):
            await self._end(ending, reason, client_ip, correlation_id)

    def _count_failure(self, client_ip: str | None) -> None:
        if client_ip is not None:
            self._failures.record(client_ip, ReasonCode.NO_SESSION)
