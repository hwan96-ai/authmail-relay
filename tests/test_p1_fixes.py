"""Regression tests for the P1 fixes from gate-code-verify-2026-05-18-002.

Block layout matches the verification SUMMARY:
  P1-A: SSRF DNS-rebinding mitigation — fetch-time re-validation
  P1-B: HTTP /send idempotency (Idempotency-Key header)
  P1-C: webhook HMAC replay defense (V2 signature + timestamp header)

Each block leaves the prior P0 contract intact; tests here add coverage
without changing existing assertions.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from email_service.api import (  # noqa: E402
    MAX_IDEMPOTENCY_KEY_LEN,
    _IdempotencyCache,
    _SlidingWindowLimiter,
    create_app,
)
from email_service.notifiers import OTPNotifier  # noqa: E402
from email_service.sender import SendResult  # noqa: E402
from email_service.webhooks import (  # noqa: E402
    SIGNATURE_HEADER,
    SIGNATURE_HEADER_V2,
    TIMESTAMP_HEADER,
    _sign,
    _sign_v2,
    deliver_webhook,
)


# ============================================================================
# P1-A. SSRF DNS rebinding — fetch-time re-validation.
# ============================================================================
class TestP1A_FetchTimeSSRFRevalidation:
    def test_fetch_time_validation_rejects_private_ip(self):
        """Even if validator passed at parse time, hitting a private IP at
        fetch time must be blocked. Simulates DNS rebinding."""
        # No mock — actual hostname won't resolve, but we point straight at
        # a literal private IP to bypass DNS.
        transport = httpx.MockTransport(lambda req: httpx.Response(200))
        client = httpx.Client(transport=transport)
        result = deliver_webhook(
            "http://10.0.0.5/hook",
            {"message_id": "<m>"},
            secret=None,
            client=client,
        )
        assert result is False, (
            "fetch-time validator must block private IP literal even "
            "when transport is mocked"
        )

    def test_fetch_time_validation_rejects_loopback(self):
        transport = httpx.MockTransport(lambda req: httpx.Response(200))
        client = httpx.Client(transport=transport)
        assert deliver_webhook(
            "http://127.0.0.1/hook",
            {"message_id": "<m>"},
            secret=None,
            client=client,
        ) is False

    def test_fetch_time_validation_rejects_aws_metadata(self):
        transport = httpx.MockTransport(lambda req: httpx.Response(200))
        client = httpx.Client(transport=transport)
        assert deliver_webhook(
            "http://169.254.169.254/latest/meta-data",
            {"message_id": "<m>"},
            secret=None,
            client=client,
        ) is False

    def test_dns_rebinding_simulation_blocks_second_resolution(
        self, monkeypatch
    ):
        """Hostname allowed at parse time, but at fetch time the validator's
        re-resolution returns a private IP — must abort, no HTTP call."""
        # Imagine: Pydantic parse-time validation already passed because the
        # first DNS resolution returned a public IP. By the time the
        # BackgroundTask runs deliver_webhook, DNS has rebound. Our second
        # validation catches it.
        import socket
        rebound = {"called": 0}

        def fake_resolver(host, port):
            rebound["called"] += 1
            # Always returns a loopback IP — simulating post-rebind state.
            return [(socket.AF_INET, None, None, "", ("127.0.0.1", 0))]

        # Patch the resolver inside url_validation by monkeypatching
        # socket.getaddrinfo (validate_webhook_url falls back to it).
        monkeypatch.setattr("email_service.url_validation.socket.getaddrinfo",
                            fake_resolver)

        transport_called = {"n": 0}

        def transport_handler(req):
            transport_called["n"] += 1
            return httpx.Response(200)

        client = httpx.Client(transport=httpx.MockTransport(transport_handler))
        result = deliver_webhook(
            "http://example.com/hook",
            {"message_id": "<m>"},
            secret=None,
            client=client,
        )
        assert result is False
        assert transport_called["n"] == 0, (
            "fetch-time validation should reject BEFORE any HTTP attempt"
        )

    def test_validation_failure_increments_failure_counter(self):
        """A blocked webhook must be counted as a delivery failure."""
        from email_service.metrics import email_webhook_failed_total

        # Read current counter value (prometheus counters expose _value).
        try:
            before = email_webhook_failed_total._value.get()
        except AttributeError:
            # No-op counter when prometheus_client is missing.
            pytest.skip("prometheus_client not installed")

        transport = httpx.MockTransport(lambda req: httpx.Response(200))
        client = httpx.Client(transport=transport)
        deliver_webhook(
            "http://10.0.0.1/x",
            {"message_id": "<m>"},
            secret=None,
            client=client,
        )

        after = email_webhook_failed_total._value.get()
        assert after > before


# ============================================================================
# P1-B. HTTP /send idempotency.
# ============================================================================
class TestP1B_Idempotency:
    @staticmethod
    def _sender_ok(message_id: str = "<a@h>") -> MagicMock:
        s = MagicMock()
        s.send.return_value = SendResult(sent=True, message_id=message_id)
        return s

    def _app(self, sender, cache=None):
        return create_app(
            sender=sender,
            api_key="k",
            otp=MagicMock(spec=OTPNotifier),
            idempotency_cache=cache,
            rate_limiter=_SlidingWindowLimiter(
                max_requests=1000, window_seconds=60.0
            ),
        )

    def _post(self, client, key=None, body=None):
        body = body or {
            "to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"
        }
        headers = {"Authorization": "Bearer k"}
        if key is not None:
            headers["Idempotency-Key"] = key
        return client.post("/send", headers=headers, json=body)

    def test_repeated_key_returns_cached_response_and_does_not_resend(self):
        sender = self._sender_ok("<msg-1@h>")
        cache = _IdempotencyCache(ttl_seconds=300, max_entries=100)
        client = TestClient(self._app(sender, cache))

        r1 = self._post(client, key="abc-123")
        assert r1.status_code == 200
        assert r1.json()["message_id"] == "<msg-1@h>"
        assert sender.send.call_count == 1

        # Second call with same key: cached path. Sender must NOT be invoked
        # again, response identical.
        r2 = self._post(client, key="abc-123")
        assert r2.status_code == 200
        assert r2.json() == r1.json()
        assert sender.send.call_count == 1

    def test_different_keys_process_independently(self):
        sender = self._sender_ok()
        cache = _IdempotencyCache(ttl_seconds=300, max_entries=100)
        client = TestClient(self._app(sender, cache))

        assert self._post(client, key="k1").status_code == 200
        assert self._post(client, key="k2").status_code == 200
        assert sender.send.call_count == 2

    def test_no_key_means_no_dedup(self):
        sender = self._sender_ok()
        cache = _IdempotencyCache(ttl_seconds=300, max_entries=100)
        client = TestClient(self._app(sender, cache))

        assert self._post(client).status_code == 200
        assert self._post(client).status_code == 200
        assert sender.send.call_count == 2

    def test_failed_send_is_not_cached(self):
        """502 responses must NOT be cached — caller may retry after fix."""
        sender = MagicMock()
        sender.send.return_value = SendResult(
            sent=False, error_code="smtp_timeout", error_message="boom"
        )
        cache = _IdempotencyCache(ttl_seconds=300, max_entries=100)
        client = TestClient(self._app(sender, cache))

        r1 = self._post(client, key="will-fail")
        assert r1.status_code == 502
        assert sender.send.call_count == 1

        # Same key; sender returns success this time.
        sender.send.return_value = SendResult(sent=True, message_id="<ok@h>")
        r2 = self._post(client, key="will-fail")
        assert r2.status_code == 200
        assert sender.send.call_count == 2, (
            "failed send must not be cached — retry must hit sender"
        )

    def test_oversized_idempotency_key_rejected(self):
        sender = self._sender_ok()
        cache = _IdempotencyCache(ttl_seconds=300, max_entries=100)
        client = TestClient(self._app(sender, cache))
        too_long = "a" * (MAX_IDEMPOTENCY_KEY_LEN + 1)
        r = self._post(client, key=too_long)
        assert r.status_code == 400
        assert "Idempotency-Key" in r.text

    def test_cache_disabled_when_ttl_zero(self):
        sender = self._sender_ok()
        cache = _IdempotencyCache(ttl_seconds=0, max_entries=100)
        assert cache.enabled is False
        client = TestClient(self._app(sender, cache))

        assert self._post(client, key="k").status_code == 200
        assert self._post(client, key="k").status_code == 200
        assert sender.send.call_count == 2, (
            "disabled cache must not dedup"
        )

    def test_cache_evicts_at_capacity(self):
        cache = _IdempotencyCache(ttl_seconds=300, max_entries=3)
        # Fill at three different (bearer, key) tuples.
        cache.put("b", "k1", {"v": 1}, now=100.0)
        cache.put("b", "k2", {"v": 2}, now=101.0)
        cache.put("b", "k3", {"v": 3}, now=102.0)
        # Adding a 4th forces eviction (oldest expiry = k1).
        cache.put("b", "k4", {"v": 4}, now=103.0)
        assert cache.get("b", "k1", now=104.0) is None
        assert cache.get("b", "k4", now=104.0) == {"v": 4}

    def test_cache_isolates_bearers(self):
        """Two different bearer tokens with the same key must NOT collide."""
        cache = _IdempotencyCache(ttl_seconds=300, max_entries=100)
        cache.put("bearer-a", "key", {"who": "a"})
        cache.put("bearer-b", "key", {"who": "b"})
        assert cache.get("bearer-a", "key") == {"who": "a"}
        assert cache.get("bearer-b", "key") == {"who": "b"}


# ============================================================================
# P1-C. webhook HMAC replay defense.
# ============================================================================
class TestP1C_WebhookReplayDefense:
    def _capture(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_ALLOW_HOSTS", "hook")
        captured = {}

        def handler(req: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(req.headers)
            captured["body"] = bytes(req.content)
            return httpx.Response(200)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        return captured, client

    def test_timestamp_header_present_and_epoch(self, monkeypatch):
        captured, client = self._capture(monkeypatch)
        ok = deliver_webhook(
            "http://hook/x", {"message_id": "<m>"}, secret=None, client=client
        )
        assert ok is True
        ts = captured["headers"].get(TIMESTAMP_HEADER.lower())
        assert ts is not None
        # Must parse as integer epoch seconds, recent (within last minute).
        ts_int = int(ts)
        import time as _time
        assert abs(_time.time() - ts_int) < 60

    def test_v2_signature_covers_timestamp_and_body(self, monkeypatch):
        captured, client = self._capture(monkeypatch)
        secret = "topsecret"
        ok = deliver_webhook(
            "http://hook/x",
            {"message_id": "<m>", "status": "delivered"},
            secret=secret,
            client=client,
        )
        assert ok is True

        body = captured["body"]
        ts = captured["headers"][TIMESTAMP_HEADER.lower()]
        v2 = captured["headers"].get(SIGNATURE_HEADER_V2.lower())
        assert v2 is not None

        expected = _sign_v2(ts, body, secret)
        assert hmac.compare_digest(v2, expected)

    def test_v1_signature_still_present_for_backward_compat(self, monkeypatch):
        captured, client = self._capture(monkeypatch)
        secret = "s"
        deliver_webhook(
            "http://hook/x",
            {"message_id": "<m>"},
            secret=secret,
            client=client,
        )
        v1 = captured["headers"].get(SIGNATURE_HEADER.lower())
        assert v1 is not None
        body = captured["body"]
        assert v1 == _sign(body, secret)

    def test_v2_signature_differs_for_different_timestamps(self):
        """Replay defense: same body + same secret + DIFFERENT timestamp
        produces a different V2 signature, so a captured payload cannot be
        replayed at a later time with a forged-but-valid V2 signature."""
        body = b'{"m":"x"}'
        secret = "s"
        sig_a = _sign_v2("1700000000", body, secret)
        sig_b = _sign_v2("1700000001", body, secret)
        assert sig_a != sig_b

    def test_no_signature_headers_when_no_secret(self, monkeypatch):
        captured, client = self._capture(monkeypatch)
        deliver_webhook(
            "http://hook/x", {"message_id": "<m>"}, secret=None, client=client
        )
        assert SIGNATURE_HEADER.lower() not in captured["headers"]
        assert SIGNATURE_HEADER_V2.lower() not in captured["headers"]
        # Timestamp header is always emitted (anti-replay relies on it).
        assert TIMESTAMP_HEADER.lower() in captured["headers"]
