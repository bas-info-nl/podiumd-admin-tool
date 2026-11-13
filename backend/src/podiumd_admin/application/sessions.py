"""Sessions after sign-in: resuming, refreshing, ending and expiring them.

Spec: authentication, "Session lifetime and expiry" and "Sign-out". Design D2.
"""

from __future__ import annotations

from podiumd_admin.application.authentication import AuthSettings
from podiumd_admin.application.unauthenticated_failures import UnauthenticatedFailureAggregator
from podiumd_admin.ports.audit import AuditSink
from podiumd_admin.ports.clock import Clock
from podiumd_admin.ports.identity_provider import IdentityProvider
from podiumd_admin.ports.unit_of_work import UnitOfWork


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
