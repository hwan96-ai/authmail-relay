"""email-service unit tests."""
import base64
import email
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from email_service.sender import SmtpSender, SmtpConfig
from email_service.notifiers import MagicLinkNotifier, OTPNotifier, TemplateNotifier


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


def _mock_server(mock_smtp_cls):
    """Configure MagicMock to return itself from the SMTP context manager."""
    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server
    # smtplib.SMTP.sendmail returns {} when all recipients accepted.
    mock_server.sendmail.return_value = {}
    mock_smtp_cls.return_value = mock_server
    return mock_server


class TestSmtpSender:
    @patch("email_service.sender.smtplib.SMTP")
    def test_send_success(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        result = sender.send("to@test.com", "Subject", "<p>body</p>")

        assert result is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("test@test.com", "pw")
        mock_server.sendmail.assert_called_once()
        mock_server.__exit__.assert_called_once()

    @patch("email_service.sender.smtplib.SMTP")
    def test_connection_closed_on_login_failure(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)
        mock_server.login.side_effect = RuntimeError("auth failed")

        sender = _make_sender()
        result = sender.send("to@test.com", "Subject", "<p>body</p>")

        assert result is False
        mock_server.__exit__.assert_called_once()

    @patch("email_service.sender.smtplib.SMTP")
    def test_send_failure(self, mock_smtp_cls):
        mock_smtp_cls.side_effect = ConnectionRefusedError("no server")

        sender = _make_sender()
        result = sender.send("to@test.com", "Subject", "<p>body</p>")

        assert result is False

    @patch("email_service.sender.smtplib.SMTP")
    def test_no_tls(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = SmtpSender(SmtpConfig(
            host="smtp.test.com", port=25,
            user="u", password="p", use_tls=False,
        ))
        sender.send("to@test.com", "Sub", "<p>b</p>")

        mock_server.starttls.assert_not_called()

    @patch("email_service.sender.smtplib.SMTP")
    def test_no_auth(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = SmtpSender(SmtpConfig(
            host="smtp.test.com", port=25,
            user="", password="",
        ))
        sender.send("to@test.com", "Sub", "<p>b</p>")

        mock_server.login.assert_not_called()

    @patch("email_service.sender.smtplib.SMTP")
    def test_text_body_attached(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        sender.send(
            "to@test.com", "Sub", "<p>html</p>",
            text_body="plain fallback",
        )

        raw = mock_server.sendmail.call_args[0][2]
        msg = email.message_from_string(raw)
        parts = {p.get_content_type(): p for p in msg.walk() if p.get_content_type().startswith("text/")}
        assert "text/plain" in parts and "text/html" in parts
        plain = base64.b64decode(parts["text/plain"].get_payload()).decode("utf-8")
        assert plain == "plain fallback"

    @patch("email_service.sender.smtplib.SMTP")
    def test_cc_in_header_and_recipients(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        sender.send(
            "to@test.com", "Sub", "<p>b</p>",
            cc=["cc1@test.com", "cc2@test.com"],
        )

        from_addr, recipients, raw = mock_server.sendmail.call_args[0]
        assert recipients == ["to@test.com", "cc1@test.com", "cc2@test.com"]
        msg = email.message_from_string(raw)
        assert msg["Cc"] == "cc1@test.com, cc2@test.com"

    @patch("email_service.sender.smtplib.SMTP")
    def test_bcc_in_recipients_not_header(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        sender.send(
            "to@test.com", "Sub", "<p>b</p>",
            bcc=["bcc@test.com"],
        )

        from_addr, recipients, raw = mock_server.sendmail.call_args[0]
        assert recipients == ["to@test.com", "bcc@test.com"]
        msg = email.message_from_string(raw)
        assert msg["Bcc"] is None

    @patch("email_service.sender.smtplib.SMTP")
    def test_returns_false_on_partial_recipient_refusal(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)
        # smtplib.SMTP.sendmail returns {recipient: (code, msg)} for refused recipients.
        mock_server.sendmail.return_value = {
            "bad@test.com": (550, b"User unknown"),
        }

        sender = _make_sender()
        result = sender.send(
            "to@test.com", "Sub", "<p>b</p>",
            cc=["bad@test.com"],
        )

        assert result is False
        mock_server.sendmail.assert_called_once()

    @patch("email_service.sender.smtplib.SMTP")
    def test_rejects_crlf_in_headers(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()

        assert sender.send("to@test.com", "Sub\r\nBcc: evil@test.com", "<p>b</p>") is False
        assert sender.send("to@test.com\nBcc: evil@test.com", "Sub", "<p>b</p>") is False
        assert sender.send("to@test.com", "Sub", "<p>b</p>",
                           cc=["ok@test.com\r\nX: y"]) is False
        assert sender.send("to@test.com", "Sub", "<p>b</p>",
                           bcc=["ok@test.com\nX: y"]) is False

        evil_sender = SmtpSender(SmtpConfig(
            host="smtp.test.com", port=587,
            user="test@test.com", password="pw",
            from_addr="ok@test.com\r\nBcc: evil@test.com",
        ))
        assert evil_sender.send("to@test.com", "Sub", "<p>b</p>") is False

        mock_server.sendmail.assert_not_called()


class TestMagicLinkNotifier:
    @patch("email_service.sender.smtplib.SMTP")
    def test_send_contains_link(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

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
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = MagicLinkNotifier(
            sender, base_url="https://app.example.com",
            path="/reset",
        )
        notifier.send("user@test.com", "테스트", "tok")

        html = _extract_html(mock_server)
        assert "/reset?token=tok" in html

    @patch("email_service.sender.smtplib.SMTP")
    def test_token_url_encoded(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = MagicLinkNotifier(
            sender, base_url="https://app.example.com",
        )
        notifier.send("user@test.com", "홍길동", "a+b&c=d/==")

        html = _extract_html(mock_server)
        assert "token=a%2Bb%26c%3Dd%2F%3D%3D" in html
        assert "a+b&c=d/==" not in html

    @patch("email_service.sender.smtplib.SMTP")
    def test_user_name_html_escaped(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = MagicLinkNotifier(
            sender, base_url="https://app.example.com",
        )
        notifier.send("user@test.com", "<b>홍길동</b>", "tok")

        html = _extract_html(mock_server)
        assert "&lt;b&gt;홍길동&lt;/b&gt;" in html
        assert "<b>홍길동</b>" not in html


class TestOTPNotifier:
    @patch("email_service.sender.smtplib.SMTP")
    def test_send_contains_code(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = OTPNotifier(sender, subject_prefix="[MyApp] ")
        result = notifier.send("user@test.com", "홍길동", "482901")

        assert result is True
        html = _extract_html(mock_server)
        assert "482901" in html

    @patch("email_service.sender.smtplib.SMTP")
    def test_user_name_and_payload_escaped(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = OTPNotifier(sender)
        notifier.send("user@test.com", "<b>홍길동</b>", "<script>alert(1)</script>")

        html = _extract_html(mock_server)
        assert "&lt;b&gt;홍길동&lt;/b&gt;" in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "<script>" not in html
        assert "<b>홍길동</b>" not in html


class TestTemplateNotifier:
    @patch("email_service.sender.smtplib.SMTP")
    def test_renders_context(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = TemplateNotifier(
            sender,
            subject="[Shop] 주문 {order_id} 확인",
            html_template="<p>{name}님, 합계 {total}원입니다.</p>",
        )
        result = notifier.send(
            "user@test.com",
            name="홍길동", order_id="1234", total="50000",
        )

        assert result is True
        html = _extract_html(mock_server)
        assert "홍길동" in html
        assert "50000원" in html

        raw = mock_server.sendmail.call_args[0][2]
        msg = email.message_from_string(raw)
        decoded = str(email.header.make_header(email.header.decode_header(msg["Subject"])))
        assert decoded == "[Shop] 주문 1234 확인"

    @patch("email_service.sender.smtplib.SMTP")
    def test_missing_context_raises(self, mock_smtp_cls):
        sender = _make_sender()
        notifier = TemplateNotifier(
            sender,
            subject="hi {name}",
            html_template="<p>{name}</p>",
        )
        try:
            notifier.send("user@test.com")
        except KeyError:
            pass
        else:
            assert False, "expected KeyError for missing template key"

    @patch("email_service.sender.smtplib.SMTP")
    def test_text_template_attached(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = TemplateNotifier(
            sender,
            subject="hi {name}",
            html_template="<p>{name}</p>",
            text_template="hello {name}",
        )
        notifier.send("user@test.com", name="Alice")

        raw = mock_server.sendmail.call_args[0][2]
        msg = email.message_from_string(raw)
        plain = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
        assert base64.b64decode(plain.get_payload()).decode("utf-8") == "hello Alice"

    @patch("email_service.sender.smtplib.SMTP")
    def test_autoescape_on_by_default(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = TemplateNotifier(
            sender,
            subject="hi",
            html_template="<p>{name}</p>",
        )
        notifier.send("user@test.com", name="<b>x</b>")

        html = _extract_html(mock_server)
        assert "&lt;b&gt;x&lt;/b&gt;" in html
        assert "<b>x</b>" not in html

    @patch("email_service.sender.smtplib.SMTP")
    def test_autoescape_escapes_html_body_only(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = TemplateNotifier(
            sender,
            subject="order {name}",
            html_template="<p>{name}</p>",
            text_template="order {name}",
            autoescape=True,
        )
        notifier.send("user@test.com", name="<script>x</script>")

        html = _extract_html(mock_server)
        assert "&lt;script&gt;" in html
        assert "<script>" not in html

        raw = mock_server.sendmail.call_args[0][2]
        msg = email.message_from_string(raw)
        # subject and text body are NOT escaped — they aren't HTML contexts
        decoded = str(email.header.make_header(email.header.decode_header(msg["Subject"])))
        assert decoded == "order <script>x</script>"
        plain = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
        assert base64.b64decode(plain.get_payload()).decode("utf-8") == "order <script>x</script>"
