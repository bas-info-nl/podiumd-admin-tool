"""Audit Entries: what one record in the Audit Log holds.

Spec: audit-log, "What is recorded". Design D4: the outcome is one of
``allowed|denied|succeeded|failed|info``, reason codes come from a fixed enum
so no free text from requests or Keycloak is stored, text fields are truncated
to fixed limits, and parameters never hold secret values.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from podiumd_admin.domain.audit import (
    DENIAL_REASONS,
    MAX_ACTION_LENGTH,
    MAX_CORRELATION_ID_LENGTH,
    MAX_PARAMETER_KEY_LENGTH,
    MAX_PARAMETER_VALUE_LENGTH,
    MAX_PARAMETERS,
    MAX_TARGET_LENGTH,
    MAX_USER_SUBJECT_LENGTH,
    MAX_USERNAME_LENGTH,
    SESSION_EXPIRY_REASONS,
    UNAUTHENTICATED_REASONS,
    AuditEntry,
    InvalidAuditEntryError,
    Outcome,
    ReasonCode,
    SecretParameterError,
    UnauthenticatedFailureSummary,
)
from podiumd_admin.domain.environment import EnvironmentIdentity, Stage

ENVIRONMENT = EnvironmentIdentity(municipality="Onsdorp", stage=Stage.TEST)
OCCURRED_AT = datetime(2026, 11, 8, 9, 30, tzinfo=UTC)


def _entry(**overrides: Any) -> AuditEntry:
    fields: dict[str, Any] = {
        "occurred_at": OCCURRED_AT,
        "environment": ENVIRONMENT,
        "action": "sign-out",
        "outcome": Outcome.ALLOWED,
        "correlation_id": "6f1c0a52-3b7e-4d55-9a0f-2f7a4d1c9b11",
        "client_ip": "192.0.2.10",
        "user_subject": "f3b2c1d0-0000-4000-8000-000000000001",
        "username": "j.jansen",
    }
    fields.update(overrides)
    return AuditEntry(**fields)


# --- Outcome --------------------------------------------------------------------


def test_outcomes_are_exactly_the_five_spec_values() -> None:
    assert {outcome.value for outcome in Outcome} == {
        "allowed",
        "denied",
        "succeeded",
        "failed",
        "info",
    }


# --- ReasonCode -----------------------------------------------------------------


def test_reason_codes_cover_authorisation_denials() -> None:
    assert ReasonCode.NO_ROLE.value == "no-role"
    assert ReasonCode.MISSING_PERMISSION.value == "missing-permission"
    assert ReasonCode.CSRF.value == "csrf"
    assert {ReasonCode.NO_ROLE, ReasonCode.MISSING_PERMISSION, ReasonCode.CSRF} == DENIAL_REASONS


def test_reason_codes_cover_session_expiry() -> None:
    assert {reason.value for reason in SESSION_EXPIRY_REASONS} == {
        "idle",
        "max-lifetime",
        "refresh-refused",
        "backchannel-logout",
    }


def test_reason_codes_cover_unauthenticated_failures() -> None:
    assert {reason.value for reason in UNAUTHENTICATED_REASONS} == {
        "invalid-state",
        "callback-error",
        "token-exchange-failed",
        "no-session",
        "invalid-logout-token",
    }


def test_every_reason_code_belongs_to_exactly_one_group() -> None:
    groups = [DENIAL_REASONS, SESSION_EXPIRY_REASONS, UNAUTHENTICATED_REASONS]

    assert set().union(*groups) == set(ReasonCode)
    assert sum(len(group) for group in groups) == len(ReasonCode)


@pytest.mark.parametrize("reason", list(ReasonCode), ids=str)
def test_reason_codes_are_kebab_case(reason: ReasonCode) -> None:
    assert reason.value == reason.value.lower()
    assert all(part.isalpha() for part in reason.value.split("-"))


def test_reason_codes_accept_only_known_values() -> None:
    # Free text, such as a Keycloak error_description, can never become a reason.
    with pytest.raises(ValueError, match="not a valid ReasonCode"):
        ReasonCode("The user account is disabled")


# --- AuditEntry: fields ---------------------------------------------------------


def test_entry_holds_every_recorded_field() -> None:
    entry_id = uuid.UUID("0b9f7c64-1b52-4a8e-8f1e-5b8a4f0f2c3d")

    entry = _entry(
        id=entry_id,
        action="api:/api/v1/audit-entries",
        target="GET /api/v1/audit-entries",
        parameters={"permission": "audit-log:read"},
        outcome=Outcome.DENIED,
        reason=ReasonCode.MISSING_PERMISSION,
    )

    assert entry.id == entry_id
    assert entry.occurred_at == OCCURRED_AT
    assert entry.environment == ENVIRONMENT
    assert entry.user_subject == "f3b2c1d0-0000-4000-8000-000000000001"
    assert entry.username == "j.jansen"
    assert entry.action == "api:/api/v1/audit-entries"
    assert entry.target == "GET /api/v1/audit-entries"
    assert dict(entry.parameters) == {"permission": "audit-log:read"}
    assert entry.outcome is Outcome.DENIED
    assert entry.reason is ReasonCode.MISSING_PERMISSION
    assert entry.correlation_id == "6f1c0a52-3b7e-4d55-9a0f-2f7a4d1c9b11"
    assert entry.client_ip == "192.0.2.10"


def test_entry_gets_a_unique_id_by_default() -> None:
    first, second = _entry(), _entry()

    assert isinstance(first.id, uuid.UUID)
    assert first.id != second.id


def test_optional_fields_default_to_absent() -> None:
    entry = AuditEntry(
        occurred_at=OCCURRED_AT,
        environment=ENVIRONMENT,
        action="session-expired",
        outcome=Outcome.INFO,
        reason=ReasonCode.IDLE,
        correlation_id="sweep-1",
    )

    assert entry.user_subject is None
    assert entry.username is None
    assert entry.target is None
    assert dict(entry.parameters) == {}
    assert entry.client_ip is None


def test_entry_is_immutable() -> None:
    entry = _entry()

    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.outcome = Outcome.DENIED  # type: ignore[misc]


def test_parameters_cannot_be_changed_after_construction() -> None:
    parameters = {"page": 1}
    entry = _entry(parameters=parameters)

    parameters["page"] = 2
    with pytest.raises(TypeError):
        entry.parameters["page"] = 3  # type: ignore[index]

    assert entry.parameters["page"] == 1


# --- AuditEntry: required fields ------------------------------------------------


@pytest.mark.parametrize("field", ["action", "correlation_id"])
@pytest.mark.parametrize("value", ["", "   ", None])
def test_required_text_fields_must_be_given(field: str, value: str | None) -> None:
    with pytest.raises(InvalidAuditEntryError, match=field):
        _entry(**{field: value})


def test_environment_must_be_an_environment_identity() -> None:
    with pytest.raises(InvalidAuditEntryError, match="environment"):
        _entry(environment="onsdorp-test")


def test_outcome_must_be_an_outcome() -> None:
    with pytest.raises(InvalidAuditEntryError, match="outcome"):
        _entry(outcome="allowed")


def test_reason_must_be_a_reason_code() -> None:
    with pytest.raises(InvalidAuditEntryError, match="reason"):
        _entry(outcome=Outcome.DENIED, reason="missing-permission")


def test_id_must_be_a_uuid() -> None:
    with pytest.raises(InvalidAuditEntryError, match="id"):
        _entry(id="0b9f7c64-1b52-4a8e-8f1e-5b8a4f0f2c3d")


# --- AuditEntry: timestamp ------------------------------------------------------


def test_timestamp_must_carry_a_timezone() -> None:
    with pytest.raises(InvalidAuditEntryError, match="occurred_at"):
        _entry(occurred_at=datetime(2026, 11, 8, 9, 30))  # noqa: DTZ001 - the naive value under test


def test_timestamp_must_be_a_datetime() -> None:
    with pytest.raises(InvalidAuditEntryError, match="occurred_at"):
        _entry(occurred_at="2026-11-08T09:30:00Z")


def test_timestamp_is_stored_in_utc() -> None:
    amsterdam_winter = timezone(timedelta(hours=1))

    entry = _entry(occurred_at=datetime(2026, 11, 8, 10, 30, tzinfo=amsterdam_winter))

    assert entry.occurred_at == OCCURRED_AT
    assert entry.occurred_at.utcoffset() == timedelta(0)


# --- AuditEntry: outcome and reason ---------------------------------------------


@pytest.mark.parametrize("outcome", [Outcome.DENIED, Outcome.INFO], ids=str)
def test_denials_and_system_events_require_a_reason(outcome: Outcome) -> None:
    with pytest.raises(InvalidAuditEntryError, match="reason"):
        _entry(outcome=outcome, reason=None)


@pytest.mark.parametrize("outcome", [Outcome.ALLOWED, Outcome.SUCCEEDED], ids=str)
def test_allowed_and_succeeded_entries_carry_no_reason(outcome: Outcome) -> None:
    with pytest.raises(InvalidAuditEntryError, match="reason"):
        _entry(outcome=outcome, reason=ReasonCode.MISSING_PERMISSION)


@pytest.mark.parametrize("reason", [None, ReasonCode.REFRESH_REFUSED], ids=str)
def test_failed_entries_may_carry_a_reason(reason: ReasonCode | None) -> None:
    assert _entry(outcome=Outcome.FAILED, reason=reason).reason is reason


def test_unauthenticated_failure_reasons_are_never_stored_as_entries() -> None:
    # Unauthenticated failures go to stdout only (spec: "Recording
    # unauthenticated failures"), so an Audit Entry cannot carry their reasons.
    with pytest.raises(InvalidAuditEntryError, match="unauthenticated"):
        _entry(outcome=Outcome.DENIED, reason=ReasonCode.INVALID_STATE)


# --- AuditEntry: text-length caps -----------------------------------------------


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("action", MAX_ACTION_LENGTH),
        ("target", MAX_TARGET_LENGTH),
        ("user_subject", MAX_USER_SUBJECT_LENGTH),
        ("username", MAX_USERNAME_LENGTH),
        ("correlation_id", MAX_CORRELATION_ID_LENGTH),
    ],
)
def test_text_fields_are_truncated_to_their_limit(field: str, limit: int) -> None:
    entry = _entry(**{field: "x" * (limit + 50)})

    value = getattr(entry, field)
    assert len(value) == limit
    assert value.endswith("…")
    assert value.startswith("x" * (limit - 1))


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("action", MAX_ACTION_LENGTH),
        ("target", MAX_TARGET_LENGTH),
        ("user_subject", MAX_USER_SUBJECT_LENGTH),
        ("username", MAX_USERNAME_LENGTH),
        ("correlation_id", MAX_CORRELATION_ID_LENGTH),
    ],
)
def test_text_fields_at_their_limit_are_kept_whole(field: str, limit: int) -> None:
    assert getattr(_entry(**{field: "x" * limit}), field) == "x" * limit


def test_parameter_text_values_are_truncated() -> None:
    entry = _entry(parameters={"filter": "y" * (MAX_PARAMETER_VALUE_LENGTH + 1)})

    value = entry.parameters["filter"]
    assert isinstance(value, str)
    assert len(value) == MAX_PARAMETER_VALUE_LENGTH
    assert value.endswith("…")


def test_parameter_keys_are_truncated() -> None:
    long_key = "k" * (MAX_PARAMETER_KEY_LENGTH + 10)

    entry = _entry(parameters={long_key: 1})

    (key,) = entry.parameters
    assert len(key) == MAX_PARAMETER_KEY_LENGTH


def test_parameter_keys_that_collide_after_truncation_are_rejected() -> None:
    prefix = "k" * MAX_PARAMETER_KEY_LENGTH

    with pytest.raises(InvalidAuditEntryError, match="parameter"):
        _entry(parameters={prefix + "a": 1, prefix + "b": 2})


def test_number_of_parameters_is_capped() -> None:
    too_many = {f"p{index}": index for index in range(MAX_PARAMETERS + 1)}

    with pytest.raises(InvalidAuditEntryError, match="parameters"):
        _entry(parameters=too_many)


def test_blank_optional_text_counts_as_absent() -> None:
    entry = _entry(target="  ", username="", user_subject=" ")

    assert entry.target is None
    assert entry.username is None
    assert entry.user_subject is None


def test_surrounding_whitespace_is_trimmed() -> None:
    assert _entry(action="  sign-out \n").action == "sign-out"


@pytest.mark.parametrize("field", ["target", "user_subject", "username"])
def test_optional_text_fields_must_be_text(field: str) -> None:
    with pytest.raises(InvalidAuditEntryError, match=field):
        _entry(**{field: 42})


# --- AuditEntry: parameters -----------------------------------------------------


def test_parameters_hold_plain_values() -> None:
    parameters = {"page": 2, "dry_run": True, "action": "sign-out", "until": None}

    assert dict(_entry(parameters=parameters).parameters) == parameters


@pytest.mark.parametrize("value", [1.5, b"bytes", ["a"], {"nested": "value"}, object()])
def test_parameters_reject_values_that_are_not_plain(value: object) -> None:
    with pytest.raises(InvalidAuditEntryError, match="parameter"):
        _entry(parameters={"value": value})


@pytest.mark.parametrize("key", [1, "", "  "])
def test_parameters_reject_keys_that_are_not_names(key: object) -> None:
    with pytest.raises(InvalidAuditEntryError, match="parameter"):
        _entry(parameters={key: "x"})


def test_parameters_must_be_a_mapping() -> None:
    with pytest.raises(InvalidAuditEntryError, match="parameters"):
        _entry(parameters=[("page", 1)])


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "Password",
        "new_password",
        "passwd",
        "pwd",
        "passphrase",
        "secret",
        "client_secret",
        "clientSecret",
        "token",
        "access_token",
        "refreshToken",
        "id-token",
        "key",
        "api_key",
        "apiKey",
        "private_key",
        "encryption-key",
        "credential",
        "credentials",
        "authorization",
        "auth",
        "cookie",
        "session_id",
        "sessionId",
    ],
)
def test_secret_like_parameters_are_rejected(key: str) -> None:
    with pytest.raises(SecretParameterError, match=key):
        _entry(parameters={key: "hunter2"})


def test_secret_parameter_error_is_an_invalid_entry() -> None:
    assert issubclass(SecretParameterError, InvalidAuditEntryError)


def test_secret_parameter_error_does_not_reveal_the_value() -> None:
    with pytest.raises(SecretParameterError) as raised:
        _entry(parameters={"password": "hunter2"})

    assert "hunter2" not in str(raised.value)


@pytest.mark.parametrize(
    "key",
    ["permission", "component", "monkey", "keyboard_layout", "page", "author", "tokenizer_name"],
)
def test_ordinary_parameter_names_are_allowed(key: str) -> None:
    assert key in _entry(parameters={key: "x"}).parameters


def test_parameter_names_that_look_secret_after_truncation_are_rejected() -> None:
    # Truncation cuts this harmless name down to ``xxx…_token…``, which looks
    # like a secret name and would be rejected when the stored entry is read.
    key = "x" * 57 + "_tokenizer_name"

    with pytest.raises(SecretParameterError):
        _entry(parameters={key: "x"})


@pytest.mark.parametrize(
    "key",
    [
        "page",
        "k" * (MAX_PARAMETER_KEY_LENGTH + 10),
        "x" * 57 + "_tokenizer_name",
        "x" * 50 + "_secretariat_code",
        "x" * 55 + "_keyboard_layout",
        "component_" + "y" * MAX_PARAMETER_KEY_LENGTH,
    ],
)
def test_rebuilding_an_entry_from_its_parameters_keeps_them(key: str) -> None:
    """An accepted entry's parameters are accepted again unchanged, as on read."""
    try:
        entry = _entry(parameters={key: "y" * (MAX_PARAMETER_VALUE_LENGTH + 1)})
    except SecretParameterError:
        return

    rebuilt = _entry(parameters=dict(entry.parameters))

    assert rebuilt.parameters == entry.parameters


# --- AuditEntry: client IP ------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("192.0.2.10", "192.0.2.10"),
        (" 192.0.2.10 ", "192.0.2.10"),
        ("2001:DB8:0:0:0:0:0:1", "2001:db8::1"),
    ],
)
def test_client_ip_is_stored_normalised(given: str, stored: str) -> None:
    assert _entry(client_ip=given).client_ip == stored


@pytest.mark.parametrize(
    "value", ["testclient", "192.0.2.10, 10.0.0.1", "", 3232235530, "fe80::1%eth0"]
)
def test_client_ip_must_be_an_ip_address(value: object) -> None:
    with pytest.raises(InvalidAuditEntryError, match="client_ip"):
        _entry(client_ip=value)


# --- UnauthenticatedFailureSummary ----------------------------------------------


def test_summary_holds_the_combined_failures() -> None:
    summary = UnauthenticatedFailureSummary(
        client_ip="192.0.2.10",
        reason=ReasonCode.INVALID_STATE,
        count=500,
        first_at=OCCURRED_AT,
        last_at=OCCURRED_AT + timedelta(seconds=59),
    )

    assert summary.count == 500
    assert summary.reason is ReasonCode.INVALID_STATE


def test_summary_accepts_only_unauthenticated_reasons() -> None:
    with pytest.raises(ValueError, match="unauthenticated"):
        UnauthenticatedFailureSummary(
            client_ip="192.0.2.10",
            reason=ReasonCode.MISSING_PERMISSION,
            count=1,
            first_at=OCCURRED_AT,
            last_at=OCCURRED_AT,
        )


def test_summary_counts_at_least_one_failure() -> None:
    with pytest.raises(ValueError, match="count"):
        UnauthenticatedFailureSummary(
            client_ip="192.0.2.10",
            reason=ReasonCode.NO_SESSION,
            count=0,
            first_at=OCCURRED_AT,
            last_at=OCCURRED_AT,
        )


def test_summary_ends_no_earlier_than_it_starts() -> None:
    with pytest.raises(ValueError, match="last_at"):
        UnauthenticatedFailureSummary(
            client_ip="192.0.2.10",
            reason=ReasonCode.NO_SESSION,
            count=2,
            first_at=OCCURRED_AT,
            last_at=OCCURRED_AT - timedelta(seconds=1),
        )


def test_overflow_summary_has_no_client_ip() -> None:
    summary = UnauthenticatedFailureSummary(
        client_ip=None,
        reason=ReasonCode.NO_SESSION,
        count=3,
        first_at=OCCURRED_AT,
        last_at=OCCURRED_AT,
    )

    assert summary.client_ip is None
