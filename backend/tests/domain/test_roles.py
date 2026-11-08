"""Roles and the mapping from token claims to a Role.

Spec: access-control, "Roles". Design D3: the roles are read from a
configurable claim path, by default ``resource_access.<client_id>.roles``, and
the role names that map to Viewer and Operator are configurable, defaulting to
``viewer`` and ``operator``. A user holding both roles is an Operator.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from podiumd_admin.domain.roles import (
    InvalidRoleMappingError,
    Role,
    RoleMapping,
    role_from_claims,
)

CLIENT_ID = "podiumd-admin"


def _claims_with_client_roles(*roles: Any) -> dict[str, Any]:
    return {
        "sub": "f3b2c1d0",
        "resource_access": {
            CLIENT_ID: {"roles": list(roles)},
            "account": {"roles": ["manage-account"]},
        },
    }


@pytest.fixture
def mapping() -> RoleMapping:
    return RoleMapping.for_client(CLIENT_ID)


# --- Role ---------------------------------------------------------------------


def test_there_are_exactly_two_roles() -> None:
    assert set(Role) == {Role.VIEWER, Role.OPERATOR}


# --- RoleMapping defaults and validation ----------------------------------------


def test_default_mapping_reads_the_client_roles_of_the_admin_tool_client(
    mapping: RoleMapping,
) -> None:
    assert mapping.claim_path == ("resource_access", CLIENT_ID, "roles")
    assert mapping.viewer_role_name == "viewer"
    assert mapping.operator_role_name == "operator"


def test_role_names_and_claim_path_are_configurable() -> None:
    mapping = RoleMapping(
        claim_path=("realm_access", "roles"),
        viewer_role_name="admin-tool-viewer",
        operator_role_name="admin-tool-operator",
    )

    assert mapping.claim_path == ("realm_access", "roles")
    assert mapping.viewer_role_name == "admin-tool-viewer"
    assert mapping.operator_role_name == "admin-tool-operator"


def test_mapping_is_immutable(mapping: RoleMapping) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        mapping.viewer_role_name = "operator"  # type: ignore[misc]


@pytest.mark.parametrize("claim_path", [(), ("resource_access", ""), ("resource_access", "  ")])
def test_mapping_rejects_an_empty_claim_path_or_segment(claim_path: tuple[str, ...]) -> None:
    with pytest.raises(InvalidRoleMappingError, match="claim_path"):
        RoleMapping(claim_path=claim_path)


def test_mapping_rejects_a_claim_path_given_as_plain_text() -> None:
    # A str is a sequence of characters; accepting it would silently look up "r", "o", ...
    with pytest.raises(InvalidRoleMappingError, match="claim_path"):
        RoleMapping(claim_path="resource_access.podiumd-admin.roles")  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["viewer_role_name", "operator_role_name"])
@pytest.mark.parametrize("name", ["", "   "])
def test_mapping_rejects_a_blank_role_name(field: str, name: str) -> None:
    with pytest.raises(InvalidRoleMappingError, match=field):
        RoleMapping(claim_path=("roles",), **{field: name})


@pytest.mark.parametrize("field", ["viewer_role_name", "operator_role_name"])
@pytest.mark.parametrize("name", [" viewer", "viewer ", "\tviewer", "viewer\n"])
def test_mapping_rejects_a_role_name_with_surrounding_whitespace(field: str, name: str) -> None:
    # Role names match exactly, so a padded name would silently never match a
    # token. Fail fast at startup instead.
    with pytest.raises(InvalidRoleMappingError, match=f"{field}.*whitespace"):
        RoleMapping(claim_path=("roles",), **{field: name})


def test_for_client_rejects_a_role_name_with_surrounding_whitespace() -> None:
    with pytest.raises(InvalidRoleMappingError, match="operator_role_name"):
        RoleMapping.for_client(CLIENT_ID, operator_role_name="operator ")


def test_mapping_rejects_the_same_name_for_both_roles() -> None:
    with pytest.raises(InvalidRoleMappingError, match="differ"):
        RoleMapping(claim_path=("roles",), viewer_role_name="admin", operator_role_name="admin")


def test_for_client_rejects_a_blank_client_id() -> None:
    with pytest.raises(InvalidRoleMappingError, match="claim_path"):
        RoleMapping.for_client("")


def test_for_client_accepts_configured_role_names() -> None:
    mapping = RoleMapping.for_client(CLIENT_ID, viewer_role_name="v", operator_role_name="o")

    assert (mapping.viewer_role_name, mapping.operator_role_name) == ("v", "o")


# --- role_from_claims ------------------------------------------------------------


def test_viewer_role_maps_to_viewer(mapping: RoleMapping) -> None:
    assert role_from_claims(_claims_with_client_roles("viewer"), mapping) is Role.VIEWER


def test_operator_role_maps_to_operator(mapping: RoleMapping) -> None:
    assert role_from_claims(_claims_with_client_roles("operator"), mapping) is Role.OPERATOR


@pytest.mark.parametrize("roles", [("viewer", "operator"), ("operator", "viewer")])
def test_both_roles_map_to_operator(mapping: RoleMapping, roles: tuple[str, ...]) -> None:
    assert role_from_claims(_claims_with_client_roles(*roles), mapping) is Role.OPERATOR


def test_unrelated_roles_are_ignored(mapping: RoleMapping) -> None:
    claims = _claims_with_client_roles("uma_authorization", "viewer", "offline_access")

    assert role_from_claims(claims, mapping) is Role.VIEWER


def test_no_matching_role_means_no_role(mapping: RoleMapping) -> None:
    assert role_from_claims(_claims_with_client_roles("offline_access"), mapping) is None


def test_empty_role_list_means_no_role(mapping: RoleMapping) -> None:
    assert role_from_claims(_claims_with_client_roles(), mapping) is None


def test_role_names_match_exactly(mapping: RoleMapping) -> None:
    claims = _claims_with_client_roles("Operator", "VIEWER", " viewer", "operators")

    assert role_from_claims(claims, mapping) is None


def test_roles_of_another_client_are_not_used(mapping: RoleMapping) -> None:
    claims = {"resource_access": {"other-client": {"roles": ["operator"]}}}

    assert role_from_claims(claims, mapping) is None


@pytest.mark.parametrize(
    "claims",
    [
        {},
        {"resource_access": {}},
        {"resource_access": {CLIENT_ID: {}}},
        {"resource_access": None},
        {"resource_access": {CLIENT_ID: None}},
        {"resource_access": {CLIENT_ID: {"roles": None}}},
    ],
    ids=["no-claim", "no-client", "no-roles", "null-claim", "null-client", "null-roles"],
)
def test_missing_claim_means_no_role(mapping: RoleMapping, claims: dict[str, Any]) -> None:
    assert role_from_claims(claims, mapping) is None


@pytest.mark.parametrize(
    "claims",
    [
        {"resource_access": ["operator"]},
        {"resource_access": {CLIENT_ID: "operator"}},
        {"resource_access": {CLIENT_ID: {"roles": "operator"}}},
        {"resource_access": {CLIENT_ID: {"roles": {"operator": True}}}},
        {"resource_access": {CLIENT_ID: {"roles": 1}}},
    ],
    ids=["claim-is-list", "client-is-text", "roles-is-text", "roles-is-object", "roles-is-int"],
)
def test_malformed_claim_means_no_role(mapping: RoleMapping, claims: dict[str, Any]) -> None:
    # Fail closed: only a list of role names grants a role.
    assert role_from_claims(claims, mapping) is None


def test_non_text_entries_in_the_role_list_are_ignored(mapping: RoleMapping) -> None:
    claims = _claims_with_client_roles(None, 1, {"name": "operator"}, ["operator"], "viewer")

    assert role_from_claims(claims, mapping) is Role.VIEWER


def test_configured_claim_path_and_names_are_used() -> None:
    mapping = RoleMapping(
        claim_path=("realm_access", "roles"),
        viewer_role_name="admin-tool-viewer",
        operator_role_name="admin-tool-operator",
    )
    claims = {
        "realm_access": {"roles": ["admin-tool-operator"]},
        "resource_access": {CLIENT_ID: {"roles": ["viewer"]}},
    }

    assert role_from_claims(claims, mapping) is Role.OPERATOR


def test_default_names_do_not_apply_when_names_are_configured() -> None:
    mapping = RoleMapping.for_client(
        CLIENT_ID, viewer_role_name="admin-tool-viewer", operator_role_name="admin-tool-operator"
    )

    assert role_from_claims(_claims_with_client_roles("viewer", "operator"), mapping) is None


def test_single_segment_claim_path_is_supported() -> None:
    mapping = RoleMapping(claim_path=("roles",))

    assert role_from_claims({"roles": ["viewer"]}, mapping) is Role.VIEWER
