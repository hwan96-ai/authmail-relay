"""Pattern: integration-test your code-paths that send email, without SMTP.

Set ``EMAIL_TEST_CAPTURE_DIR`` to any writable directory. The sender will
serialize each message to ``<message_id>.eml`` instead of opening an SMTP
connection. Your test can then parse the file and assert on subject, body,
headers, etc.

Run this file directly with pytest:

    pytest examples/integration_test_with_capture.py -v

or import the fixture into your own test suite.
"""
from __future__ import annotations

import email
import os
from pathlib import Path

import pytest

from authmail_relay.notifiers import MagicLinkNotifier
from authmail_relay.sender import SmtpConfig, SmtpSender


@pytest.fixture
def captured_mail_dir(tmp_path, monkeypatch):
    """Redirect all sends to disk for this test."""
    capture = tmp_path / "outbox"
    monkeypatch.setenv("EMAIL_TEST_CAPTURE_DIR", str(capture))
    yield capture


def _read_first_eml(capture_dir: Path):
    files = sorted(capture_dir.glob("*.eml"))
    assert files, f"No captured emails in {capture_dir}"
    with open(files[0], "rb") as f:
        return email.message_from_bytes(f.read())


def test_magic_link_capture(captured_mail_dir):
    # The SMTP host below is never contacted because capture mode is active.
    sender = SmtpSender(SmtpConfig(
        host="smtp.invalid", port=587,
        user="noreply@example.com", password="ignored",
    ))
    notifier = MagicLinkNotifier(sender, base_url="https://app.example.com/login")

    result = notifier.send("alice@example.com", "Alice", "abc123")

    assert result.sent is True
    assert result.status == "captured"

    msg = _read_first_eml(captured_mail_dir)
    assert msg["To"] == "alice@example.com"
    # Walk the parts and decode each one; the magic-link token must appear
    # somewhere in the HTML body.
    found = False
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            decoded = part.get_payload(decode=True).decode("utf-8")
            if "abc123" in decoded:
                found = True
                break
    assert found, "Token not found in HTML body of captured email"


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
