"""Security headers on every response (task 6.3).

Spec: installation, "Hardened runtime and responses": every response carries a
Content-Security-Policy, ``nosniff`` and ``Referrer-Policy: no-referrer``; API
responses also carry ``Cache-Control: no-store``; interactive API docs are not
served, so ``/docs`` and ``/openapi.json`` return 404.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx2 import Headers

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
