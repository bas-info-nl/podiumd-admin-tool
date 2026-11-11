"""Which address a request came from, behind zero or more trusted proxies.

Spec: installation, "Trusted proxies". Design D2, "Proxy trust": forwarded
headers are honoured only from the configured ``trustedProxies`` ranges
(default: none), and the client IP is the right-most address that is not a
trusted proxy. Addresses further left could have been written by the client
itself, so they are never used.

Resolving never fails: a malformed ``X-Forwarded-For`` falls back to the
connecting peer, and a peer that is not an IP address (a Unix socket, or a test
client) gives no client IP. A request must never turn into an error because of
a header a client can choose.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Sequence

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
type IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def _parse(value: str) -> IPAddress | None:
    """The address in ``value``, IPv4-mapped IPv6 as IPv4; ``None`` if it is none."""
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _is_trusted(address: IPAddress, trusted_proxies: Iterable[IPNetwork]) -> bool:
    return any(address in network for network in trusted_proxies)


def resolve_client_ip(
    peer: str | None,
    forwarded_for: Sequence[str],
    *,
    trusted_proxies: Sequence[IPNetwork],
) -> str | None:
    """The client IP in normalised text form, or ``None`` if there is none.

    ``peer`` is the address of the connecting peer; ``forwarded_for`` holds the
    values of every ``X-Forwarded-For`` header, in the order received.
    """
    peer_address = _parse(peer) if peer else None
    if peer_address is None:
        return None
    if not forwarded_for or not _is_trusted(peer_address, trusted_proxies):
        return peer_address.compressed

    hops: list[IPAddress] = []
    for item in ",".join(forwarded_for).split(","):
        address = _parse(item)
        if address is None:
            # One malformed hop makes the whole chain untrustworthy.
            return peer_address.compressed
        hops.append(address)

    for address in reversed(hops):
        if not _is_trusted(address, trusted_proxies):
            return address.compressed
    # Every hop is a trusted proxy: the left-most is the nearest to the client.
    return hops[0].compressed
