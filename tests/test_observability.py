"""Tests for Phase 3 observability features (metrics, logging, request-id, debug)."""
from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from email_service.api import create_app
from email_service.logging_config import configure_logging, hash_recipient
from email_service.notifiers import OTPNotifier
from email_service.sender import SendResult, SmtpConfig, SmtpSender


API_KEY = "test-key"


def _app(sender=None):
    sender = sender or MagicMock()
    otp = MagicMock(spec=OTPNotifier)
    return create_app(sender=sender, api_key=API_KEY, magic_link=None, otp=otp)


def _auth():
    return {"Authorization": f"Bearer {API_KEY}"}


class TestHashRecipient:
    def test_consistent(self):
        assert hash_recipient("a@b.com") == hash_recipient("a@b.com")

    def test_different_inputs_differ(self):
        assert hash_recipient("a@b.com") != hash_recipient("c@d.com")

    def test_length_8(self):
        assert len(hash_recipient("anyone@anywhere.com")) == 8


class TestRequestIDPropagation:
    def test_echoes_client_supplied_header(self):
        sender = MagicMock()
        sender.send.return_value = SendResult(sent=True, message_id="<m@h>")
        client = TestClient(_app(sender=sender))
        resp = client.post(
            "/send",
            headers={**_auth(), "X-Request-ID": "trace-abc-123"},
            json={"to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"},
        )
        assert resp.status_code == 200
        assert resp.headers["X-Request-ID"] == "trace-abc-123"

    def test_generates_when_missing(self):
        sender = MagicMock()
        sender.send.return_value = SendResult(sent=True, message_id="<m@h>")
        client = TestClient(_app(sender=sender))
        resp = client.post(
            "/send",
            headers=_auth(),
            json={"to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("X-Request-ID")

    def test_passed_to_sender(self):
        sender = MagicMock()
        sender.send.return_value = SendResult(sent=True, message_id="<m@h>")
        client = TestClient(_app(sender=sender))
        client.post(
            "/send",
            headers={**_auth(), "X-Request-ID": "abc"},
            json={"to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"},
        )
        kwargs = sender.send.call_args.kwargs
        assert kwargs["request_id"] == "abc"


class TestMetricsEndpoint:
    def test_returns_404_when_disabled(self, monkeypatch):
        monkeypatch.delenv("METRICS_ENABLED", raising=False)
        # Reload metrics module so METRICS_ENABLED is re-evaluated.
        import email_service.metrics as m
        importlib.reload(m)
        client = TestClient(_app())
        resp = client.get("/metrics")
        assert resp.status_code == 404

    def test_returns_prometheus_when_enabled(self, monkeypatch):
        prom = pytest.importorskip("prometheus_client")  # noqa: F841
        monkeypatch.setenv("METRICS_ENABLED", "true")
        import email_service.metrics as m
        importlib.reload(m)
        # Reload sender too so it picks up the new metric objects.
        import email_service.sender as s
        importlib.reload(s)
        # Rebuild app *after* reload.
        sender = MagicMock()
        sender.send.return_value = s.SendResult(sent=True, message_id="<m@h>")
        app = create_app(
            sender=sender, api_key=API_KEY, magic_link=None,
            otp=MagicMock(spec=OTPNotifier),
        )
        client = TestClient(app)
        # Trigger a send to populate counter.
        client.post(
            "/send",
            headers=_auth(),
            json={"to": "u@t.com", "subject": "s", "html_body": "<p>x</p>"},
        )
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        # Reset for other tests.
        monkeypatch.delenv("METRICS_ENABLED", raising=False)
        importlib.reload(m)
        importlib.reload(s)


class TestDebugMode:
    def test_set_debuglevel_called_when_enabled(self, monkeypatch):
        monkeypatch.setenv("EMAIL_SERVICE_DEBUG", "1")
        cfg = SmtpConfig(
            host="smtp.test", port=587, user="u", password="p",
            from_addr="from@t.com", use_tls=False, timeout=5,
        )
        sender = SmtpSender(cfg)
        fake_server = MagicMock()
        fake_server.has_extn.return_value = True
        fake_server.sendmail.return_value = {}
        with patch("smtplib.SMTP") as smtp_cls:
            smtp_cls.return_value.__enter__.return_value = fake_server
            result = sender.send("to@t.com", "s", "<p>x</p>")
        assert result.sent is True
        fake_server.set_debuglevel.assert_called_once_with(1)

    def test_set_debuglevel_not_called_when_disabled(self, monkeypatch):
        monkeypatch.delenv("EMAIL_SERVICE_DEBUG", raising=False)
        cfg = SmtpConfig(
            host="smtp.test", port=587, user="u", password="p",
            from_addr="from@t.com", use_tls=False, timeout=5,
        )
        sender = SmtpSender(cfg)
        fake_server = MagicMock()
        fake_server.has_extn.return_value = True
        fake_server.sendmail.return_value = {}
        with patch("smtplib.SMTP") as smtp_cls:
            smtp_cls.return_value.__enter__.return_value = fake_server
            sender.send("to@t.com", "s", "<p>x</p>")
        fake_server.set_debuglevel.assert_not_called()


class TestPIISafeLogging:
    def test_logger_uses_to_hash_not_plain_recipient(self, monkeypatch, caplog):
        """Sender info log must include to_hash but not bare 'to' in message."""
        cfg = SmtpConfig(
            host="smtp.test", port=587, user="u", password="p",
            from_addr="from@t.com", use_tls=False, timeout=5,
        )
        sender = SmtpSender(cfg)
        fake_server = MagicMock()
        fake_server.has_extn.return_value = True
        fake_server.sendmail.return_value = {}
        recipient = "alice@example.com"
        with caplog.at_level(logging.INFO, logger="email_service.sender"):
            with patch("smtplib.SMTP") as smtp_cls:
                smtp_cls.return_value.__enter__.return_value = fake_server
                sender.send(recipient, "s", "<p>x</p>")
        # The success log message should be "Email sent" — not contain the
        # plain recipient address.
        msgs = [r.getMessage() for r in caplog.records]
        assert any("Email sent" in m for m in msgs)
        assert not any(recipient in m for m in msgs)


class TestConfigureLoggingNoop:
    def test_text_format_is_noop(self, monkeypatch):
        monkeypatch.delenv("EMAIL_SERVICE_LOG_FORMAT", raising=False)
        # Should not raise even if python-json-logger missing.
        configure_logging()
