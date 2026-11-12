"""Security headers on every response (task 6.3).

Spec: installation, "Hardened runtime and responses": every response carries a
Content-Security-Policy, ``nosniff`` and ``Referrer-Policy: no-referrer``; API
responses also carry ``Cache-Control: no-store``; interactive API docs are not
served, so ``/docs`` and ``/openapi.json`` return 404.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from httpx2 import Headers

from podiumd_admin.adapters.http import create_app
from tests.adapters.http.conftest import SETTINGS, FakeReadiness

CSP = "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'"


def _assert_hardened(headers: Headers) -> None:
    assert headers.get("content-security-policy") == CSP
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("referrer-policy") == "no-referrer"


@pytest.mark.parametrize(
    "path",
    ["/api/v1/environment", "/healthz", "/readyz", "/", "/docs", "/redoc", "/openapi.json"],
)
def test_every_response_carries_the_security_headers(client: TestClient, path: str) -> None:
    _assert_hardened(client.get(path).headers)


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"])
def test_no_interactive_docs_or_spec_are_served(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/api/v1/environment", "/api/v1/does-not-exist"])
def test_api_responses_are_not_stored(client: TestClient, path: str) -> None:
    assert client.get(path).headers["cache-control"] == "no-store"


def test_an_error_response_carries_the_security_headers(client: TestClient) -> None:
    response = client.post("/api/v1/environment")

    assert response.status_code == 405
    _assert_hardened(response.headers)
    assert response.headers["cache-control"] == "no-store"


def test_a_header_is_not_duplicated(client: TestClient) -> None:
    response = client.get("/api/v1/environment")

    assert response.headers.get_list("content-security-policy") == [CSP]
    assert response.headers.get_list("cache-control") == ["no-store"]


def test_an_unhandled_error_carries_the_security_headers_and_no_detail() -> None:
    """Starlette answers an unhandled error outside the user middleware; ours must still apply."""
    app = create_app(SETTINGS, readiness=FakeReadiness())
    router = APIRouter()

    @router.get("/api/v1/test-crash")
    async def crash() -> None:
        raise RuntimeError("secret detail from db:5432")

    app.include_router(router)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/api/v1/test-crash")

    assert response.status_code == 500
    _assert_hardened(response.headers)
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"error": "internal-error"}
    assert "secret detail" not in response.text
