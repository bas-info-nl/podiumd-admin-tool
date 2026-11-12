"""The unauthenticated ``GET /api/v1/environment`` (task 6.6).

Design D5: the frontend reads the Environment identity from this endpoint, so
even the "no access" and error pages can show the Environment banner. It
returns the Municipality, the stage and the optional label, and nothing else.
The Dutch stage name is the frontend's to translate.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from podiumd_admin.adapters.http import create_app
from podiumd_admin.adapters.http.openapi import openapi_document
from podiumd_admin.domain.environment import EnvironmentIdentity, Stage
from tests.adapters.http.conftest import FakeReadiness, settings


def test_returns_the_environment_identity_without_a_session(client: TestClient) -> None:
    response = client.get("/api/v1/environment")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"municipality": "Onsdorp", "stage": "accp", "label": "Hosting BV"}


@pytest.mark.parametrize("stage", list(Stage))
def test_returns_every_stage_and_no_label_as_null(stage: Stage) -> None:
    app = create_app(
        settings(environment=EnvironmentIdentity("Den Haag", stage)), readiness=FakeReadiness()
    )

    with TestClient(app) as client:
        body = client.get("/api/v1/environment").json()

    assert body == {"municipality": "Den Haag", "stage": stage.value, "label": None}


def test_ignores_cookies_and_query_parameters(client: TestClient) -> None:
    client.cookies.set("__Host-podiumd_admin_session", "made-up")

    response = client.get("/api/v1/environment?stage=prod")

    assert response.json()["stage"] == "accp"


def test_the_contract_has_a_typed_response_with_the_stage_enum() -> None:
    document = openapi_document()
    operation = document["paths"]["/api/v1/environment"]["get"]
    schema_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    schema = document["components"]["schemas"][schema_ref.rsplit("/", 1)[1]]

    assert operation["operationId"] == "getEnvironment"
    assert set(schema["required"]) == {"municipality", "stage", "label"}
    assert schema["additionalProperties"] is False
    stage_schema = document["components"]["schemas"]["Stage"]
    assert stage_schema["enum"] == ["test", "accp", "prod"]
