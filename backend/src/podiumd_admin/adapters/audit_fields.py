"""The flat field set of an Audit Entry, shared by the database and the stdout copy.

Spec: audit-log, "Structured copy on stdout": the stdout line holds the same
fields as the stored Audit Entry. Both adapters build their output from
``audit_entry_fields``, so the two cannot drift apart.
"""

from __future__ import annotations

from typing import Any

from podiumd_admin.domain.audit import AuditEntry


def audit_entry_fields(entry: AuditEntry) -> dict[str, Any]:
    """Every field of ``entry``, flattened, with enums as their values.

    The id stays a ``UUID`` and the timestamp a ``datetime``; each adapter
    converts them the way its medium needs.
    """
    return {
        "id": entry.id,
        "occurred_at": entry.occurred_at,
        "environment_municipality": entry.environment.municipality,
        "environment_stage": entry.environment.stage.value,
        "environment_label": entry.environment.label,
        "action": entry.action,
        "target": entry.target,
        "outcome": entry.outcome.value,
        "reason": entry.reason.value if entry.reason is not None else None,
        "user_subject": entry.user_subject,
        "username": entry.username,
        "parameters": dict(entry.parameters),
        "correlation_id": entry.correlation_id,
        "client_ip": entry.client_ip,
    }
