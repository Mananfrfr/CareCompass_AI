"""URL safety checks used before any outbound fetch (SSRF protection)."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443}
EVIDENCE_SCHEMES = {"http", "https", "fixture"}

Resolver = Callable[[str], Awaitable[list[str]]]


class UnsafeURLError(ValueError):
    pass


async def system_resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


def _is_public_ip(raw: str) -> bool:
    ip = ipaddress.ip_address(raw.split("%")[0])
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified or (ip.version == 6 and ip.ipv4_mapped and not _is_public_ip(str(ip.ipv4_mapped)))
    )


def check_url_syntax(url: str, max_length: int = 2048) -> str:
    """Validate scheme, credentials, port and host. Returns the lowercase host."""
    if not url or len(url) > max_length:
        raise UnsafeURLError("URL missing or too long")
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"Scheme not allowed: {parts.scheme!r}")
    if parts.username or parts.password:
        raise UnsafeURLError("Credentials in URL are not allowed")
    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError("Invalid port") from exc
    if port not in ALLOWED_PORTS:
        raise UnsafeURLError(f"Port not allowed: {port}")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(".localhost") or host.endswith(".internal") or host.endswith(".local"):
        raise UnsafeURLError("Host not allowed")
    try:
        public = _is_public_ip(host.strip("[]"))
    except ValueError:
        public = True  # not an IP literal; DNS check happens in check_url_destination
    if not public:
        raise UnsafeURLError("Private or reserved IP address not allowed")
    return host


async def check_url_destination(url: str, resolver: Resolver = system_resolve,
                                allowed_hosts: set[str] | None = None) -> str:
    host = check_url_syntax(url)
    if allowed_hosts is not None and not any(host == h or host.endswith("." + h) for h in allowed_hosts):
        raise UnsafeURLError(f"Host {host} is not on the allow-list")
    try:
        addresses = await resolver(host)
    except OSError as exc:
        raise UnsafeURLError(f"DNS resolution failed for {host}") from exc
    if not addresses:
        raise UnsafeURLError(f"No addresses for {host}")
    for addr in addresses:
        if not _is_public_ip(addr):
            raise UnsafeURLError(f"{host} resolves to a non-public address")
    return host


def is_valid_evidence_url(url: str) -> bool:
    """Evidence URLs must be http(s) or fixture:// (synthetic datasets) - nothing else."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme == "fixture":
        return bool(parts.netloc or parts.path)
    if parts.scheme not in ALLOWED_SCHEMES or not parts.hostname:
        return False
    return True
