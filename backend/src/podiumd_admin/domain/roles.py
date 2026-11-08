"""The two roles of the Admin Tool and how they are read from token claims.

Spec: access-control, "Roles". Design D3: roles are Keycloak client roles of
the Admin Tool's OIDC client. They are read from a configurable claim path, by
default ``resource_access.<client_id>.roles``, and the configured role names
(``auth.roles.viewer``, ``auth.roles.operator``; defaults ``viewer`` and
``operator``) map to Viewer and Operator.

The mapping works on the plain, already validated claims dictionary, so it does
not depend on any OIDC library (ADR 0009).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

DEFAULT_VIEWER_ROLE_NAME = "viewer"
DEFAULT_OPERATOR_ROLE_NAME = "operator"


class Role(StrEnum):
    """A role in the Admin Tool. An Operator can do everything a Viewer can."""

    VIEWER = "viewer"
    OPERATOR = "operator"


class InvalidRoleMappingError(ValueError):
    """The configured claim path or role names are invalid."""


@dataclass(frozen=True, slots=True)
class RoleMapping:
    """Where the roles are in the token claims, and which names mean which Role."""

    claim_path: tuple[str, ...]
    viewer_role_name: str = DEFAULT_VIEWER_ROLE_NAME
    operator_role_name: str = DEFAULT_OPERATOR_ROLE_NAME

    def __post_init__(self) -> None:
        if (
            not isinstance(self.claim_path, tuple)
            or not self.claim_path
            or not all(isinstance(segment, str) and segment.strip() for segment in self.claim_path)
        ):
            raise InvalidRoleMappingError(
                "claim_path must be a non-empty tuple of non-blank claim names"
            )
        for field in ("viewer_role_name", "operator_role_name"):
            name = getattr(self, field)
            if not isinstance(name, str) or not name.strip():
                raise InvalidRoleMappingError(f"{field} must be a non-blank role name")
        if self.viewer_role_name == self.operator_role_name:
            raise InvalidRoleMappingError(
                "viewer_role_name and operator_role_name must differ, "
                f"both are {self.viewer_role_name!r}"
            )

    @classmethod
    def for_client(
        cls,
        client_id: str,
        *,
        viewer_role_name: str = DEFAULT_VIEWER_ROLE_NAME,
        operator_role_name: str = DEFAULT_OPERATOR_ROLE_NAME,
    ) -> RoleMapping:
        """The default mapping: the client roles of ``client_id`` in ``resource_access``."""
        return cls(
            claim_path=("resource_access", client_id, "roles"),
            viewer_role_name=viewer_role_name,
            operator_role_name=operator_role_name,
        )


def role_from_claims(claims: Mapping[str, object], mapping: RoleMapping) -> Role | None:
    """Return the Role the token claims grant, or ``None`` if they grant none.

    A user holding both roles is an Operator. The lookup fails closed: a
    missing claim, or a claim that is not a list of role names, grants no role.
    Role names match exactly, and entries that are not text are ignored.
    """
    value: object = claims
    for segment in mapping.claim_path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(segment)

    if not isinstance(value, list | tuple):
        return None
    names = {name for name in value if isinstance(name, str)}

    if mapping.operator_role_name in names:
        return Role.OPERATOR
    if mapping.viewer_role_name in names:
        return Role.VIEWER
    return None
