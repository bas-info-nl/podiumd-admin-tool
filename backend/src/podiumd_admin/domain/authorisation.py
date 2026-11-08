"""Permissions and the authorisation policy.

Spec: access-control, "Permission catalogue" and "Every request is authorised
on the server". Design D3: authorisation is one domain policy, the central
``PERMISSIONS`` mapping from each Permission to the roles that hold it. Code
never checks roles directly; later changes add their permissions, including
Operator-only ones, to this mapping.

The HTTP adapter enforces the policy (``require(permission)``) and records a
denied Audit Entry with the reason returned here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

from podiumd_admin.domain.roles import Role


class Permission(StrEnum):
    """A named right to perform a read or an action."""

    AUDIT_LOG_READ = "audit-log:read"
    SESSION_SIGN_OUT = "session:sign-out"


PERMISSIONS: Final[dict[Permission, frozenset[Role]]] = {
    Permission.AUDIT_LOG_READ: frozenset({Role.VIEWER, Role.OPERATOR}),
    Permission.SESSION_SIGN_OUT: frozenset({Role.VIEWER, Role.OPERATOR}),
}
"""The roles that hold each Permission. An Operator holds every Viewer permission."""


class DenialReason(StrEnum):
    """Why authorisation was denied; recorded as the reason of a denied Audit Entry."""

    NO_ROLE = "no-role"
    MISSING_PERMISSION = "missing-permission"


@dataclass(frozen=True, slots=True)
class User:
    """A signed-in user, as far as authorisation is concerned.

    ``subject`` is the token's ``sub`` claim. ``role`` is the Role their token
    claims grant, or ``None`` when they hold neither role.
    """

    subject: str
    role: Role | None

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise ValueError("subject is required")
        if self.role is not None and not isinstance(self.role, Role):
            raise ValueError(f"role must be a Role or None, got {self.role!r}")


@dataclass(frozen=True, slots=True)
class Allowed:
    """The user holds the required Permission."""

    permission: Permission

    @property
    def allowed(self) -> Literal[True]:
        return True


@dataclass(frozen=True, slots=True)
class Denied:
    """The user does not hold the required Permission, for the given reason."""

    permission: Permission
    reason: DenialReason

    @property
    def allowed(self) -> Literal[False]:
        return False


type AuthorisationDecision = Allowed | Denied


def authorise(
    user: User,
    permission: Permission,
    permissions: Mapping[Permission, frozenset[Role]] = PERMISSIONS,
) -> AuthorisationDecision:
    """Decide whether ``user`` holds ``permission``.

    A user without a role is denied with ``no-role``. A user whose role does not
    hold the permission, or a permission the catalogue does not list, is denied
    with ``missing-permission``. ``permissions`` defaults to the central
    catalogue and is only replaced in tests.
    """
    if user.role is None:
        return Denied(permission=permission, reason=DenialReason.NO_ROLE)
    if user.role in permissions.get(permission, frozenset()):
        return Allowed(permission=permission)
    return Denied(permission=permission, reason=DenialReason.MISSING_PERMISSION)
