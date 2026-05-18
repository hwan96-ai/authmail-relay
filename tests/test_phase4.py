"""Phase 4 tests: retry, test-mode capture, webhook delivery."""
from __future__ import annotations

import email
import smtplib
import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from email_service.sender import (
    SmtpConfig,
    SmtpSender,
    ERR_SMTP_CONNECTION,
    ERR_SMTP_TIMEOUT,
    ERR_SMTP_TRANSIENT,
    STATUS_CAPTURED,
    STATUS_DELIVERED,
    STATUS_FAILED,
    STATUS_PARTIAL,
)
from email_service import webhooks as webhooks_module
from email_service.webhooks import deliver_webhook, SIGNATURE_HEADER, _sign


def _mock_server(mock_smtp_cls):
    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server
    mock_server.__exit__.return_value = False
    mock_server.has_extn.return_value = True
    mock_server.sendmail.return_value = {}
    mock_smtp_cls.return_value = mock_server
    return mock_server


# ---------------------------------------------------------------------------
# 4.3 EMAIL_TEST_CAPTURE_DIR
# ---------------------------------------------------------------------------
def test_capture_writes_eml_and_skips_smtp(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_TEST_CAPTURE_DIR", str(tmp_path))
    sender = SmtpSender(SmtpConfig(
        host="smtp.test.com", port=587,
        user="t@t.com", password="pw",
    ))
    with patch("email_service.sender.smtplib.SMTP") as mock_smtp:
        result = sender.send("to@t.com", "subj", "<p>hi</p>")
        # SMTP should not have been touched.
        assert not mock_smtp.called
    assert result.sent is True
    assert result.status == STATUS_CAPTURED
    files = list(tmp_path.glob("*.eml"))
    assert len(files) == 1
    with open(files[0], "rb") as f:
        msg = email.message_from_bytes(f.read())
    assert msg["Subject"] == "subj"
    assert msg["To"] == "to@t.com"


def test_capture_dir_unset_uses_smtp(tmp_path, monkeypatch):
    monkeypatch.delenv("EMAIL_TEST_CAPTURE_DIR", raising=False)
    sender = SmtpSender(SmtpConfig(
        host="smtp.test.com", port=587,
        user="t@t.com", password="pw",
    ))
    with patch("email_service.sender.smtplib.SMTP") as mock_smtp:
        _mock_server(mock_smtp)
        result = sender.send("to@t.com", "subj", "<p>hi</p>")
    assert result.sent is True
    assert result.status == STATUS_DELIVERED


# ---------------------------------------------------------------------------
# 4.1 + 4.2 Retry with exponential backoff + metrics
# ---------------------------------------------------------------------------
def test_retry_succeeds_after_transient_timeout(monkeypatch):
    """A truly transient failure (timeout) still retries.

    Note: SMTPServerDisconnected mid-sendmail is now non-retriable to prevent
    double-send (P0-5). See ``test_disconnect_mid_sendmail_does_not_retry`` and
    ``test_disconnect_after_sendmail_treated_as_delivered`` below.
    """
    monkeypatch.delenv("EMAIL_TEST_CAPTURE_DIR", raising=False)
    sender = SmtpSender(
        SmtpConfig(host="smtp.test.com", port=587, user="t@t.com", password="pw"),
        max_retries=2,
        backoff_seconds=(0, 0, 0),
    )
    call_count = {"n": 0}

    def make_server(*args, **kwargs):
        call_count["n"] += 1
        server = MagicMock()
        server.__enter__.return_value = server
        server.__exit__.return_value = False
        server.has_extn.return_value = True
        if call_count["n"] == 1:
            # Transient I/O timeout — still retriable.
            server.sendmail.side_effect = TimeoutError("slow server")
        else:
            server.sendmail.return_value = {}
        return server

    with patch("email_service.sender.smtplib.SMTP", side_effect=make_server), \
         patch("email_service.sender.time.sleep") as mock_sleep:
        result = sender.send("to@t.com", "s", "<p>x</p>")
    assert result.sent is True
    assert result.attempts == 2
    assert result.status == STATUS_DELIVERED
    # Slept once between attempts.
    assert mock_sleep.call_count == 1


def test_retry_exhausts_and_fails(monkeypatch):
    monkeypatch.delenv("EMAIL_TEST_CAPTURE_DIR", raising=False)
    sender = SmtpSender(
        SmtpConfig(host="smtp.test.com", port=587, user="t@t.com", password="pw"),
        max_retries=2,
        backoff_seconds=(0, 0),
    )

    def make_server(*a, **k):
        s = MagicMock()
        s.__enter__.return_value = s
        s.__exit__.return_value = False
        s.has_extn.return_value = True
        s.sendmail.side_effect = socket.timeout("slow")
        return s

    with patch("email_service.sender.smtplib.SMTP", side_effect=make_server), \
         patch("email_service.sender.time.sleep"):
        result = sender.send("to@t.com", "s", "<p>x</p>")
    assert result.sent is False
    assert result.attempts == 3  # 1 initial + 2 retries
    assert result.error_code == ERR_SMTP_TIMEOUT
    assert result.status == STATUS_FAILED


def test_retry_on_4xx_smtp_response():
    sender = SmtpSender(
        SmtpConfig(host="smtp.test.com", port=587, user="t@t.com", password="pw"),
        max_retries=1,
        backoff_seconds=(0,),
    )
    counter = {"n": 0}

    def make_server(*a, **k):
        counter["n"] += 1
        s = MagicMock()
        s.__enter__.return_value = s
        s.__exit__.return_value = False
        s.has_extn.return_value = True
        if counter["n"] == 1:
            s.sendmail.side_effect = smtplib.SMTPResponseException(
                421, b"try again later"
            )
        else:
            s.sendmail.return_value = {}
        return s

    with patch("email_service.sender.smtplib.SMTP", side_effect=make_server), \
         patch("email_service.sender.time.sleep"):
        result = sender.send("to@t.com", "s", "<p>x</p>")
    assert result.sent is True
    assert result.attempts == 2


def test_no_retry_on_5xx_smtp_response():
    sender = SmtpSender(
        SmtpConfig(host="smtp.test.com", port=587, user="t@t.com", password="pw"),
        max_retries=3,
        backoff_seconds=(0, 0, 0),
    )
    counter = {"n": 0}

    def make_server(*a, **k):
        counter["n"] += 1
        s = MagicMock()
        s.__enter__.return_value = s
        s.__exit__.return_value = False
        s.has_extn.return_value = True
        s.sendmail.side_effect = smtplib.SMTPResponseException(
            550, b"permanent fail"
        )
        return s

    with patch("email_service.sender.smtplib.SMTP", side_effect=make_server), \
         patch("email_service.sender.time.sleep") as mock_sleep:
        result = sender.send("to@t.com", "s", "<p>x</p>")
    assert result.sent is False
    assert counter["n"] == 1  # No retry on 5xx
    assert mock_sleep.call_count == 0


def test_no_retry_on_partial_refusal():
    sender = SmtpSender(
        SmtpConfig(host="smtp.test.com", port=587, user="t@t.com", password="pw"),
        max_retries=3,
        backoff_seconds=(0, 0, 0),
    )
    counter = {"n": 0}

    def make_server(*a, **k):
        counter["n"] += 1
        s = MagicMock()
        s.__enter__.return_value = s
        s.__exit__.return_value = False
        s.has_extn.return_value = True
        s.sendmail.return_value = {"bad@t.com": (550, b"no such user")}
        return s

    with patch("email_service.sender.smtplib.SMTP", side_effect=make_server), \
         patch("email_service.sender.time.sleep"):
        result = sender.send(
            "to@t.com", "s", "<p>x</p>", bcc=["bad@t.com"]
        )
    assert result.sent is False
    assert result.status == STATUS_PARTIAL
    assert counter["n"] == 1  # Partial refusal never retries.


def test_message_id_stable_across_retries():
    """Message-ID does not regenerate on retry. Use a retriable failure
    (transient 421) — SMTPServerDisconnected is now non-retriable per P0-5."""
    sender = SmtpSender(
        SmtpConfig(host="smtp.test.com", port=587, user="t@t.com", password="pw"),
        max_retries=2,
        backoff_seconds=(0, 0),
    )
    seen_message_ids = []
    counter = {"n": 0}

    def make_server(*a, **k):
        counter["n"] += 1
        s = MagicMock()
        s.__enter__.return_value = s
        s.__exit__.return_value = False
        s.has_extn.return_value = True

        def capture_send(from_addr, recips, raw):
            msg = email.message_from_string(raw)
            seen_message_ids.append(msg["Message-ID"])
            if counter["n"] == 1:
                raise smtplib.SMTPResponseException(421, b"try again")
            return {}

        s.sendmail.side_effect = capture_send
        return s

    with patch("email_service.sender.smtplib.SMTP", side_effect=make_server), \
         patch("email_service.sender.time.sleep"):
        sender.send("to@t.com", "s", "<p>x</p>")
    assert len(seen_message_ids) == 2
    assert seen_message_ids[0] == seen_message_ids[1]


# ---------------------------------------------------------------------------
# 4.5/4.6/4.7 Webhook delivery
# ---------------------------------------------------------------------------
def test_deliver_webhook_success_first_try(monkeypatch):
    # P1 NEW-1: fetch-time SSRF re-validation runs. Allow fake 'hook' host.
    monkeypatch.setenv("WEBHOOK_ALLOW_HOSTS", "hook")
    transport = httpx.MockTransport(lambda req: httpx.Response(200))
    client = httpx.Client(transport=transport)
    payload = {"message_id": "<m1>", "status": "delivered"}
    ok = deliver_webhook("http://hook/x", payload, secret=None, client=client)
    assert ok is True


def test_deliver_webhook_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("WEBHOOK_ALLOW_HOSTS", "hook")
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    with patch("email_service.webhooks.time.sleep") as mock_sleep:
        ok = deliver_webhook(
            "http://hook/x",
            {"message_id": "<m>"},
            secret=None,
            client=client,
        )
    assert ok is True
    assert calls["n"] == 2
    assert mock_sleep.call_count == 1


def test_deliver_webhook_exhausts_retries(monkeypatch):
    monkeypatch.setenv("WEBHOOK_ALLOW_HOSTS", "hook")
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    client = httpx.Client(transport=transport)
    with patch("email_service.webhooks.time.sleep"):
        ok = deliver_webhook(
            "http://hook/x",
            {"message_id": "<m>"},
            secret=None,
            client=client,
            max_retries=3,
        )
    assert ok is False


def test_deliver_webhook_signs_with_hmac(monkeypatch):
    monkeypatch.setenv("WEBHOOK_ALLOW_HOSTS", "hook")
    received = {}

    def handler(req: httpx.Request) -> httpx.Response:
        received["headers"] = dict(req.headers)
        received["body"] = bytes(req.content)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    secret = "topsecret"
    ok = deliver_webhook(
        "http://hook/x",
        {"message_id": "<m>", "status": "delivered"},
        secret=secret,
        client=client,
    )
    assert ok is True
    sig = received["headers"].get(SIGNATURE_HEADER.lower())
    assert sig is not None
    expected = _sign(received["body"], secret)
    assert sig == expected


# ---------------------------------------------------------------------------
# 4.5 API endpoint webhook flow
# ---------------------------------------------------------------------------
def test_api_send_with_webhook_returns_accepted(monkeypatch):
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("SMTP_HOST", "smtp.t")
    from fastapi.testclient import TestClient
    from email_service.api import create_app
    from email_service.sender import SendResult as SR

    fake_sender = MagicMock()
    fake_sender.send.return_value = SR(
        sent=True, message_id="<m@h>", status="delivered"
    )

    captured = {}

    def fake_deliver(url, payload, secret, **kw):
        captured["url"] = url
        captured["payload"] = payload
        captured["secret"] = secret
        return True

    monkeypatch.setattr("email_service.api.deliver_webhook", fake_deliver)
    # P0-2: SSRF validator runs at Pydantic parse time. Allow 'hook' to bypass
    # DNS resolution for this test fixture.
    monkeypatch.setenv("WEBHOOK_ALLOW_HOSTS", "hook")
    app = create_app(sender=fake_sender, api_key="k")
    client = TestClient(app)
    resp = client.post(
        "/send",
        headers={"Authorization": "Bearer k"},
        json={
            "to": "u@t.com",
            "subject": "s",
            "html_body": "<p>x</p>",
            "webhook_url": "http://hook/x",
            "webhook_secret": "shh",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sent"] is False
    assert body["status"] == "accepted"
    # Background task should have run by now (TestClient runs tasks sync).
    assert captured["url"] == "http://hook/x"
    assert captured["secret"] == "shh"
    assert captured["payload"]["status"] == "delivered"
    assert captured["payload"]["message_id"] == "<m@h>"
