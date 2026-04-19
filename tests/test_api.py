"""HTTP API integration tests."""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from email_service import api as api_module
from email_service.api import create_app
from email_service.notifiers import MagicLinkNotifier, OTPNotifier


API_KEY = "test-key"


def _app(sender=None, magic_link=None, otp=None):
    sender = sender or MagicMock()
    otp = otp or MagicMock(spec=OTPNotifier)
    return create_app(
        sender=sender, api_key=API_KEY, magic_link=magic_link, otp=otp
    )


def _auth():
    return {"Authorization": f"Bearer {API_KEY}"}


class TestSendEmail:
    def test_success(self):
        sender = MagicMock()
        sender.send.return_value = True

        client = TestClient(_app(sender=sender))
        resp = client.post(
            "/send",
            headers=_auth(),
            json={
                "to": "user@test.com",
                "subject": "Hi",
                "html_body": "<p>Hello</p>",
            },
        )

        assert resp.status_code == 200
        assert resp.json() == {"sent": True}
        sender.send.assert_called_once()

    def test_forwards_optional_fields(self):
        sender = MagicMock()
        sender.send.return_value = True

        client = TestClient(_app(sender=sender))
        resp = client.post(
            "/send",
            headers=_auth(),
            json={
                "to": "user@test.com",
                "subject": "Hi",
                "html_body": "<p>Hello</p>",
                "text_body": "Hello",
                "cc": ["cc@test.com"],
                "bcc": ["bcc@test.com"],
            },
        )

        assert resp.status_code == 200
        kwargs = sender.send.call_args.kwargs
        assert kwargs["text_body"] == "Hello"
        assert kwargs["cc"] == ["cc@test.com"]
        assert kwargs["bcc"] == ["bcc@test.com"]

    def test_missing_api_key_returns_401(self):
        sender = MagicMock()

        client = TestClient(_app(sender=sender))
        resp = client.post(
            "/send",
            json={"to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"},
        )

        assert resp.status_code == 401
        sender.send.assert_not_called()

    def test_wrong_api_key_returns_401(self):
        sender = MagicMock()

        client = TestClient(_app(sender=sender))
        resp = client.post(
            "/send",
            headers={"Authorization": "Bearer wrong"},
            json={"to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"},
        )

        assert resp.status_code == 401
        sender.send.assert_not_called()

    def test_missing_required_field_returns_422(self):
        client = TestClient(_app())
        resp = client.post(
            "/send", headers=_auth(), json={"to": "u@t.com", "subject": "s"}
        )

        assert resp.status_code == 422

    def test_crlf_in_to_rejected_before_sender(self):
        sender = MagicMock()

        client = TestClient(_app(sender=sender))
        resp = client.post(
            "/send",
            headers=_auth(),
            json={
                "to": "u@t.com\r\nBcc: evil@t.com",
                "subject": "s",
                "html_body": "<p>x</p>",
            },
        )

        assert resp.status_code == 422
        sender.send.assert_not_called()

    def test_crlf_in_subject_rejected_before_sender(self):
        sender = MagicMock()

        client = TestClient(_app(sender=sender))
        resp = client.post(
            "/send",
            headers=_auth(),
            json={
                "to": "u@t.com",
                "subject": "s\nInjected: yes",
                "html_body": "<p>x</p>",
            },
        )

        assert resp.status_code == 422
        sender.send.assert_not_called()

    def test_crlf_in_cc_rejected_before_sender(self):
        sender = MagicMock()

        client = TestClient(_app(sender=sender))
        resp = client.post(
            "/send",
            headers=_auth(),
            json={
                "to": "u@t.com",
                "subject": "s",
                "html_body": "<p>x</p>",
                "cc": ["ok@t.com\r\nX: y"],
            },
        )

        assert resp.status_code == 422
        sender.send.assert_not_called()

    def test_smtp_failure_returns_502(self):
        sender = MagicMock()
        sender.send.return_value = False

        client = TestClient(_app(sender=sender))
        resp = client.post(
            "/send",
            headers=_auth(),
            json={"to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"},
        )

        assert resp.status_code == 502


class TestSendMagicLink:
    def test_success(self):
        sender = MagicMock()
        magic = MagicMock(spec=MagicLinkNotifier)
        magic.send.return_value = True

        client = TestClient(_app(sender=sender, magic_link=magic))
        resp = client.post(
            "/send/magic-link",
            headers=_auth(),
            json={"to": "u@t.com", "user_name": "Kim", "token": "abc123"},
        )

        assert resp.status_code == 200
        magic.send.assert_called_once_with("u@t.com", "Kim", "abc123")

    def test_not_configured_returns_503(self):
        client = TestClient(_app(magic_link=None))
        resp = client.post(
            "/send/magic-link",
            headers=_auth(),
            json={"to": "u@t.com", "user_name": "Kim", "token": "abc"},
        )

        assert resp.status_code == 503

    def test_auth_required(self):
        magic = MagicMock(spec=MagicLinkNotifier)
        client = TestClient(_app(magic_link=magic))
        resp = client.post(
            "/send/magic-link",
            json={"to": "u@t.com", "user_name": "Kim", "token": "abc"},
        )

        assert resp.status_code == 401
        magic.send.assert_not_called()


class TestSendOTP:
    def test_success(self):
        otp = MagicMock(spec=OTPNotifier)
        otp.send.return_value = True

        client = TestClient(_app(otp=otp))
        resp = client.post(
            "/send/otp",
            headers=_auth(),
            json={"to": "u@t.com", "user_name": "Kim", "code": "123456"},
        )

        assert resp.status_code == 200
        otp.send.assert_called_once_with("u@t.com", "Kim", "123456")

    def test_failure_returns_502(self):
        otp = MagicMock(spec=OTPNotifier)
        otp.send.return_value = False

        client = TestClient(_app(otp=otp))
        resp = client.post(
            "/send/otp",
            headers=_auth(),
            json={"to": "u@t.com", "user_name": "Kim", "code": "123456"},
        )

        assert resp.status_code == 502


class TestStartupValidation:
    def test_missing_smtp_env_raises(self, monkeypatch):
        for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "API_KEY"):
            monkeypatch.delenv(key, raising=False)

        with pytest.raises(RuntimeError, match="SMTP_HOST"):
            create_app()

    def test_missing_api_key_env_raises(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
        monkeypatch.setenv("SMTP_USER", "u@t.com")
        monkeypatch.setenv("SMTP_PASSWORD", "pw")
        monkeypatch.delenv("API_KEY", raising=False)

        with pytest.raises(RuntimeError, match="API_KEY"):
            create_app()
