"""Which address is the client's (task 6.4).

Spec: installation, "Trusted proxies". Design D2, "Proxy trust":
``X-Forwarded-For`` is honoured only from the ``trustedProxies`` CIDRs
(default: none). The client IP is the right-most address that is not a
trusted proxy. A malformed header falls back to the connecting peer, and an
unusable peer address gives no client IP: resolving never fails.
"""

from __future__ import annotations

import ipaddress

import pytest

from podiumd_admin.domain.client_ip import resolve_client_ip

PROXIES = (ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("2001:db8::/32"))


def test_without_trusted_proxies_a_spoofed_header_is_ignored() -> None:
    assert resolve_client_ip("192.0.2.10", ["1.2.3.4"], trusted_proxies=()) == "192.0.2.10"


def test_without_a_header_the_peer_is_the_client() -> None:
    assert resolve_client_ip("192.0.2.10", [], trusted_proxies=PROXIES) == "192.0.2.10"


def test_a_header_from_an_untrusted_peer_is_ignored() -> None:
    assert resolve_client_ip("192.0.2.10", ["1.2.3.4"], trusted_proxies=PROXIES) == "192.0.2.10"


def test_a_trusted_proxy_gives_the_address_it_forwarded_for() -> None:
    assert resolve_client_ip("10.1.2.3", ["198.51.100.7"], trusted_proxies=PROXIES) == (
        "198.51.100.7"
    )


def test_the_right_most_untrusted_address_is_the_client() -> None:
    """Addresses left of the first untrusted hop could be chosen by the client."""
    header = ["1.2.3.4, 198.51.100.7, 10.9.9.9"]

    assert resolve_client_ip("10.1.2.3", header, trusted_proxies=PROXIES) == "198.51.100.7"


def test_several_headers_are_read_as_one_list_in_order() -> None:
    headers = ["1.2.3.4", "198.51.100.7, 10.9.9.9"]

    assert resolve_client_ip("10.1.2.3", headers, trusted_proxies=PROXIES) == "198.51.100.7"


def test_when_every_hop_is_trusted_the_left_most_is_the_client() -> None:
    assert resolve_client_ip("10.1.2.3", ["10.0.0.5, 10.0.0.6"], trusted_proxies=PROXIES) == (
        "10.0.0.5"
    )


def test_addresses_are_normalised() -> None:
    assert (
        resolve_client_ip(
            "2001:db8:0:0::1", [" 2001:DB8:0:0:0:0:0:FFFF , 2001:db8::2"], trusted_proxies=PROXIES
        )
        == "2001:db8::ffff"
    )


def test_an_ipv4_mapped_peer_is_matched_as_ipv4() -> None:
    assert resolve_client_ip("::ffff:10.1.2.3", ["198.51.100.7"], trusted_proxies=PROXIES) == (
        "198.51.100.7"
    )
    assert resolve_client_ip("::ffff:192.0.2.10", [], trusted_proxies=()) == "192.0.2.10"


@pytest.mark.parametrize(
    "header",
    [
        "not-an-address",
        "198.51.100.7, ",
        "198.51.100.7,,10.0.0.5",
        "198.51.100.7:4711",
        "[2001:db8::7]:443",
        # A zone id is not storable in PostgreSQL INET.
        "2001:db9::7%eth0",
        "fe80::1%eth0",
        "unknown",
        "<script>",
        "",
    ],
)
def test_a_malformed_header_falls_back_to_the_peer(header: str) -> None:
    assert resolve_client_ip("10.1.2.3", [header], trusted_proxies=PROXIES) == "10.1.2.3"


@pytest.mark.parametrize(
    "peer", [None, "", "testclient", "unix:/run/app.sock", "fe80::1%eth0", "2001:db8::1%2"]
)
def test_an_unusable_peer_gives_no_client_ip(peer: str | None) -> None:
    assert resolve_client_ip(peer, ["198.51.100.7"], trusted_proxies=PROXIES) is None
