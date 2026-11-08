"""The identity of the Environment an Admin Tool Instance belongs to.

Every Admin Tool Instance is installed in exactly one Environment (ADR 0001)
and is configured with that Environment's Municipality, stage and an optional
label (spec: environment-context). An instance must refuse to start with a
missing or invalid identity, so these types reject such values when they are
constructed instead of when they are first used.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

type IdentityField = Literal["municipality", "stage", "label"]


class InvalidEnvironmentIdentityError(ValueError):
    """A configured Environment identity value is missing or invalid.

    ``field`` names the offending part, so the configuration layer can report
    the setting it came from.
    """

    def __init__(self, field: IdentityField, problem: str) -> None:
        super().__init__(f"invalid Environment identity: {field} {problem}")
        self.field: IdentityField = field


class Stage(StrEnum):
    """The stage that identifies an Environment within its Municipality."""

    TEST = "test"
    ACCP = "accp"
    PROD = "prod"

    @classmethod
    def parse(cls, value: str) -> Stage:
        """Return the stage for a configured value; only the exact values are accepted."""
        try:
            return cls(value)
        except ValueError:
            allowed = ", ".join(stage.value for stage in cls)
            raise InvalidEnvironmentIdentityError(
                "stage", f"must be one of {allowed}, got {value!r}"
            ) from None

    @property
    def display_name(self) -> str:
        """The Dutch name shown to users, for example in the Environment banner."""
        return _DISPLAY_NAMES[self]


_DISPLAY_NAMES: dict[Stage, str] = {
    Stage.TEST: "Test",
    Stage.ACCP: "Acceptatie",
    Stage.PROD: "Productie",
}


@dataclass(frozen=True, slots=True)
class EnvironmentIdentity:
    """Which Municipality's Environment this Admin Tool Instance belongs to.

    The Municipality and stage are required. The label is optional and is shown
    next to the stage, for example the name of the hosting party. Surrounding
    whitespace is trimmed, and a blank label counts as no label.
    """

    municipality: str
    stage: Stage
    label: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.municipality, str) or not self.municipality.strip():
            raise InvalidEnvironmentIdentityError("municipality", "is required")
        if not isinstance(self.stage, Stage):
            raise InvalidEnvironmentIdentityError(
                "stage", f"must be a Stage, got {type(self.stage).__name__}"
            )
        if self.label is not None and not isinstance(self.label, str):
            raise InvalidEnvironmentIdentityError("label", "must be text when given")

        # Normalise in place; object.__setattr__ is the documented way to do
        # this in a frozen dataclass.
        object.__setattr__(self, "municipality", self.municipality.strip())
        label = self.label.strip() if self.label is not None else ""
        object.__setattr__(self, "label", label or None)

    @classmethod
    def from_config(
        cls, *, municipality: str | None, stage: str | None, label: str | None = None
    ) -> EnvironmentIdentity:
        """Build the identity from configured text values, rejecting missing ones."""
        if municipality is None:
            raise InvalidEnvironmentIdentityError("municipality", "is required")
        if stage is None:
            raise InvalidEnvironmentIdentityError("stage", "is required")
        return cls(municipality=municipality, stage=Stage.parse(stage), label=label)
