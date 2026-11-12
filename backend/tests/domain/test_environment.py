"""EnvironmentIdentity: the Municipality and stage an Admin Tool Instance belongs to.

Spec: environment-context, "Environment identity is configured at installation".
The Admin Tool Instance refuses to start with a missing or invalid identity, so
the domain object rejects such values on construction.
"""

from __future__ import annotations

import dataclasses

import pytest

from podiumd_admin.domain.environment import (
    EnvironmentIdentity,
    InvalidEnvironmentIdentityError,
    Stage,
)


def test_identity_holds_municipality_stage_and_label() -> None:
    identity = EnvironmentIdentity(municipality="Onsdorp", stage=Stage.PROD, label="Hoster B.V.")

    assert identity.municipality == "Onsdorp"
    assert identity.stage is Stage.PROD
    assert identity.label == "Hoster B.V."


def test_label_is_optional() -> None:
    identity = EnvironmentIdentity(municipality="Onsdorp", stage=Stage.ACCP)

    assert identity.label is None


def test_identity_is_immutable() -> None:
    identity = EnvironmentIdentity(municipality="Onsdorp", stage=Stage.TEST)

    with pytest.raises(dataclasses.FrozenInstanceError):
        identity.municipality = "Amsterdam"  # type: ignore[misc]


def test_surrounding_whitespace_is_trimmed() -> None:
    identity = EnvironmentIdentity(municipality="  Onsdorp ", stage=Stage.TEST, label=" Hoster ")

    assert identity.municipality == "Onsdorp"
    assert identity.label == "Hoster"


@pytest.mark.parametrize("label", ["", "   "])
def test_blank_label_means_no_label(label: str) -> None:
    identity = EnvironmentIdentity(municipality="Onsdorp", stage=Stage.TEST, label=label)

    assert identity.label is None


@pytest.mark.parametrize("municipality", ["", "   ", "\t\n"])
def test_blank_municipality_is_rejected(municipality: str) -> None:
    with pytest.raises(InvalidEnvironmentIdentityError) as excinfo:
        EnvironmentIdentity(municipality=municipality, stage=Stage.PROD)

    assert excinfo.value.field == "municipality"


def test_non_text_municipality_is_rejected() -> None:
    with pytest.raises(InvalidEnvironmentIdentityError) as excinfo:
        EnvironmentIdentity(municipality=None, stage=Stage.PROD)  # type: ignore[arg-type]

    assert excinfo.value.field == "municipality"


@pytest.mark.parametrize("stage", ["prod", None, 1])
def test_stage_that_is_not_a_stage_member_is_rejected(stage: object) -> None:
    with pytest.raises(InvalidEnvironmentIdentityError) as excinfo:
        EnvironmentIdentity(municipality="Onsdorp", stage=stage)  # type: ignore[arg-type]

    assert excinfo.value.field == "stage"


def test_non_text_label_is_rejected() -> None:
    with pytest.raises(InvalidEnvironmentIdentityError) as excinfo:
        EnvironmentIdentity(municipality="Onsdorp", stage=Stage.PROD, label=42)  # type: ignore[arg-type]

    assert excinfo.value.field == "label"


def test_invalid_identity_error_is_a_value_error_naming_the_field() -> None:
    with pytest.raises(ValueError, match="municipality"):
        EnvironmentIdentity(municipality="", stage=Stage.PROD)


# --- Stage --------------------------------------------------------------------


def test_there_are_exactly_three_stages() -> None:
    assert [stage.value for stage in Stage] == ["test", "accp", "prod"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("test", Stage.TEST), ("accp", Stage.ACCP), ("prod", Stage.PROD)],
)
def test_stage_parses_its_configured_value(value: str, expected: Stage) -> None:
    assert Stage.parse(value) is expected


@pytest.mark.parametrize("value", ["", "dev", "production", "PROD", " prod", "acc"])
def test_stage_rejects_any_other_value(value: str) -> None:
    with pytest.raises(InvalidEnvironmentIdentityError) as excinfo:
        Stage.parse(value)

    assert excinfo.value.field == "stage"


@pytest.mark.parametrize(
    ("stage", "name"),
    [(Stage.TEST, "Test"), (Stage.ACCP, "Acceptatie"), (Stage.PROD, "Productie")],
)
def test_stage_has_its_display_name(stage: Stage, name: str) -> None:
    assert stage.display_name == name


# --- Building from configured values -------------------------------------------


def test_identity_is_built_from_configured_text_values() -> None:
    identity = EnvironmentIdentity.from_config(municipality="Onsdorp", stage="accp", label=None)

    assert identity == EnvironmentIdentity(municipality="Onsdorp", stage=Stage.ACCP)


@pytest.mark.parametrize("stage", [None, "", "staging"])
def test_identity_from_config_rejects_a_missing_or_invalid_stage(stage: str | None) -> None:
    with pytest.raises(InvalidEnvironmentIdentityError) as excinfo:
        EnvironmentIdentity.from_config(municipality="Onsdorp", stage=stage)

    assert excinfo.value.field == "stage"


def test_identity_from_config_rejects_a_missing_municipality() -> None:
    with pytest.raises(InvalidEnvironmentIdentityError) as excinfo:
        EnvironmentIdentity.from_config(municipality=None, stage="prod")

    assert excinfo.value.field == "municipality"
