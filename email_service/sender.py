"""SMTP email sender — no project-specific dependencies."""
import logging
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid

logger = logging.getLogger(__name__)


# Structured error codes returned in SendResult.error_code.
ERR_CRLF_IN_HEADER = "crlf_in_header"
ERR_SMTP_AUTH_FAILED = "smtp_auth_failed"
ERR_SMTP_CONNECTION = "smtp_connection"
ERR_SMTP_TIMEOUT = "smtp_timeout"
ERR_RECIPIENT_REFUSED = "recipient_refused"
ERR_STARTTLS_UNSUPPORTED = "starttls_unsupported"
ERR_TEMPLATE_NOT_CONFIGURED = "template_not_configured"
ERR_UNKNOWN = "unknown"


@dataclass(frozen=True)
class SendResult:
    """Structured result of a send attempt.

    `bool(result)` returns `result.sent`, so legacy `if sender.send(...):`
    callers keep working unchanged.
    """
    sent: bool
    error_code: str | None = None
    error_message: str | None = None
    refused: list[str] | None = None
    message_id: str | None = None

    def __bool__(self) -> bool:
        return self.sent


@dataclass
class SmtpConfig:
    host: str = "smtp.gmail.com"
    port: int = 587
    user: str = ""
    password: str = ""
    from_addr: str = ""
    use_tls: bool = True
    timeout: int = 10

    def __post_init__(self):
        if not self.from_addr:
            self.from_addr = self.user


class SmtpSender:
    """Send HTML emails via SMTP. Reusable across projects."""

    def __init__(self, config: SmtpConfig):
        self._cfg = config

    def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        *,
        text_body: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> SendResult:
        for value in (self._cfg.from_addr, subject, to, *(cc or ()), *(bcc or ())):
            if "\r" in value or "\n" in value:
                logger.warning("Rejected email to %s: CRLF in header value", to)
                return SendResult(
                    sent=False,
                    error_code=ERR_CRLF_IN_HEADER,
                    error_message="CRLF characters are not allowed in header values",
                )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._cfg.from_addr
        msg["To"] = to
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()
        if cc:
            msg["Cc"] = ", ".join(cc)

        # multipart/alternative: plain text must precede HTML so clients
        # without HTML support fall back correctly.
        if text_body is not None:
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        recipients = [to] + list(cc or []) + list(bcc or [])
        message_id = msg["Message-ID"]

        try:
            with smtplib.SMTP(self._cfg.host, self._cfg.port,
                              timeout=self._cfg.timeout) as server:
                if self._cfg.use_tls:
                    # Guard against a downgrade / STRIPTLS scenario: only call
                    # starttls() when the server advertises it. Otherwise we
                    # would silently send credentials over plaintext.
                    if not server.has_extn("starttls"):
                        logger.warning(
                            "SMTP server %s does not advertise STARTTLS; "
                            "refusing to send email to %s",
                            self._cfg.host, to,
                        )
                        return SendResult(
                            sent=False,
                            error_code=ERR_STARTTLS_UNSUPPORTED,
                            error_message=(
                                f"SMTP server {self._cfg.host} does not "
                                "advertise STARTTLS"
                            ),
                        )
                    server.starttls(context=ssl.create_default_context())
                if self._cfg.user and self._cfg.password:
                    server.login(self._cfg.user, self._cfg.password)
                # sendmail returns a dict of refused recipients; non-empty means
                # partial delivery failure that would otherwise be silent.
                refused = server.sendmail(
                    self._cfg.from_addr, recipients, msg.as_string()
                )
            if refused:
                refused_list = sorted(refused)
                logger.warning(
                    "Email to %s partially refused: %s", to, refused_list
                )
                return SendResult(
                    sent=False,
                    error_code=ERR_RECIPIENT_REFUSED,
                    error_message=f"Recipients refused: {refused_list}",
                    refused=refused_list,
                    message_id=message_id,
                )
            logger.info("Email sent to %s", to)
            return SendResult(sent=True, message_id=message_id)
        except smtplib.SMTPAuthenticationError as exc:
            logger.exception("SMTP auth failed for %s", to)
            return SendResult(
                sent=False,
                error_code=ERR_SMTP_AUTH_FAILED,
                error_message=str(exc),
            )
        except (smtplib.SMTPConnectError, socket.gaierror, ConnectionError) as exc:
            logger.exception("SMTP connection failed sending to %s", to)
            return SendResult(
                sent=False,
                error_code=ERR_SMTP_CONNECTION,
                error_message=str(exc),
            )
        except (socket.timeout, TimeoutError) as exc:
            logger.exception("SMTP timeout sending to %s", to)
            return SendResult(
                sent=False,
                error_code=ERR_SMTP_TIMEOUT,
                error_message=str(exc),
            )
        except Exception as exc:
            logger.exception("Failed to send email to %s", to)
            return SendResult(
                sent=False,
                error_code=ERR_UNKNOWN,
                error_message=str(exc),
            )
