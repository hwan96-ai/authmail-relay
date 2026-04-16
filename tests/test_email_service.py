"""email-service unit tests."""
import base64
import email
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from email_service.sender import SmtpSender, SmtpConfig
from email_service.notifiers import MagicLinkNotifier, OTPNotifier


def _make_sender():
    return SmtpSender(SmtpConfig(
        host="smtp.test.com", port=587,
        user="test@test.com", password="pw",
    ))


def _extract_html(mock_server) -> str:
    """Extract decoded HTML body from the mock sendmail call."""
    raw = mock_server.sendmail.call_args[0][2]
    msg = email.message_from_string(raw)
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload()
            return base64.b64decode(payload).decode("utf-8")
    return raw


class TestSmtpSender:
    @patch("email_service.sender.smtplib.SMTP")
    def test_send_success(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        sender = _make_sender()
        result = sender.send("to@test.com", "Subject", "<p>body</p>")

        assert result is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("test@test.com", "pw")
        mock_server.sendmail.assert_called_once()
        mock_server.quit.assert_called_once()

    @patch("email_service.sender.smtplib.SMTP")
    def test_send_failure(self, mock_smtp_cls):
        mock_smtp_cls.side_effect = ConnectionRefusedError("no server")

        sender = _make_sender()
        result = sender.send("to@test.com", "Subject", "<p>body</p>")

        assert result is False

    @patch("email_service.sender.smtplib.SMTP")
    def test_no_tls(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        sender = SmtpSender(SmtpConfig(
            host="smtp.test.com", port=25,
            user="u", password="p", use_tls=False,
        ))
        sender.send("to@test.com", "Sub", "<p>b</p>")

        mock_server.starttls.assert_not_called()

    @patch("email_service.sender.smtplib.SMTP")
    def test_no_auth(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        sender = SmtpSender(SmtpConfig(
            host="smtp.test.com", port=25,
            user="", password="",
        ))
        sender.send("to@test.com", "Sub", "<p>b</p>")

        mock_server.login.assert_not_called()


class TestMagicLinkNotifier:
    @patch("email_service.sender.smtplib.SMTP")
    def test_send_contains_link(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        sender = _make_sender()
        notifier = MagicLinkNotifier(
            sender, base_url="https://app.example.com",
            subject_prefix="[MyApp] ",
        )
        result = notifier.send("user@test.com", "홍길동", "abc123token")

        assert result is True
        html = _extract_html(mock_server)
        assert "https://app.example.com/set-password?token=abc123token" in html

    @patch("email_service.sender.smtplib.SMTP")
    def test_custom_path(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        sender = _make_sender()
        notifier = MagicLinkNotifier(
            sender, base_url="https://app.example.com",
            path="/reset",
        )
        notifier.send("user@test.com", "테스트", "tok")

        html = _extract_html(mock_server)
        assert "/reset?token=tok" in html


class TestOTPNotifier:
    @patch("email_service.sender.smtplib.SMTP")
    def test_send_contains_code(self, mock_smtp_cls):
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        sender = _make_sender()
        notifier = OTPNotifier(sender, subject_prefix="[MyApp] ")
        result = notifier.send("user@test.com", "홍길동", "482901")

        assert result is True
        html = _extract_html(mock_server)
        assert "482901" in html
