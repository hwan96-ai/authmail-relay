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
from unittest.mock import MagicMock, patch

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
        cache.put("b", "k1", "fp1", {"v": 1}, now=100.0)
        cache.put("b", "k2", "fp2", {"v": 2}, now=101.0)
        cache.put("b", "k3", "fp3", {"v": 3}, now=102.0)
        # Adding a 4th forces eviction (oldest expiry = k1).
        cache.put("b", "k4", "fp4", {"v": 4}, now=103.0)
        assert cache.get("b", "k1", now=104.0) is None
        # get() now returns {fingerprint, response} envelope.
        k4 = cache.get("b", "k4", now=104.0)
        assert k4 is not None and k4["response"] == {"v": 4}
        assert k4["fingerprint"] == "fp4"

    def test_cache_isolates_bearers(self):
        """Two different bearer tokens with the same key must NOT collide."""
        cache = _IdempotencyCache(ttl_seconds=300, max_entries=100)
        cache.put("bearer-a", "key", "fp", {"who": "a"})
        cache.put("bearer-b", "key", "fp", {"who": "b"})
        assert cache.get("bearer-a", "key")["response"] == {"who": "a"}
        assert cache.get("bearer-b", "key")["response"] == {"who": "b"}


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


# ============================================================================
# NEW-V-1. SSRF re-validation across retries — defeats inter-retry DNS rebind.
# ============================================================================
class TestNewV1_PerRetrySSRFRevalidation:
    def test_ssrf_revalidate_between_retries(self, monkeypatch):
        """First DNS resolution returns a public IP (validator passes →
        httpx returns 503). Second resolution returns 127.0.0.1 (private)
        → second attempt MUST be blocked before httpx is invoked."""
        import socket
        # Resolver state: 1st call public, 2nd+ loopback.
        call_count = {"n": 0}

        def rebinding_resolver(host, port):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [(socket.AF_INET, None, None, "",
                         ("93.184.216.34", 0))]  # example.com public IP
            return [(socket.AF_INET, None, None, "", ("127.0.0.1", 0))]

        monkeypatch.setattr(
            "email_service.url_validation.socket.getaddrinfo",
            rebinding_resolver,
        )
        # httpx returns 503 on first POST, forcing a retry. Second attempt
        # should NEVER reach httpx because re-validate blocks.
        http_calls = {"n": 0}

        def transport_handler(req):
            http_calls["n"] += 1
            return httpx.Response(503)

        client = httpx.Client(transport=httpx.MockTransport(transport_handler))
        with patch("email_service.webhooks.time.sleep"):
            result = deliver_webhook(
                "http://example.com/hook",
                {"message_id": "<m>"},
                secret=None,
                client=client,
                max_retries=3,
            )
        assert result is False
        # 1 attempt succeeded validation, hit httpx (503). 2nd attempt
        # blocked at re-validation, no httpx call.
        assert http_calls["n"] == 1, (
            f"expected exactly 1 httpx attempt before rebind block, "
            f"got {http_calls['n']}"
        )
        # Validator called at least twice (once per retry attempt that
        # reached the validation step).
        assert call_count["n"] >= 2

    def test_repeated_failures_revalidate_each_time(self, monkeypatch):
        """Even with no rebind, validator runs once per retry attempt."""
        monkeypatch.setenv("WEBHOOK_ALLOW_HOSTS", "hook")
        validate_calls = {"n": 0}
        import email_service.webhooks as webhooks_mod
        original = webhooks_mod.validate_webhook_url

        def counting_validator(url, **kw):
            validate_calls["n"] += 1
            return original(url, **kw)

        monkeypatch.setattr(webhooks_mod, "validate_webhook_url",
                            counting_validator)

        client = httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(500))
        )
        with patch("email_service.webhooks.time.sleep"):
            deliver_webhook(
                "http://hook/x",
                {"message_id": "<m>"},
                secret=None,
                client=client,
                max_retries=3,
            )
        assert validate_calls["n"] == 3, (
            f"validator should run once per attempt, got {validate_calls['n']}"
        )


# ============================================================================
# NEW-V-2. Idempotency body fingerprint enforcement.
# ============================================================================
class TestNewV2_IdempotencyBodyFingerprint:
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

    def test_idempotency_same_body_same_key_cached(self):
        """Same key + same body → identical response, sender called once."""
        sender = self._sender_ok("<msg-1@h>")
        cache = _IdempotencyCache(ttl_seconds=300, max_entries=100)
        client = TestClient(self._app(sender, cache))

        body = {"to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"}
        headers = {"Authorization": "Bearer k", "Idempotency-Key": "K"}

        r1 = client.post("/send", headers=headers, json=body)
        r2 = client.post("/send", headers=headers, json=body)

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json() == r2.json()
        assert sender.send.call_count == 1, (
            "same body + same key must hit cache; sender called only once"
        )

    def test_idempotency_different_body_same_key_rejected(self):
        """Same key + different body → 409 Conflict, sender called only
        for the FIRST (legitimate) request."""
        sender = self._sender_ok("<msg-1@h>")
        cache = _IdempotencyCache(ttl_seconds=300, max_entries=100)
        client = TestClient(self._app(sender, cache))

        body_a = {"to": "u@t.com", "subject": "S-A", "html_body": "<p>A</p>"}
        body_b = {"to": "u@t.com", "subject": "S-B", "html_body": "<p>B</p>"}
        headers = {"Authorization": "Bearer k", "Idempotency-Key": "K"}

        r1 = client.post("/send", headers=headers, json=body_a)
        r2 = client.post("/send", headers=headers, json=body_b)

        assert r1.status_code == 200
        assert r2.status_code == 409
        assert "different request body" in r2.text
        assert sender.send.call_count == 1, (
            "second (mismatched) request must not invoke sender"
        )

    def test_idempotency_different_key_different_body_both_process(self):
        sender = self._sender_ok()
        cache = _IdempotencyCache(ttl_seconds=300, max_entries=100)
        client = TestClient(self._app(sender, cache))
        body_a = {"to": "u@t.com", "subject": "A", "html_body": "<p>A</p>"}
        body_b = {"to": "u@t.com", "subject": "B", "html_body": "<p>B</p>"}

        r1 = client.post(
            "/send",
            headers={"Authorization": "Bearer k", "Idempotency-Key": "K1"},
            json=body_a,
        )
        r2 = client.post(
            "/send",
            headers={"Authorization": "Bearer k", "Idempotency-Key": "K2"},
            json=body_b,
        )
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert sender.send.call_count == 2


# ============================================================================
# NEW-V-3. Idempotency concurrency — single execution per key.
# ============================================================================
class TestNewV3_IdempotencyConcurrency:
    def test_idempotency_concurrent_requests_single_execution(self):
        """10 concurrent requests with the same key + same body must
        result in EXACTLY ONE sender.send invocation."""
        from concurrent.futures import ThreadPoolExecutor
        import threading

        # Sender that holds briefly so the race window is real, then
        # returns a single canonical SendResult.
        send_started = threading.Event()
        proceed = threading.Event()

        def slow_send(**kwargs):
            # First caller blocks until released; concurrent callers should
            # be waiting on the per-key lock and never reach this.
            send_started.set()
            proceed.wait(timeout=2.0)
            return SendResult(sent=True, message_id="<once@h>")

        sender = MagicMock()
        sender.send.side_effect = slow_send

        cache = _IdempotencyCache(ttl_seconds=300, max_entries=100)
        app = create_app(
            sender=sender,
            api_key="k",
            otp=MagicMock(spec=OTPNotifier),
            idempotency_cache=cache,
            rate_limiter=_SlidingWindowLimiter(
                max_requests=10_000, window_seconds=60.0
            ),
        )
        client = TestClient(app)
        body = {"to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"}
        headers = {"Authorization": "Bearer k", "Idempotency-Key": "K"}

        def post():
            return client.post("/send", headers=headers, json=body)

        results = []
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(post) for _ in range(10)]
            # Let the first sender call commit before releasing.
            send_started.wait(timeout=2.0)
            proceed.set()
            for f in futures:
                results.append(f.result(timeout=5.0))

        statuses = [r.status_code for r in results]
        assert statuses.count(200) == 10, (
            f"expected all 10 to return 200, got {statuses}"
        )
        # All bodies identical (one canonical response from the single
        # invocation, replayed via cache to the other 9).
        bodies = [r.json() for r in results]
        assert all(b == bodies[0] for b in bodies)
        assert sender.send.call_count == 1, (
            f"expected exactly one sender.send invocation, got "
            f"{sender.send.call_count}"
        )

    def test_different_keys_run_in_parallel(self):
        """Two different keys must NOT block each other — second call
        does not have to wait for first."""
        from concurrent.futures import ThreadPoolExecutor
        import threading

        in_flight = threading.Semaphore(0)
        proceed = threading.Event()

        def gated_send(**kwargs):
            in_flight.release()
            proceed.wait(timeout=2.0)
            return SendResult(sent=True, message_id="<x@h>")

        sender = MagicMock()
        sender.send.side_effect = gated_send

        cache = _IdempotencyCache(ttl_seconds=300, max_entries=100)
        app = create_app(
            sender=sender,
            api_key="k",
            otp=MagicMock(spec=OTPNotifier),
            idempotency_cache=cache,
            rate_limiter=_SlidingWindowLimiter(
                max_requests=10_000, window_seconds=60.0
            ),
        )
        client = TestClient(app)
        body = {"to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"}

        def post(key):
            return client.post(
                "/send",
                headers={
                    "Authorization": "Bearer k", "Idempotency-Key": key,
                },
                json=body,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(post, "K1")
            f2 = pool.submit(post, "K2")
            # Both must reach sender (in parallel) before proceed is set.
            # If they were serialized, only one would have entered.
            assert in_flight.acquire(timeout=2.0)
            assert in_flight.acquire(timeout=2.0)
            proceed.set()
            r1 = f1.result(timeout=5.0)
            r2 = f2.result(timeout=5.0)

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert sender.send.call_count == 2


# ============================================================================
# NEW-V-4. Lock-eviction race fix (code-L23).
#
# `_IdempotencyCache.get()` previously popped both `_store[key]` AND
# `_key_locks[key]` when an entry expired. That orphaned any in-flight
# holder of the old Lock instance: the next caller would `get_lock(key)`
# and create a *fresh* Lock, allowing two processors to run the same key
# concurrently. The fix decouples the lock dict lifetime from cache entry
# lifetime — locks persist across expiry/eviction.
# ============================================================================
class TestNewV4_LockEvictionRace:
    def test_idempotency_lock_dict_retains_lock_after_cache_expiry(self):
        """Lock identity for (bearer, key) must survive cache entry expiry.

        This is the unit-level guarantee NEW-V-4 depends on; the race in
        the concurrent test cannot occur if this invariant holds.
        """
        cache = _IdempotencyCache(ttl_seconds=300, max_entries=100)
        lock_before = cache.get_lock("b", "k")

        # Insert an entry then force-expire it via a future `now`.
        cache.put("b", "k", "fp", {"v": 1}, now=100.0)
        # Confirm expiry path runs (entry must look stale) — get returns None.
        assert cache.get("b", "k", now=100.0 + 400.0) is None

        # The lock dict must STILL contain the same Lock instance.
        lock_after = cache.get_lock("b", "k")
        assert lock_after is lock_before, (
            "lock identity changed after cache entry expiry — "
            "in-flight holders would be orphaned"
        )

    def test_idempotency_lock_retained_after_capacity_eviction(self):
        """Eviction by capacity also must not drop the lock."""
        cache = _IdempotencyCache(ttl_seconds=300, max_entries=2)
        lock_k1 = cache.get_lock("b", "k1")
        cache.put("b", "k1", "fp1", {"v": 1}, now=100.0)
        cache.put("b", "k2", "fp2", {"v": 2}, now=101.0)
        # Adding k3 forces eviction of oldest (k1) from _store.
        cache.put("b", "k3", "fp3", {"v": 3}, now=102.0)
        # k1's store entry is gone but its lock object must remain.
        assert cache.get("b", "k1", now=103.0) is None
        assert cache.get_lock("b", "k1") is lock_k1, (
            "lock identity changed after capacity eviction"
        )

    def test_idempotency_lock_eviction_race(self):
        """Unit-level race verification: expired prior entry + concurrent
        same-key arrivals must NOT cause duplicate processing.

        This test was previously flaky (~40%) when written against the
        Starlette TestClient — TestClient is not thread-safe (see
        `git-L06` in .claude/learnings/git/learnings.md). We now exercise
        ``_IdempotencyCache.get_lock`` + locking directly, mirroring the
        critical section structure inside ``_idempotency_guard`` without
        the HTTP / ASGI layer.

        Reproduces the NEW-V-4 scenario: prior entry exists but is stale
        when threads A+B arrive. Before the fix, A would pop _store AND
        _key_locks; B would create a fresh Lock and process in parallel
        with A. With the fix, both threads share the same Lock via the
        retained dict entry → exactly one processes.
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor

        cache = _IdempotencyCache(ttl_seconds=0.05, max_entries=100)
        # Seed an entry that is already expired by the time concurrent
        # readers arrive (`now=0.0` against a real monotonic clock far in
        # the future).
        cache.put(
            "bearer-x",
            "RACE-K",
            fingerprint="stale-fp",
            response={"sent": True, "message_id": "<stale@h>"},
            now=0.0,
        )

        # Sanity: the seeded lock dict is empty (put does not create
        # locks). The first concurrent caller creates the lock; all later
        # callers MUST receive the same instance.
        assert ("bearer-x", "RACE-K") not in cache._key_locks

        process_count = {"n": 0}
        count_lock = threading.Lock()
        send_started = threading.Event()
        proceed = threading.Event()

        FRESH_FP = "fresh-fp"
        FRESH_RESPONSE = {"sent": True, "message_id": "<fresh@h>"}

        def emulate_guard() -> tuple[str, dict]:
            """Mirror the production ``_idempotency_guard`` critical
            section (api.py). HTTP layer omitted on purpose."""
            lock = cache.get_lock("bearer-x", "RACE-K")
            with lock:
                existing = cache.get("bearer-x", "RACE-K")
                if existing is not None:
                    # Cache hit. In production the fingerprint would be
                    # compared here; we use the same FP across threads so
                    # the comparison would pass.
                    return ("cached", existing["response"])
                # Cache miss — emulate the slow send + store.
                with count_lock:
                    process_count["n"] += 1
                send_started.set()
                # Block so subsequent threads queue on the per-key lock.
                proceed.wait(timeout=3.0)
                cache.put(
                    "bearer-x", "RACE-K", FRESH_FP, FRESH_RESPONSE,
                )
                return ("fresh", FRESH_RESPONSE)

        results: list[tuple[str, dict]] = []
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(emulate_guard) for _ in range(10)]
            # First arrival reaches the cache-miss path; release the gate.
            assert send_started.wait(timeout=3.0), (
                "no thread reached the cache-miss branch"
            )
            proceed.set()
            for f in futures:
                results.append(f.result(timeout=5.0))

        # Critical invariant: only ONE thread processed despite the
        # expired prior entry + concurrent arrival. The other nine took
        # the cache-hit branch after the first stored its result.
        assert process_count["n"] == 1, (
            f"lock-eviction race regressed: expected 1 process, "
            f"got {process_count['n']}"
        )

        statuses = [r[0] for r in results]
        # Exactly one "fresh" path and nine "cached" replays.
        assert statuses.count("fresh") == 1, statuses
        assert statuses.count("cached") == 9, statuses
        # All threads observe the same response payload.
        assert all(r[1] == FRESH_RESPONSE for r in results)

        # Final lock-identity assertion: the dict entry created by the
        # first concurrent caller is still the SAME instance everyone
        # holds — i.e., the fix's invariant held throughout the race.
        final_lock = cache.get_lock("bearer-x", "RACE-K")
        # We don't have direct access to the threads' Lock references,
        # but if a fresh Lock had been created mid-race, the dict would
        # contain a different instance now than the one threads used to
        # serialize. Re-fetching twice must return identity-equal locks.
        assert final_lock is cache.get_lock("bearer-x", "RACE-K")

    def test_idempotency_long_first_blocks_waiter_eventually_returns_cached(
        self,
    ):
        """First caller's slow send must not produce a second sender
        invocation for a concurrent same-key + same-body waiter; the
        waiter blocks on the per-key lock and receives the cached
        response after the first completes.
        """
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import time as _time

        first_in_send = threading.Event()
        release_first = threading.Event()

        def slow_first_send(**kwargs):
            first_in_send.set()
            release_first.wait(timeout=3.0)
            return SendResult(sent=True, message_id="<first@h>")

        sender = MagicMock()
        sender.send.side_effect = slow_first_send

        cache = _IdempotencyCache(ttl_seconds=300, max_entries=100)
        app = create_app(
            sender=sender,
            api_key="k",
            otp=MagicMock(spec=OTPNotifier),
            idempotency_cache=cache,
            rate_limiter=_SlidingWindowLimiter(
                max_requests=10_000, window_seconds=60.0
            ),
        )
        client = TestClient(app)
        body = {"to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"}
        headers = {"Authorization": "Bearer k", "Idempotency-Key": "WAIT-K"}

        def post():
            return client.post("/send", headers=headers, json=body)

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_first = pool.submit(post)
            # Wait for first to start sending so the second arrives after
            # the lock is held.
            assert first_in_send.wait(timeout=3.0)
            f_second = pool.submit(post)
            # Give the second thread a moment to enter the route and block
            # on the lock. Then release the first.
            _time.sleep(0.1)
            assert sender.send.call_count == 1, (
                "second request should be blocked on the lock; sender "
                "must not have been called twice yet"
            )
            release_first.set()
            r1 = f_first.result(timeout=5.0)
            r2 = f_second.result(timeout=5.0)

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json() == r2.json(), (
            "waiter must receive the cached response from the first call"
        )
        assert sender.send.call_count == 1, (
            f"expected exactly one sender execution; got "
            f"{sender.send.call_count}"
        )
