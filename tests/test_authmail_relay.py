"""authmail-relay unit tests."""
import base64
import email
import ssl
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import smtplib
import socket

from authmail_relay.sender import (
    SendResult,
    SmtpSender,
    SmtpConfig,
    ERR_CRLF_IN_HEADER,
    ERR_RECIPIENT_REFUSED,
    ERR_SMTP_AUTH_FAILED,
    ERR_SMTP_CONNECTION,
    ERR_SMTP_TIMEOUT,
    ERR_STARTTLS_UNSUPPORTED,
    ERR_UNKNOWN,
)
from authmail_relay.notifiers import MagicLinkNotifier, OTPNotifier, TemplateNotifier


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
    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_send_success(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        result = sender.send("to@test.com", "Subject", "<p>body</p>")

        assert result.sent is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("test@test.com", "pw")
        mock_server.sendmail.assert_called_once()
        mock_server.__exit__.assert_called_once()

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_connection_closed_on_login_failure(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)
        mock_server.login.side_effect = RuntimeError("auth failed")

        sender = _make_sender()
        result = sender.send("to@test.com", "Subject", "<p>body</p>")

        assert result.sent is False
        mock_server.__exit__.assert_called_once()

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_send_failure(self, mock_smtp_cls):
        mock_smtp_cls.side_effect = ConnectionRefusedError("no server")

        sender = _make_sender()
        result = sender.send("to@test.com", "Subject", "<p>body</p>")

        assert result.sent is False

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_no_tls(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = SmtpSender(SmtpConfig(
            host="smtp.test.com", port=25,
            user="u", password="p", use_tls=False,
        ))
        sender.send("to@test.com", "Sub", "<p>b</p>")

        mock_server.starttls.assert_not_called()

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_no_auth(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = SmtpSender(SmtpConfig(
            host="smtp.test.com", port=25,
            user="", password="",
        ))
        sender.send("to@test.com", "Sub", "<p>b</p>")

        mock_server.login.assert_not_called()

    @patch("authmail_relay.sender.smtplib.SMTP")
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

    @patch("authmail_relay.sender.smtplib.SMTP")
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

    @patch("authmail_relay.sender.smtplib.SMTP")
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

    @patch("authmail_relay.sender.smtplib.SMTP")
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

        assert result.sent is False
        mock_server.sendmail.assert_called_once()

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_date_header_present(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        sender.send("to@test.com", "Sub", "<p>b</p>")

        raw = mock_server.sendmail.call_args[0][2]
        msg = email.message_from_string(raw)
        assert msg["Date"] is not None and msg["Date"] != ""

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_message_id_header_present(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        sender.send("to@test.com", "Sub", "<p>b</p>")

        raw = mock_server.sendmail.call_args[0][2]
        msg = email.message_from_string(raw)
        mid = msg["Message-ID"]
        # RFC 5322: Message-ID is angle-bracketed like "<...@host>"
        assert mid is not None
        assert mid.startswith("<") and mid.endswith(">")
        assert "@" in mid

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_starttls_uses_ssl_default_context(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)
        mock_server.has_extn.return_value = True

        sender = _make_sender()
        # Use bool() to verify SendResult.__bool__ backward-compat path.
        assert bool(sender.send("to@test.com", "Sub", "<p>b</p>")) is True

        mock_server.starttls.assert_called_once()
        kwargs = mock_server.starttls.call_args.kwargs
        assert "context" in kwargs
        assert isinstance(kwargs["context"], ssl.SSLContext)
        mock_server.sendmail.assert_called_once()

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_aborts_when_starttls_not_advertised(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)
        mock_server.has_extn.return_value = False

        sender = _make_sender()
        result = sender.send("to@test.com", "Sub", "<p>b</p>")

        assert result.sent is False
        mock_server.starttls.assert_not_called()
        mock_server.login.assert_not_called()
        mock_server.sendmail.assert_not_called()

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_rejects_crlf_in_headers(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()

        # bool(result) reflects result.sent — verifies backward-compat path.
        assert not sender.send("to@test.com", "Sub\r\nBcc: evil@test.com", "<p>b</p>")
        assert not sender.send("to@test.com\nBcc: evil@test.com", "Sub", "<p>b</p>")
        r1 = sender.send("to@test.com", "Sub", "<p>b</p>",
                         cc=["ok@test.com\r\nX: y"])
        assert r1.sent is False and r1.error_code == "crlf_in_header"
        assert not sender.send("to@test.com", "Sub", "<p>b</p>",
                               bcc=["ok@test.com\nX: y"])

        evil_sender = SmtpSender(SmtpConfig(
            host="smtp.test.com", port=587,
            user="test@test.com", password="pw",
            from_addr="ok@test.com\r\nBcc: evil@test.com",
        ))
        evil_result = evil_sender.send("to@test.com", "Sub", "<p>b</p>")
        assert evil_result.sent is False
        assert evil_result.error_code == "crlf_in_header"

        mock_server.sendmail.assert_not_called()


class TestMagicLinkNotifier:
    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_send_contains_link(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = MagicLinkNotifier(
            sender, base_url="https://app.example.com",
            subject_prefix="[MyApp] ",
        )
        result = notifier.send("user@test.com", "홍길동", "abc123token")

        assert result.sent is True
        html = _extract_html(mock_server)
        assert "https://app.example.com/set-password?token=abc123token" in html

    @patch("authmail_relay.sender.smtplib.SMTP")
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

    @patch("authmail_relay.sender.smtplib.SMTP")
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

    @patch("authmail_relay.sender.smtplib.SMTP")
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
    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_send_contains_code(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = OTPNotifier(sender, subject_prefix="[MyApp] ")
        result = notifier.send("user@test.com", "홍길동", "482901")

        assert result.sent is True
        html = _extract_html(mock_server)
        assert "482901" in html

    @patch("authmail_relay.sender.smtplib.SMTP")
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
    @patch("authmail_relay.sender.smtplib.SMTP")
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

        assert result.sent is True
        html = _extract_html(mock_server)
        assert "홍길동" in html
        assert "50000원" in html

        raw = mock_server.sendmail.call_args[0][2]
        msg = email.message_from_string(raw)
        decoded = str(email.header.make_header(email.header.decode_header(msg["Subject"])))
        assert decoded == "[Shop] 주문 1234 확인"

    @patch("authmail_relay.sender.smtplib.SMTP")
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

    @patch("authmail_relay.sender.smtplib.SMTP")
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

    @patch("authmail_relay.sender.smtplib.SMTP")
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

    @patch("authmail_relay.sender.smtplib.SMTP")
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


class TestMagicLinkPlainText:
    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_plain_text_alternative_attached(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = MagicLinkNotifier(
            sender, base_url="https://app.example.com",
        )
        notifier.send("user@test.com", "홍길동", "tok123")

        raw = mock_server.sendmail.call_args[0][2]
        msg = email.message_from_string(raw)
        plain = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
        body = base64.b64decode(plain.get_payload()).decode("utf-8")
        assert "홍길동" in body
        assert "https://app.example.com/set-password?token=tok123" in body


class TestOTPPlainText:
    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_plain_text_alternative_attached(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = OTPNotifier(sender)
        notifier.send("user@test.com", "홍길동", "482901")

        raw = mock_server.sendmail.call_args[0][2]
        msg = email.message_from_string(raw)
        plain = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
        body = base64.b64decode(plain.get_payload()).decode("utf-8")
        assert "홍길동" in body
        assert "482901" in body


class TestNotifierI18n:
    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_magic_link_custom_subject_and_template(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = MagicLinkNotifier(
            sender,
            base_url="https://app.example.com",
            subject="Set your password",
            html_template="<p>Hello {name}, link: {link} (expires in {expire}m)</p>",
            text_template="Hello {name}, link: {link} ({expire}m)",
        )
        notifier.send("user@test.com", "Alice", "tokABC")

        raw = mock_server.sendmail.call_args[0][2]
        msg = email.message_from_string(raw)
        decoded = str(email.header.make_header(email.header.decode_header(msg["Subject"])))
        assert decoded == "Set your password"

        html = _extract_html(mock_server)
        assert "Hello Alice" in html
        assert "/set-password?token=tokABC" in html

        plain = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
        text = base64.b64decode(plain.get_payload()).decode("utf-8")
        assert "Hello Alice" in text

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_otp_custom_subject_and_template(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = OTPNotifier(
            sender,
            subject="Your code",
            html_template="<p>Hi {name}, code: {payload}, expires {expire}m</p>",
        )
        notifier.send("user@test.com", "Bob", "999111")

        raw = mock_server.sendmail.call_args[0][2]
        msg = email.message_from_string(raw)
        decoded = str(email.header.make_header(email.header.decode_header(msg["Subject"])))
        assert decoded == "Your code"

        html = _extract_html(mock_server)
        assert "Hi Bob" in html
        assert "999111" in html


class TestTemplateNotifierNoAutoescape:
    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_autoescape_false_passes_raw_html(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = TemplateNotifier(
            sender,
            subject="raw test",
            html_template="<div>{snippet}</div>",
            autoescape=False,
        )
        notifier.send("user@test.com", snippet="<script>x</script>")

        html = _extract_html(mock_server)
        # autoescape=False — raw is passed through unescaped
        assert "<script>x</script>" in html
        assert "&lt;script&gt;" not in html

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_autoescape_true_escapes_same_value(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)

        sender = _make_sender()
        notifier = TemplateNotifier(
            sender,
            subject="escaped test",
            html_template="<div>{snippet}</div>",
            autoescape=True,
        )
        notifier.send("user@test.com", snippet="<script>x</script>")

        html = _extract_html(mock_server)
        assert "&lt;script&gt;x&lt;/script&gt;" in html
        assert "<script>x</script>" not in html


class TestSendResult:
    """Verify structured error codes for each failure mode."""

    def test_bool_protocol_true(self):
        assert bool(SendResult(sent=True)) is True
        assert SendResult(sent=True)  # if-truthy path

    def test_bool_protocol_false(self):
        assert bool(SendResult(sent=False, error_code="x")) is False
        assert not SendResult(sent=False, error_code="x")

    def test_message_id_captured_on_success(self):
        with patch("authmail_relay.sender.smtplib.SMTP") as cls:
            _mock_server(cls)
            result = _make_sender().send("to@test.com", "s", "<p>x</p>")
        assert result.sent is True
        assert result.message_id is not None
        assert result.message_id.startswith("<") and result.message_id.endswith(">")

    def test_crlf_error_code(self):
        result = _make_sender().send("to@test.com", "s\r\nX: y", "<p>x</p>")
        assert result.sent is False
        assert result.error_code == ERR_CRLF_IN_HEADER

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_auth_failed_error_code(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"auth failed"
        )
        result = _make_sender().send("to@test.com", "s", "<p>x</p>")
        assert result.sent is False
        assert result.error_code == ERR_SMTP_AUTH_FAILED

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_connection_error_code(self, mock_smtp_cls):
        mock_smtp_cls.side_effect = socket.gaierror("name resolution")
        result = _make_sender().send("to@test.com", "s", "<p>x</p>")
        assert result.sent is False
        assert result.error_code == ERR_SMTP_CONNECTION

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_timeout_error_code(self, mock_smtp_cls):
        mock_smtp_cls.side_effect = socket.timeout("timed out")
        result = _make_sender().send("to@test.com", "s", "<p>x</p>")
        assert result.sent is False
        assert result.error_code == ERR_SMTP_TIMEOUT

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_recipient_refused_error_code(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)
        mock_server.sendmail.return_value = {"bad@test.com": (550, b"nope")}
        result = _make_sender().send(
            "to@test.com", "s", "<p>x</p>", cc=["bad@test.com"]
        )
        assert result.sent is False
        assert result.error_code == ERR_RECIPIENT_REFUSED
        assert result.refused == ["bad@test.com"]

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_starttls_unsupported_error_code(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)
        mock_server.has_extn.return_value = False
        result = _make_sender().send("to@test.com", "s", "<p>x</p>")
        assert result.sent is False
        assert result.error_code == ERR_STARTTLS_UNSUPPORTED

    @patch("authmail_relay.sender.smtplib.SMTP")
    def test_unknown_error_code_for_generic_exception(self, mock_smtp_cls):
        mock_server = _mock_server(mock_smtp_cls)
        mock_server.sendmail.side_effect = RuntimeError("???")
        result = _make_sender().send("to@test.com", "s", "<p>x</p>")
        assert result.sent is False
        assert result.error_code == ERR_UNKNOWN
