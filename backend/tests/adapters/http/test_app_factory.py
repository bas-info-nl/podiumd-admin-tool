"""The FastAPI app factory and the build-time OpenAPI export (task 6.2).

Design D2, "Response hardening": FastAPI's docs, redoc and OpenAPI URLs are
disabled at runtime; the OpenAPI spec is exported at build time by a script,
for the generated frontend client (D6). Design D7: the API lives under
``/api/v1``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from podiumd_admin.adapters.db.unit_of_work import TransactionAbortedError
from podiumd_admin.adapters.http import create_app
from podiumd_admin.adapters.http.app import API_PREFIX
from podiumd_admin.adapters.http.openapi import main, openapi_document
from podiumd_admin.application.audit import AuditWriteFailedError
from podiumd_admin.domain.audit import AuditEntry, Outcome
from tests.adapters.http.conftest import SETTINGS, FakeReadiness


def test_the_runtime_app_serves_no_interactive_docs_or_spec() -> None:
    app = create_app(SETTINGS, readiness=FakeReadiness())

    assert isinstance(app, FastAPI)
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


def test_every_api_route_lives_under_api_v1() -> None:
    # FastAPI 0.16x keeps included routers as lazy entries in ``app.routes``,
    # so the documented paths are the public view of the API routes.
    api_paths = list(openapi_document()["paths"])

    assert API_PREFIX == "/api/v1"
    assert api_paths
    assert all(path.startswith("/api/v1/") for path in api_paths)


def test_the_exported_document_describes_the_api() -> None:
    document = openapi_document()

    assert document["openapi"].startswith("3.")
    assert document["info"]["title"] == "PodiumD Admin Tool"
    assert "/api/v1/environment" in document["paths"]
    # Health endpoints are for the platform, not for the generated client.
    assert "/healthz" not in document["paths"]
    assert "/readyz" not in document["paths"]


def test_the_export_script_writes_the_document_to_a_file(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"

    main([str(target)])

    assert json.loads(target.read_text(encoding="utf-8")) == openapi_document()
    assert target.read_text(encoding="utf-8").endswith("\n")


def test_the_export_script_writes_to_stdout_without_a_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main([])

    assert json.loads(capsys.readouterr().out) == openapi_document()


def _entry() -> AuditEntry:
    return AuditEntry(
        occurred_at=datetime(2026, 11, 11, 9, 0, tzinfo=UTC),
        environment=SETTINGS.environment,
        action="sign-out",
        outcome=Outcome.ALLOWED,
        correlation_id="c-1",
    )


@pytest.mark.parametrize(
    "error",
    [
        AuditWriteFailedError(_entry()),
        TransactionAbortedError("a failed statement aborted the transaction"),
    ],
    ids=["insert-failed", "transaction-aborted"],
)
def test_an_unrecorded_action_tells_the_user_it_could_not_be_recorded(
    error: Exception,
) -> None:
    """Spec audit-log, "No action without an Audit Entry"; issue #30."""
    app = create_app(SETTINGS, readiness=FakeReadiness())
    router = APIRouter()

    @router.post("/api/v1/test-action")
    async def act() -> None:
        raise error

    app.include_router(router)

    with TestClient(app) as client:
        response = client.post("/api/v1/test-action")

    assert response.status_code == 500
    assert response.json() == {"error": "action-not-recorded"}
    assert "transaction" not in response.text
    assert "sign-out" not in response.text
