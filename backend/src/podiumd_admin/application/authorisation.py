"""Authorising the action of a signed-in user, and recording a refusal.

Spec: access-control, "Every request is authorised on the server" and
"Actions are protected against cross-site requests"; audit-log, "No action
without an Audit Entry". Design D3 and D4:

- the decision is the domain policy ``authorise`` over ``PERMISSIONS``;
- a refusal is recorded as a ``denied`` Audit Entry with the reason
  (``no-role``, ``missing-permission`` or ``csrf``) and, for a permission,
  the required permission as a parameter;
- the request is refused even when that entry cannot be stored; the failure
  is then written to stdout.

Permitted requests are not recorded here: an allowed action records its own
``allowed`` entry before it takes effect.
"""

from __future__ import annotations

import contextlib
from typing import NoReturn

from podiumd_admin.application.audit import AuditRecorder
from podiumd_admin.application.authentication import AuthSettings
from podiumd_admin.application.sessions import ActiveSession
from podiumd_admin.domain.audit import AuditEntry, Outcome, ParameterValue, ReasonCode
from podiumd_admin.domain.authorisation import Denied, Permission, authorise
from podiumd_admin.ports.audit import AuditSink
from podiumd_admin.ports.clock import Clock
from podiumd_admin.ports.unit_of_work import UnitOfWork

PERMISSION_PARAMETER = "permission"


class AccessDeniedError(Exception):
    """The request was refused, for ``reason``; its denied entry has been recorded."""

    def __init__(self, reason: ReasonCode) -> None:
        super().__init__(f"access denied: {reason}")
        self.reason = reason


class Authoriser:
    """Checks a signed-in user's permission and records refusals."""

    def __init__(
        self,
        *,
        settings: AuthSettings,
        unit_of_work: UnitOfWork,
        audit_sink: AuditSink,
        clock: Clock,
    ) -> None:
        self._settings = settings
        self._unit_of_work = unit_of_work
        self._audit_sink = audit_sink
        self._clock = clock

    async def require(
        self,
        active: ActiveSession,
        permission: Permission,
        *,
        action: str,
        target: str,
        client_ip: str | None,
        correlation_id: str,
    ) -> None:
        """Return if the user holds ``permission``; else record and raise ``AccessDeniedError``."""
        decision = authorise(active.user, permission)
        if isinstance(decision, Denied):
            await self._refuse(
                active,
                decision.reason,
                action=action,
                target=target,
                client_ip=client_ip,
                correlation_id=correlation_id,
                parameters={PERMISSION_PARAMETER: permission.value},
            )

    async def refuse_cross_site(
        self,
        active: ActiveSession,
        *,
        action: str,
        target: str,
        client_ip: str | None,
        correlation_id: str,
    ) -> NoReturn:
        """Record an action without the CSRF header as denied, and raise ``AccessDeniedError``."""
        await self._refuse(
            active,
            ReasonCode.CSRF,
            action=action,
            target=target,
            client_ip=client_ip,
            correlation_id=correlation_id,
            parameters={},
        )

    async def _refuse(
        self,
        active: ActiveSession,
        reason: ReasonCode,
        *,
        action: str,
        target: str,
        client_ip: str | None,
        correlation_id: str,
        parameters: dict[str, ParameterValue],
    ) -> NoReturn:
        entry = AuditEntry(
            occurred_at=self._clock.now(),
            environment=self._settings.environment,
            action=action,
            target=target,
            outcome=Outcome.DENIED,
            reason=reason,
            parameters=parameters,
            user_subject=active.session.user_subject,
            username=active.session.username,
            correlation_id=correlation_id,
            client_ip=client_ip,
        )
        # A failed insert is written to stdout by record_denial; the commit of
        # the transaction it aborted then raises, which must not turn the
        # refusal into anything else.
        with contextlib.suppress(Exception):
            async with self._unit_of_work.begin() as transaction:
                recorder = AuditRecorder(
                    repository=transaction.audit_repository, sink=self._audit_sink
                )
                await recorder.record_denial(entry)
        raise AccessDeniedError(reason)
