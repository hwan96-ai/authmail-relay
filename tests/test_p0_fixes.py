"""Regression tests for the five P0 issues identified in
``gate-code-2026-05-16-001/SUMMARY.md``.

Each block here verifies a specific P0's contract and is intended to be a
permanent guard against re-introduction.

Indexed by P0 number:
  P0-1: webhook retry backoff is bounded (no threadpool starvation)
  P0-2: webhook_url is SSRF-validated
  P0-3: subject / body / recipient lists have size caps
  P0-4: per-bearer rate limit returns 429 with Retry-After
  P0-5: SMTP disconnect mid-sendmail is non-retriable; post-sendmail = success
"""
from __future__ import annotations

import os
import socket
import smtplib
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from authmail_relay.api import (  # noqa: E402
    MAX_BODY_LEN,
    MAX_SUBJECT_LEN,
    MAX_RECIPIENTS,
    _SlidingWindowLimiter,
    create_app,
)
from authmail_relay.sender import (  # noqa: E402
    ERR_SMTP_DISCONNECT_UNCERTAIN,
    STATUS_DELIVERED,
    STATUS_FAILED,
    SendResult,
    SmtpConfig,
    SmtpSender,
)
from authmail_relay.url_validation import validate_webhook_url  # noqa: E402
from authmail_relay.webhooks import (  # noqa: E402
    DEFAULT_BACKOFFS,
    _jittered,
    deliver_webhook,
)


# ============================================================================
# P0-1. BackgroundTasks + sync sleep → threadpool starvation.
#       Verified by: bounded total backoff sleep + jitter shape.
# ============================================================================
class TestP0_1_BoundedWebhookBackoff:
    def test_default_backoffs_total_under_ten_seconds(self):
        """Worst-case total sleep across all retries must be <= 10s.

        Previously (1, 10, 60) = 71s. New default (1, 2, 5) = 8s.
        """
        assert sum(DEFAULT_BACKOFFS) <= 10.0

    def test_default_backoffs_are_monotonic(self):
        backoffs = list(DEFAULT_BACKOFFS)
        assert backoffs == sorted(backoffs), "backoffs should be non-decreasing"

    def test_jitter_stays_within_band(self):
        # ±25% jitter ratio around the base delay.
        samples = [_jittered(2.0) for _ in range(200)]
        assert all(1.5 <= s <= 2.5 for s in samples), (
            "jitter must stay within ±25% of base delay"
        )
        # Not all identical (jitter actually active).
        assert len(set(round(s, 3) for s in samples)) > 1

    def test_jitter_handles_zero_delay(self):
        assert _jittered(0.0) == 0.0
        assert _jittered(-1.0) == 0.0

    def test_total_sleep_bounded_in_real_retry_loop(self, monkeypatch):
        """End-to-end: maximum cumulative sleep across 3 attempts <= 10s."""
        sleeps: list[float] = []
        monkeypatch.setattr(
            "authmail_relay.webhooks.time.sleep", lambda s: sleeps.append(s)
        )
        transport = httpx.MockTransport(lambda r: httpx.Response(500))
        client = httpx.Client(transport=transport)
        deliver_webhook("https://example.test/", {"m": "x"}, secret=None, client=client)
        assert sum(sleeps) <= 10.0, (
            f"Cumulative sleep {sum(sleeps)}s exceeds bounded budget"
        )


# ============================================================================
# P0-2. SSRF: webhook_url is validated against private/loopback addresses.
# ============================================================================
class TestP0_2_SSRFDefense:
    def test_rejects_non_http_scheme(self):
        with pytest.raises(ValueError, match="http or https"):
            validate_webhook_url("ftp://example.com/x")
        with pytest.raises(ValueError, match="http or https"):
            validate_webhook_url("file:///etc/passwd")

    def test_rejects_aws_metadata_ip(self):
        with pytest.raises(ValueError, match="private, loopback"):
            validate_webhook_url("http://169.254.169.254/latest/meta-data")

    def test_rejects_localhost_ip(self):
        with pytest.raises(ValueError, match="private, loopback"):
            validate_webhook_url("http://127.0.0.1:8080/hook")

    def test_rejects_ipv6_loopback(self):
        with pytest.raises(ValueError, match="private, loopback"):
            validate_webhook_url("http://[::1]/hook")

    @pytest.mark.parametrize("ip", ["10.0.0.5", "192.168.1.1", "172.16.0.1"])
    def test_rejects_private_rfc1918(self, ip):
        with pytest.raises(ValueError, match="private, loopback"):
            validate_webhook_url(f"http://{ip}/hook")

    def test_rejects_link_local_hostname_resolution(self):
        """Hostname resolves to link-local IP → blocked."""
        def fake_resolver(host, port):
            return [(socket.AF_INET, None, None, "", ("169.254.169.254", 0))]
        with pytest.raises(ValueError, match="private, loopback"):
            validate_webhook_url("http://metadata.local/x", resolver=fake_resolver)

    def test_allows_public_ip(self):
        def fake_resolver(host, port):
            return [(socket.AF_INET, None, None, "", ("93.184.216.34", 0))]
        assert validate_webhook_url(
            "http://example.com/hook", resolver=fake_resolver
        ) == "http://example.com/hook"

    def test_rejects_unresolvable_hostname(self):
        def fake_resolver(host, port):
            raise socket.gaierror("nodename nor servname provided")
        with pytest.raises(ValueError, match="could not be resolved"):
            validate_webhook_url("http://nx.invalid/x", resolver=fake_resolver)

    def test_allowlist_bypasses_dns_check(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_ALLOW_HOSTS", "internal.svc,hook")
        # Hostname in allowlist — no DNS check at all.
        assert validate_webhook_url("http://internal.svc/x") == "http://internal.svc/x"
        assert validate_webhook_url("http://hook/x") == "http://hook/x"

    def test_loopback_env_override(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_ALLOW_LOOPBACK", "1")
        # Now loopback IP literal is allowed.
        assert validate_webhook_url("http://127.0.0.1/x") == "http://127.0.0.1/x"

    def test_api_rejects_aws_metadata_at_request_validation(self):
        from authmail_relay.notifiers import OTPNotifier
        app = create_app(
            sender=MagicMock(), api_key="k", otp=MagicMock(spec=OTPNotifier)
        )
        client = TestClient(app)
        resp = client.post(
            "/send",
            headers={"Authorization": "Bearer k"},
            json={
                "to": "u@t.com",
                "subject": "s",
                "html_body": "<p>x</p>",
                "webhook_url": "http://169.254.169.254/latest/meta-data",
            },
        )
        assert resp.status_code == 422
        assert "private, loopback" in resp.text


# ============================================================================
# P0-3. Body / subject / recipient list size caps.
# ============================================================================
class TestP0_3_SizeLimits:
    def _app(self):
        from authmail_relay.notifiers import OTPNotifier
        sender = MagicMock()
        sender.send.return_value = SendResult(sent=True, message_id="<x@h>")
        return create_app(
            sender=sender, api_key="k", otp=MagicMock(spec=OTPNotifier)
        )

    def _post_send(self, client, **overrides):
        body = {
            "to": "u@t.com",
            "subject": "s",
            "html_body": "<p>x</p>",
        }
        body.update(overrides)
        return client.post(
            "/send", headers={"Authorization": "Bearer k"}, json=body
        )

    def test_subject_at_cap_accepted_over_cap_rejected(self):
        client = TestClient(self._app())
        ok = self._post_send(client, subject="a" * MAX_SUBJECT_LEN)
        # Sender is MagicMock — call goes through. Could be 200 or 502 depending
        # on mock return; we only assert the validation layer accepted.
        assert ok.status_code != 422
        too_long = self._post_send(client, subject="a" * (MAX_SUBJECT_LEN + 1))
        assert too_long.status_code == 422

    def test_html_body_over_cap_rejected(self):
        client = TestClient(self._app())
        too_long = self._post_send(client, html_body="a" * (MAX_BODY_LEN + 1))
        assert too_long.status_code == 422

    def test_text_body_over_cap_rejected(self):
        client = TestClient(self._app())
        too_long = self._post_send(client, text_body="a" * (MAX_BODY_LEN + 1))
        assert too_long.status_code == 422

    def test_recipient_list_over_cap_rejected(self):
        client = TestClient(self._app())
        too_many = self._post_send(
            client, cc=[f"x{i}@t.com" for i in range(MAX_RECIPIENTS + 1)]
        )
        assert too_many.status_code == 422


# ============================================================================
# P0-4. Per-bearer rate limit with 429 + Retry-After.
# ============================================================================
class TestP0_4_RateLimit:
    def test_limiter_allows_up_to_n_then_blocks(self):
        limiter = _SlidingWindowLimiter(max_requests=3, window_seconds=60.0)
        t0 = 100.0
        for i in range(3):
            allowed, retry = limiter.check("k", now=t0 + i)
            assert allowed is True
            assert retry == 0.0
        allowed, retry = limiter.check("k", now=t0 + 4)
        assert allowed is False
        assert retry > 0.0

    def test_limiter_recovers_after_window(self):
        limiter = _SlidingWindowLimiter(max_requests=2, window_seconds=10.0)
        assert limiter.check("k", now=100)[0] is True
        assert limiter.check("k", now=101)[0] is True
        assert limiter.check("k", now=102)[0] is False
        # Window elapsed.
        assert limiter.check("k", now=115)[0] is True

    def test_limiter_disabled_when_max_is_zero(self):
        limiter = _SlidingWindowLimiter(max_requests=0, window_seconds=60.0)
        assert limiter.enabled is False
        for _ in range(1000):
            assert limiter.check("anyone")[0] is True

    def test_limiter_isolates_keys(self):
        limiter = _SlidingWindowLimiter(max_requests=1, window_seconds=60.0)
        assert limiter.check("a", now=100)[0] is True
        assert limiter.check("a", now=101)[0] is False
        # Different key still has full quota.
        assert limiter.check("b", now=101)[0] is True

    def test_api_returns_429_after_exceeding_limit(self):
        from authmail_relay.notifiers import OTPNotifier
        sender = MagicMock()
        sender.send.return_value = SendResult(sent=True, message_id="<x>")
        limiter = _SlidingWindowLimiter(max_requests=2, window_seconds=60.0)
        app = create_app(
            sender=sender,
            api_key="k",
            otp=MagicMock(spec=OTPNotifier),
            rate_limiter=limiter,
        )
        client = TestClient(app)
        body = {"to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"}
        headers = {"Authorization": "Bearer k"}
        assert client.post("/send", headers=headers, json=body).status_code == 200
        assert client.post("/send", headers=headers, json=body).status_code == 200
        resp = client.post("/send", headers=headers, json=body)
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        # Retry-After must be a positive integer seconds.
        assert int(resp.headers["Retry-After"]) >= 1

    def test_health_endpoint_is_not_rate_limited(self):
        sender = MagicMock()
        sender.send.return_value = SendResult(sent=True, message_id="<x>")
        limiter = _SlidingWindowLimiter(max_requests=1, window_seconds=60.0)
        app = create_app(
            sender=sender, api_key="k", rate_limiter=limiter
        )
        client = TestClient(app)
        # Exhaust /send quota.
        client.post(
            "/send",
            headers={"Authorization": "Bearer k"},
            json={"to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"},
        )
        # /health still freely accessible.
        for _ in range(5):
            assert client.get("/health").status_code == 200


# ============================================================================
# P0-5. SMTP disconnect-during-sendmail must NOT retry (double-send risk).
#       Disconnect-after-sendmail = treated as delivered.
# ============================================================================
class TestP0_5_DisconnectDuringSendmail:
    def _sender(self, max_retries=2):
        return SmtpSender(
            SmtpConfig(host="h", port=587, user="u@t.com", password="pw"),
            max_retries=max_retries,
            backoff_seconds=(0, 0, 0),
        )

    def test_disconnect_mid_sendmail_does_not_retry(self):
        """Disconnect raised from sendmail() = unknown if message arrived.
        Must not retry (would duplicate)."""
        sender = self._sender(max_retries=3)
        connect_count = {"n": 0}

        def make_server(*a, **k):
            connect_count["n"] += 1
            s = MagicMock()
            s.__enter__.return_value = s
            s.__exit__.return_value = False
            s.has_extn.return_value = True
            s.sendmail.side_effect = smtplib.SMTPServerDisconnected("mid-flow")
            return s

        with patch("authmail_relay.sender.smtplib.SMTP", side_effect=make_server), \
             patch("authmail_relay.sender.time.sleep") as mock_sleep:
            result = sender.send("to@t.com", "s", "<p>x</p>")

        assert result.sent is False
        assert result.error_code == ERR_SMTP_DISCONNECT_UNCERTAIN
        assert result.status == STATUS_FAILED
        assert result.attempts == 1, (
            "must not retry — would double-send if message actually arrived"
        )
        assert connect_count["n"] == 1
        assert mock_sleep.call_count == 0

    def test_disconnect_after_sendmail_returned_is_success(self):
        """sendmail() returns 250 OK, then server drops on QUIT/exit.
        Message was delivered — must return success, no retry."""
        sender = self._sender(max_retries=2)
        connect_count = {"n": 0}

        def make_server(*a, **k):
            connect_count["n"] += 1
            s = MagicMock()
            s.__enter__.return_value = s
            # sendmail succeeds, returns no refusals.
            s.sendmail.return_value = {}
            s.has_extn.return_value = True
            # But context-exit (QUIT) raises disconnect.
            s.__exit__.side_effect = smtplib.SMTPServerDisconnected("quit died")
            return s

        with patch("authmail_relay.sender.smtplib.SMTP", side_effect=make_server), \
             patch("authmail_relay.sender.time.sleep") as mock_sleep:
            result = sender.send("to@t.com", "s", "<p>x</p>")

        assert result.sent is True
        assert result.status == STATUS_DELIVERED
        assert result.attempts == 1
        assert connect_count["n"] == 1
        assert mock_sleep.call_count == 0

    def test_disconnect_after_partial_refusal_preserves_refused_list(self):
        """sendmail() returns with refused dict, then QUIT raises.
        Outcome: partial refusal (status=PARTIAL), no retry."""
        sender = self._sender(max_retries=2)

        def make_server(*a, **k):
            s = MagicMock()
            s.__enter__.return_value = s
            s.sendmail.return_value = {"bad@t.com": (550, b"no such user")}
            s.has_extn.return_value = True
            s.__exit__.side_effect = smtplib.SMTPServerDisconnected("after")
            return s

        with patch("authmail_relay.sender.smtplib.SMTP", side_effect=make_server), \
             patch("authmail_relay.sender.time.sleep"):
            result = sender.send(
                "to@t.com", "s", "<p>x</p>", bcc=["bad@t.com"]
            )

        assert result.sent is False
        assert result.refused == ["bad@t.com"]
        assert result.status == "partial"
        assert result.attempts == 1
