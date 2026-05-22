"""Tests for authmail_relay.async_client.AsyncEmailServiceClient."""
import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from authmail_relay.async_client import AsyncEmailServiceClient
from authmail_relay.client import EmailServiceError


def _async_handler(responses):
    requests: list[httpx.Request] = []

    def h(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        key = (request.method, request.url.path)
        if key not in responses:
            return httpx.Response(404, json={"detail": "not found"})
        status, body = responses[key]
        return httpx.Response(status, json=body)

    return h, requests


def _run(coro):
    return asyncio.run(coro)


class TestAsyncClient:
    def test_health(self):
        h, reqs = _async_handler({("GET", "/health"): (200, {"status": "ok"})})

        async def go():
            async with AsyncEmailServiceClient(
                "http://authmail-relay:8000", "key",
                transport=httpx.MockTransport(h),
            ) as c:
                return await c.health()

        assert _run(go()) == {"status": "ok"}
        assert reqs[0].headers["Authorization"] == "Bearer key"

    def test_send_magic_link(self):
        h, reqs = _async_handler({
            ("POST", "/send/magic-link"): (
                200, {"sent": True, "message_id": "<m@h>"},
            ),
        })

        async def go():
            async with AsyncEmailServiceClient(
                "http://authmail-relay:8000", "key",
                transport=httpx.MockTransport(h),
            ) as c:
                return await c.send_magic_link(
                    "u@x.com", "Alice", "tok", dry_run=False,
                )

        out = _run(go())
        assert out == {"sent": True, "message_id": "<m@h>"}

    def test_dry_run_sets_header(self):
        h, reqs = _async_handler({
            ("POST", "/send/otp"): (200, {"sent": False, "dry_run": True}),
        })

        async def go():
            async with AsyncEmailServiceClient(
                "http://authmail-relay:8000", "key",
                transport=httpx.MockTransport(h),
            ) as c:
                return await c.send_otp("u@x.com", "Bob", "999", dry_run=True)

        _run(go())
        assert reqs[0].headers.get("X-Dry-Run") == "true"

    def test_502_raises_authmail_relay_error(self):
        h, _ = _async_handler({
            ("POST", "/send"): (
                502,
                {"detail": {"error_code": "smtp_timeout", "message": "boom"}},
            ),
        })

        async def go():
            async with AsyncEmailServiceClient(
                "http://authmail-relay:8000", "key",
                transport=httpx.MockTransport(h),
            ) as c:
                await c.send("u@x.com", "Sub", "<p>x</p>")

        with pytest.raises(EmailServiceError) as exc_info:
            _run(go())
        assert exc_info.value.error_code == "smtp_timeout"
        assert exc_info.value.status_code == 502
