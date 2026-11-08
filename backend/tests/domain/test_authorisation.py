"""The central Permission catalogue and the authorise policy.

Spec: access-control, "Permission catalogue" and "Every request is authorised
on the server". Design D3: one domain policy,
a read-only ``PERMISSIONS`` mapping from each Permission to its roles. Every permission is tested
against every role, and against a user without a role.
"""

from __future__ import annotations

import dataclasses
import inspect
import itertools

import pytest

from podiumd_admin.domain import authorisation
from podiumd_admin.domain.audit import DENIAL_REASONS, ReasonCode
from podiumd_admin.domain.authorisation import (
    PERMISSIONS,
    Allowed,
    Denied,
    Permission,
    User,
    _authorise_with,
    authorise,
)
from podiumd_admin.domain.roles import Role

# The expected catalogue, written out independently of PERMISSIONS. When a
# change adds a permission, this table must be extended too (see the coverage
# test below), so every permission is always checked against every role.
EXPECTED_ROLES: dict[Permission, frozenset[Role]] = {
    Permission.AUDIT_LOG_READ: frozenset({Role.VIEWER, Role.OPERATOR}),
    Permission.SESSION_SIGN_OUT: frozenset({Role.VIEWER, Role.OPERATOR}),
}

ROLES_AND_NO_ROLE: list[Role | None] = [*Role, None]


def _user(role: Role | None) -> User:
    return User(subject="f3b2c1d0-0000-4000-8000-000000000001", role=role)


# --- Permission ---------------------------------------------------------------


def test_permissions_have_their_catalogue_names() -> None:
    assert Permission.AUDIT_LOG_READ.value == "audit-log:read"
    assert Permission.SESSION_SIGN_OUT.value == "session:sign-out"


def test_this_change_defines_exactly_these_permissions() -> None:
    assert set(Permission) == {Permission.AUDIT_LOG_READ, Permission.SESSION_SIGN_OUT}


# --- PERMISSIONS catalogue ----------------------------------------------------


def test_expected_table_covers_every_permission() -> None:
    assert set(EXPECTED_ROLES) == set(Permission)


def test_catalogue_maps_every_permission() -> None:
    assert set(PERMISSIONS) == set(Permission)


@pytest.mark.parametrize(
    ("permission", "role"),
    list(itertools.product(Permission, Role)),
    ids=lambda value: str(value),
)
def test_catalogue_grants_each_permission_to_exactly_the_expected_roles(
    permission: Permission, role: Role
) -> None:
    assert (role in PERMISSIONS[permission]) is (role in EXPECTED_ROLES[permission])


@pytest.mark.parametrize("permission", list(Permission), ids=str)
def test_catalogue_entries_are_immutable_non_empty_role_sets(permission: Permission) -> None:
    roles = PERMISSIONS[permission]

    assert isinstance(roles, frozenset)
    assert roles
    assert all(isinstance(role, Role) for role in roles)


def test_catalogue_cannot_be_changed_at_runtime() -> None:
    with pytest.raises(TypeError):
        PERMISSIONS[Permission.AUDIT_LOG_READ] = frozenset()  # type: ignore[index]
    with pytest.raises(TypeError):
        del PERMISSIONS[Permission.AUDIT_LOG_READ]  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        PERMISSIONS.clear()  # type: ignore[attr-defined]

    assert PERMISSIONS[Permission.AUDIT_LOG_READ] == EXPECTED_ROLES[Permission.AUDIT_LOG_READ]


@pytest.mark.parametrize("permission", list(Permission), ids=str)
def test_operator_holds_every_viewer_permission(permission: Permission) -> None:
    if Role.VIEWER in PERMISSIONS[permission]:
        assert Role.OPERATOR in PERMISSIONS[permission]


# --- authorise: every permission x every role ---------------------------------


@pytest.mark.parametrize(
    ("permission", "role"),
    list(itertools.product(Permission, ROLES_AND_NO_ROLE)),
    ids=lambda value: str(value),
)
def test_authorise_decides_every_permission_for_every_role(
    permission: Permission, role: Role | None
) -> None:
    decision = authorise(_user(role), permission)

    if role is None:
        assert decision == Denied(permission=permission, reason=ReasonCode.NO_ROLE)
    elif role in EXPECTED_ROLES[permission]:
        assert decision == Allowed(permission=permission)
    else:
        assert decision == Denied(permission=permission, reason=ReasonCode.MISSING_PERMISSION)


@pytest.mark.parametrize("role", list(Role), ids=str)
def test_audit_log_can_be_read_by_viewer_and_operator(role: Role) -> None:
    decision = authorise(_user(role), Permission.AUDIT_LOG_READ)

    assert decision.allowed


def test_authorise_takes_exactly_a_user_and_a_permission() -> None:
    # The catalogue is not injectable through the public policy, so no caller
    # can authorise against anything but the central PERMISSIONS.
    assert list(inspect.signature(authorise).parameters) == ["user", "permission"]


# --- authorise: denial reasons --------------------------------------------------

OPERATOR_ONLY: dict[Permission, frozenset[Role]] = {
    Permission.AUDIT_LOG_READ: frozenset({Role.OPERATOR}),
}


def test_user_without_the_permission_is_denied_with_missing_permission() -> None:
    decision = _authorise_with(_user(Role.VIEWER), Permission.AUDIT_LOG_READ, OPERATOR_ONLY)

    assert decision == Denied(
        permission=Permission.AUDIT_LOG_READ, reason=ReasonCode.MISSING_PERMISSION
    )
    assert not decision.allowed


def test_user_with_the_permission_is_allowed_by_a_custom_catalogue() -> None:
    decision = _authorise_with(_user(Role.OPERATOR), Permission.AUDIT_LOG_READ, OPERATOR_ONLY)

    assert decision == Allowed(permission=Permission.AUDIT_LOG_READ)


def test_permission_missing_from_the_catalogue_is_denied() -> None:
    # Fail closed: a permission nobody holds is denied, not an error.
    decision = _authorise_with(_user(Role.OPERATOR), Permission.SESSION_SIGN_OUT, OPERATOR_ONLY)

    assert decision == Denied(
        permission=Permission.SESSION_SIGN_OUT, reason=ReasonCode.MISSING_PERMISSION
    )


def test_no_role_takes_precedence_over_missing_permission() -> None:
    decision = _authorise_with(_user(None), Permission.SESSION_SIGN_OUT, OPERATOR_ONLY)

    assert decision == Denied(permission=Permission.SESSION_SIGN_OUT, reason=ReasonCode.NO_ROLE)


def test_denial_reasons_are_audit_reason_codes() -> None:
    # One source of reason codes: the policy returns ReasonCode members, so a
    # denied Audit Entry stores the policy's reason as is.
    assert ReasonCode.NO_ROLE.value == "no-role"
    assert ReasonCode.MISSING_PERMISSION.value == "missing-permission"
    assert {ReasonCode.NO_ROLE, ReasonCode.MISSING_PERMISSION} <= DENIAL_REASONS
    assert not hasattr(authorisation, "DenialReason")


@pytest.mark.parametrize(
    "reason",
    sorted(set(ReasonCode) - {ReasonCode.NO_ROLE, ReasonCode.MISSING_PERMISSION}),
    ids=str,
)
def test_denied_accepts_only_authorisation_reasons(reason: ReasonCode) -> None:
    with pytest.raises(ValueError, match="reason"):
        Denied(permission=Permission.AUDIT_LOG_READ, reason=reason)  # type: ignore[arg-type]


def test_decisions_name_the_required_permission() -> None:
    allowed = authorise(_user(Role.VIEWER), Permission.SESSION_SIGN_OUT)
    denied = authorise(_user(None), Permission.AUDIT_LOG_READ)

    assert allowed.permission is Permission.SESSION_SIGN_OUT
    assert denied.permission is Permission.AUDIT_LOG_READ


def test_decisions_can_be_matched_on_their_kind() -> None:
    match authorise(_user(None), Permission.AUDIT_LOG_READ):
        case Denied(reason=reason):
            assert reason is ReasonCode.NO_ROLE
        case Allowed():
            pytest.fail("a user without a role must be denied")


# --- User -----------------------------------------------------------------------


def test_user_holds_a_subject_and_an_optional_role() -> None:
    user = User(subject="abc", role=None)

    assert user.subject == "abc"
    assert user.role is None


def test_user_is_immutable() -> None:
    user = _user(Role.VIEWER)

    with pytest.raises(dataclasses.FrozenInstanceError):
        user.role = Role.OPERATOR  # type: ignore[misc]


@pytest.mark.parametrize("subject", ["", "   "])
def test_user_requires_a_subject(subject: str) -> None:
    with pytest.raises(ValueError, match="subject"):
        User(subject=subject, role=Role.VIEWER)


def test_user_rejects_a_role_that_is_not_a_role_member() -> None:
    # "operator" is the default Keycloak name, but only a mapped Role counts.
    with pytest.raises(ValueError, match="role"):
        User(subject="abc", role="operator")  # type: ignore[arg-type]
