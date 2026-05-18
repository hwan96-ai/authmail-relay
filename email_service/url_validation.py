"""SSRF defense for user-provided callback URLs (webhook_url).

P0-2 from gate-code-2026-05-16-001 / L-SEED-03 in .claude/learnings/index.md.

Validates that a URL is safe to fetch server-side:
- Scheme must be http or https.
- Hostname must not resolve to loopback, link-local, private, multicast,
  reserved, or unspecified addresses.

Test/internal callbacks may bypass via env:
- ``WEBHOOK_ALLOW_HOSTS`` (comma-separated hostname allowlist; matches case-
  insensitively against the URL's hostname). Hostnames in this list skip both
  IP-literal and DNS-resolution checks.
- ``WEBHOOK_ALLOW_LOOPBACK=1`` allows resolution to loopback/private IPs
  WITHOUT individually listing hostnames. Intended for local dev / tests only.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse


_INVALID_SCHEME_MSG = "webhook_url must use http or https"
_NO_HOST_MSG = "webhook_url is missing a hostname"
_DNS_FAIL_MSG = "webhook_url hostname could not be resolved"
_BLOCKED_IP_MSG = (
    "webhook_url resolves to a private, loopback, link-local, "
    "multicast, or reserved address"
)

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _truthy_env(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes"}


def _allow_hosts() -> set[str]:
    raw = os.environ.get("WEBHOOK_ALLOW_HOSTS", "") or ""
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True for any address that should never be reached from a
    server-side webhook fetcher."""
    return bool(
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_webhook_url(
    url: str,
    *,
    resolver=None,
) -> str:
    """Reject SSRF candidates. Returns the URL when safe, raises ``ValueError``
    otherwise.

    ``resolver`` (optional) overrides ``socket.getaddrinfo`` for testing.
    """
    if not isinstance(url, str) or not url:
        raise ValueError(_NO_HOST_MSG)

    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError(_INVALID_SCHEME_MSG)
    host = parsed.hostname
    if not host:
        raise ValueError(_NO_HOST_MSG)

    host_lc = host.lower()
    if host_lc in _allow_hosts():
        return url

    allow_loopback = _truthy_env("WEBHOOK_ALLOW_LOOPBACK")

    # 1. IP literal? Validate directly without DNS.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None

    if ip is not None:
        if _is_blocked_ip(ip) and not allow_loopback:
            raise ValueError(_BLOCKED_IP_MSG)
        return url

    # 2. Hostname — resolve and validate every returned address.
    resolve = resolver or socket.getaddrinfo
    try:
        infos = resolve(host, None)
    except (socket.gaierror, OSError) as exc:
        raise ValueError(f"{_DNS_FAIL_MSG}: {host}") from exc

    if not infos:
        raise ValueError(f"{_DNS_FAIL_MSG}: {host}")

    for info in infos:
        try:
            sockaddr = info[4]
            resolved = ipaddress.ip_address(sockaddr[0])
        except (IndexError, ValueError):
            continue
        if _is_blocked_ip(resolved) and not allow_loopback:
            raise ValueError(_BLOCKED_IP_MSG)
    return url
