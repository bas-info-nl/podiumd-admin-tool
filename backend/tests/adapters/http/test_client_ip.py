"""The client IP of an HTTP request (task 6.4).

Spec: installation, "Trusted proxies", scenario "Spoofed forwarded header": with
no proxies configured, a request carrying ``X-Forwarded-For: 1.2.3.4`` is
recorded with the connecting peer's address.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterator
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from podiumd_admin.adapters.http import create_app
from podiumd_admin.adapters.http.client_ip import client_ip
from tests.adapters.http.conftest import FakeReadiness, settings


def _client(*proxies: str, peer: str) -> Iterator[TestClient]:
    app = create_app(
        settings(trusted_proxies=tuple(ipaddress.ip_network(proxy) for proxy in proxies)),
        readiness=FakeReadiness(),
    )
    router = APIRouter()

    @router.get("/api/v1/test-client-ip")
    async def show(ip: Annotated[str | None, Depends(client_ip)]) -> dict[str, str | None]:
        return {"client_ip": ip}

    app.include_router(router)
    with TestClient(app, client=(peer, 50000)) as test_client:
        yield test_client


@pytest.fixture
def untrusting() -> Iterator[TestClient]:
    yield from _client(peer="192.0.2.10")


@pytest.fixture
def behind_proxy() -> Iterator[TestClient]:
    yield from _client("10.0.0.0/8", peer="10.1.2.3")


def _ip(client: TestClient, forwarded_for: str | None = None) -> object:
    headers = {} if forwarded_for is None else {"X-Forwarded-For": forwarded_for}
    return client.get("/api/v1/test-client-ip", headers=headers).json()["client_ip"]


def test_a_spoofed_header_is_ignored_by_default(untrusting: TestClient) -> None:
    assert _ip(untrusting, "1.2.3.4") == "192.0.2.10"


def test_the_header_of_a_trusted_proxy_is_honoured(behind_proxy: TestClient) -> None:
    assert _ip(behind_proxy, "1.2.3.4, 198.51.100.7") == "198.51.100.7"


def test_a_malformed_header_falls_back_to_the_peer(behind_proxy: TestClient) -> None:
    assert _ip(behind_proxy, "not-an-address") == "10.1.2.3"


def test_an_unusable_peer_address_gives_no_client_ip() -> None:
    """Starlette's test client reports the peer ``testclient``; no 500 follows."""
    for test_client in _client("10.0.0.0/8", peer="testclient"):
        assert _ip(test_client, "198.51.100.7") is None
