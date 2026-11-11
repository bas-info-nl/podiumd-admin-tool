"""Liveness and readiness (task 6.5).

Spec: installation, "Health endpoints": two unauthenticated endpoints that
reveal no configuration. Liveness reports that the process runs; readiness
reports whether the database is reachable. Scenario "Database unreachable":
readiness reports not-ready while liveness stays healthy.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from podiumd_admin.adapters.http import create_app
from tests.adapters.http.conftest import SETTINGS, FakeReadiness


def test_liveness_is_healthy(client: TestClient, readiness: FakeReadiness) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert readiness.calls == 0  # liveness never depends on the database


def test_readiness_is_ready_when_the_database_is_reachable(client: TestClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_an_unreachable_database_is_not_ready_while_liveness_stays_healthy(
    client: TestClient, readiness: FakeReadiness
) -> None:
    readiness.ready = False

    ready = client.get("/readyz")

    assert ready.status_code == 503
    assert ready.json() == {"status": "not-ready"}
    assert client.get("/healthz").status_code == 200


def test_a_failing_readiness_check_reports_not_ready_without_details() -> None:
    async def broken() -> bool:
        raise OSError("connection to db:5432 refused for podiumd_admin_app")

    with TestClient(create_app(SETTINGS, readiness=broken)) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not-ready"}


def test_health_responses_reveal_no_configuration(
    client: TestClient, readiness: FakeReadiness
) -> None:
    readiness.ready = False
    bodies = client.get("/healthz").text + client.get("/readyz").text

    for value in (
        "Utrecht",
        "accp",
        SETTINGS.public_hostname,
        SETTINGS.oidc_issuer,
        SETTINGS.oidc_client_id,
        "podiumd_admin",
        "db",
        "10.0.0.0",
    ):
        assert value not in bodies
