"""Tests for email_service.client.EmailServiceClient."""
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from email_service.client import EmailServiceClient, EmailServiceError


def _handler(responses):
    """Build an httpx.MockTransport handler from a {(method, path): (status, body)} map."""
    requests: list[httpx.Request] = []

    def h(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        key = (request.method, request.url.path)
        if key not in responses:
            return httpx.Response(404, json={"detail": "not found"})
        status, body = responses[key]
        return httpx.Response(status, json=body)

    return h, requests


def _client(handler, api_key: str = "key") -> EmailServiceClient:
    return EmailServiceClient(
        "http://email-service:8000",
        api_key,
        transport=httpx.MockTransport(handler),
    )


class TestHealth:
    def test_returns_ok(self):
        h, reqs = _handler({("GET", "/health"): (200, {"status": "ok"})})
        with _client(h) as c:
            assert c.health() == {"status": "ok"}
        assert reqs[0].headers["authorization"] == "Bearer key"


class TestSend:
    def test_auth_header_set(self):
        h, reqs = _handler({("POST", "/send"): (200, {"sent": True})})
        with _client(h, api_key="secret") as c:
            c.send("u@t.com", "s", "<p>x</p>")
        assert reqs[0].headers["authorization"] == "Bearer secret"

    def test_returns_server_json(self):
        h, _ = _handler({("POST", "/send"): (200, {"sent": True})})
        with _client(h) as c:
            assert c.send("u@t.com", "s", "<p>x</p>") == {"sent": True}

    def test_forwards_optional_fields(self):
        h, reqs = _handler({("POST", "/send"): (200, {"sent": True})})
        with _client(h) as c:
            c.send(
                "u@t.com", "s", "<p>x</p>",
                text_body="t", cc=["c@t.com"], bcc=["b@t.com"],
            )
        body = json.loads(reqs[0].content)
        assert body == {
            "to": "u@t.com", "subject": "s", "html_body": "<p>x</p>",
            "text_body": "t", "cc": ["c@t.com"], "bcc": ["b@t.com"],
        }

    def test_omits_none_fields(self):
        h, reqs = _handler({("POST", "/send"): (200, {"sent": True})})
        with _client(h) as c:
            c.send("u@t.com", "s", "<p>x</p>")
        body = json.loads(reqs[0].content)
        assert body == {"to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"}

    def test_dry_run_adds_header(self):
        h, reqs = _handler(
            {("POST", "/send"): (200, {"sent": False, "dry_run": True, "message": "ok"})}
        )
        with _client(h) as c:
            result = c.send("u@t.com", "s", "<p>x</p>", dry_run=True)
        assert reqs[0].headers.get("x-dry-run") == "true"
        assert result["dry_run"] is True

    def test_no_dry_run_header_by_default(self):
        h, reqs = _handler({("POST", "/send"): (200, {"sent": True})})
        with _client(h) as c:
            c.send("u@t.com", "s", "<p>x</p>")
        assert "x-dry-run" not in reqs[0].headers

    def test_4xx_raises(self):
        h, _ = _handler({("POST", "/send"): (401, {"detail": "no"})})
        with _client(h) as c:
            with pytest.raises(httpx.HTTPStatusError):
                c.send("u@t.com", "s", "<p>x</p>")

    def test_502_raises_email_service_error_with_code(self):
        h, _ = _handler(
            {
                ("POST", "/send"): (
                    502,
                    {"detail": {"error_code": "smtp_auth_failed",
                                "message": "535 bad creds"}},
                )
            }
        )
        with _client(h) as c:
            with pytest.raises(EmailServiceError) as excinfo:
                c.send("u@t.com", "s", "<p>x</p>")
        err = excinfo.value
        assert err.error_code == "smtp_auth_failed"
        assert err.status_code == 502
        assert "535" in (err.message or "")

    def test_500_still_raises_generic_httpx(self):
        # Non-502 5xx keep the generic raise_for_status semantics.
        h, _ = _handler({("POST", "/send"): (500, {"detail": "boom"})})
        with _client(h) as c:
            with pytest.raises(httpx.HTTPStatusError):
                c.send("u@t.com", "s", "<p>x</p>")


class TestSendMagicLink:
    def test_payload_shape(self):
        h, reqs = _handler({("POST", "/send/magic-link"): (200, {"sent": True})})
        with _client(h) as c:
            c.send_magic_link("u@t.com", "Kim", "tok")
        assert json.loads(reqs[0].content) == {
            "to": "u@t.com", "user_name": "Kim", "token": "tok",
        }

    def test_dry_run(self):
        h, reqs = _handler(
            {("POST", "/send/magic-link"): (200, {"sent": False, "dry_run": True})}
        )
        with _client(h) as c:
            c.send_magic_link("u@t.com", "Kim", "tok", dry_run=True)
        assert reqs[0].headers.get("x-dry-run") == "true"


class TestSendOTP:
    def test_payload_shape(self):
        h, reqs = _handler({("POST", "/send/otp"): (200, {"sent": True})})
        with _client(h) as c:
            c.send_otp("u@t.com", "Kim", "123456")
        assert json.loads(reqs[0].content) == {
            "to": "u@t.com", "user_name": "Kim", "code": "123456",
        }

    def test_dry_run(self):
        h, reqs = _handler(
            {("POST", "/send/otp"): (200, {"sent": False, "dry_run": True})}
        )
        with _client(h) as c:
            c.send_otp("u@t.com", "Kim", "123456", dry_run=True)
        assert reqs[0].headers.get("x-dry-run") == "true"


class TestKeywordOnlyDryRun:
    """dry_run must be keyword-only to prevent silent binding to text_body/etc."""

    def test_send_rejects_positional_dry_run(self):
        h, _ = _handler({("POST", "/send"): (200, {"sent": True})})
        with _client(h) as c:
            with pytest.raises(TypeError):
                c.send("a@b.com", "hi", "<p>x</p>", True)

    def test_send_magic_link_rejects_positional_dry_run(self):
        h, _ = _handler({("POST", "/send/magic-link"): (200, {"sent": True})})
        with _client(h) as c:
            with pytest.raises(TypeError):
                c.send_magic_link("a@b.com", "홍길동", "tok", True)

    def test_send_otp_rejects_positional_dry_run(self):
        h, _ = _handler({("POST", "/send/otp"): (200, {"sent": True})})
        with _client(h) as c:
            with pytest.raises(TypeError):
                c.send_otp("a@b.com", "홍길동", "123456", True)

    def test_keyword_dry_run_still_works(self):
        h, reqs = _handler({("POST", "/send/otp"): (200, {"sent": False, "dry_run": True})})
        with _client(h) as c:
            c.send_otp("a@b.com", "홍길동", "123456", dry_run=True)
        assert reqs[0].headers.get("x-dry-run") == "true"


class TestContextManager:
    def test_closes_on_exit(self):
        h, _ = _handler({})
        c = EmailServiceClient(
            "http://test", "key", transport=httpx.MockTransport(h)
        )
        with c:
            pass
        assert c._client.is_closed

    def test_close_method(self):
        h, _ = _handler({})
        c = EmailServiceClient(
            "http://test", "key", transport=httpx.MockTransport(h)
        )
        c.close()
        assert c._client.is_closed

    def test_base_url_trailing_slash_stripped(self):
        h, reqs = _handler({("GET", "/health"): (200, {"status": "ok"})})
        c = EmailServiceClient(
            "http://test/", "key", transport=httpx.MockTransport(h)
        )
        with c:
            c.health()
        # Base URL should be normalized without trailing slash
        assert reqs[0].url.path == "/health"
