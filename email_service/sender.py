"""SMTP email sender — no project-specific dependencies."""
from __future__ import annotations

import logging
import os
import smtplib
import socket
import ssl
import time
from dataclasses import dataclass
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid

from email_service.logging_config import hash_recipient
from email_service.metrics import (
    email_send_active,
    email_send_duration_seconds,
    email_send_total,
)

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


def _debug_enabled() -> bool:
    return (
        os.environ.get("EMAIL_SERVICE_DEBUG", "0").strip().lower()
        in {"1", "true", "yes"}
    )


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


def _log_extra(
    to: str,
    *,
    message_id: str | None = None,
    duration_ms: float | None = None,
    error_code: str | None = None,
    request_id: str | None = None,
    refused: list[str] | None = None,
) -> dict:
    extra: dict = {"to_hash": hash_recipient(to)}
    if message_id is not None:
        extra["message_id"] = message_id
    if duration_ms is not None:
        extra["duration_ms"] = round(duration_ms, 2)
    if error_code is not None:
        extra["error_code"] = error_code
    if request_id is not None:
        extra["request_id"] = request_id
    if refused is not None:
        # Hash refused recipients too to avoid PII leakage.
        extra["refused_hashes"] = [hash_recipient(r) for r in refused]
    return extra


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
        request_id: str | None = None,
    ) -> SendResult:
        for value in (self._cfg.from_addr, subject, to, *(cc or ()), *(bcc or ())):
            if "\r" in value or "\n" in value:
                logger.warning(
                    "Rejected email: CRLF in header value",
                    extra=_log_extra(
                        to, error_code=ERR_CRLF_IN_HEADER, request_id=request_id
                    ),
                )
                email_send_total.labels(
                    result="failure", error_code=ERR_CRLF_IN_HEADER
                ).inc()
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

        start = time.perf_counter()
        email_send_active.inc()
        try:
            with smtplib.SMTP(self._cfg.host, self._cfg.port,
                              timeout=self._cfg.timeout) as server:
                # WARNING: smtplib's debug output is written to stderr and
                # includes AUTH lines containing the base64-encoded password.
                # Only enable EMAIL_SERVICE_DEBUG in development environments.
                if _debug_enabled():
                    server.set_debuglevel(1)
                if self._cfg.use_tls:
                    # Guard against a downgrade / STRIPTLS scenario: only call
                    # starttls() when the server advertises it. Otherwise we
                    # would silently send credentials over plaintext.
                    if not server.has_extn("starttls"):
                        logger.warning(
                            "SMTP server does not advertise STARTTLS; refusing to send",
                            extra=_log_extra(
                                to,
                                error_code=ERR_STARTTLS_UNSUPPORTED,
                                request_id=request_id,
                            ),
                        )
                        email_send_total.labels(
                            result="failure",
                            error_code=ERR_STARTTLS_UNSUPPORTED,
                        ).inc()
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
            duration_ms = (time.perf_counter() - start) * 1000.0
            email_send_duration_seconds.observe(duration_ms / 1000.0)
            if refused:
                refused_list = sorted(refused)
                logger.warning(
                    "Email partially refused",
                    extra=_log_extra(
                        to,
                        message_id=message_id,
                        duration_ms=duration_ms,
                        error_code=ERR_RECIPIENT_REFUSED,
                        request_id=request_id,
                        refused=refused_list,
                    ),
                )
                email_send_total.labels(
                    result="failure", error_code=ERR_RECIPIENT_REFUSED
                ).inc()
                return SendResult(
                    sent=False,
                    error_code=ERR_RECIPIENT_REFUSED,
                    error_message=f"Recipients refused: {refused_list}",
                    refused=refused_list,
                    message_id=message_id,
                )
            logger.info(
                "Email sent",
                extra=_log_extra(
                    to,
                    message_id=message_id,
                    duration_ms=duration_ms,
                    request_id=request_id,
                ),
            )
            email_send_total.labels(result="success", error_code="").inc()
            return SendResult(sent=True, message_id=message_id)
        except smtplib.SMTPAuthenticationError as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            logger.exception(
                "SMTP auth failed",
                extra=_log_extra(
                    to,
                    duration_ms=duration_ms,
                    error_code=ERR_SMTP_AUTH_FAILED,
                    request_id=request_id,
                ),
            )
            email_send_total.labels(
                result="failure", error_code=ERR_SMTP_AUTH_FAILED
            ).inc()
            return SendResult(
                sent=False,
                error_code=ERR_SMTP_AUTH_FAILED,
                error_message=str(exc),
            )
        except (smtplib.SMTPConnectError, socket.gaierror, ConnectionError) as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            logger.exception(
                "SMTP connection failed",
                extra=_log_extra(
                    to,
                    duration_ms=duration_ms,
                    error_code=ERR_SMTP_CONNECTION,
                    request_id=request_id,
                ),
            )
            email_send_total.labels(
                result="failure", error_code=ERR_SMTP_CONNECTION
            ).inc()
            return SendResult(
                sent=False,
                error_code=ERR_SMTP_CONNECTION,
                error_message=str(exc),
            )
        except (socket.timeout, TimeoutError) as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            logger.exception(
                "SMTP timeout",
                extra=_log_extra(
                    to,
                    duration_ms=duration_ms,
                    error_code=ERR_SMTP_TIMEOUT,
                    request_id=request_id,
                ),
            )
            email_send_total.labels(
                result="failure", error_code=ERR_SMTP_TIMEOUT
            ).inc()
            return SendResult(
                sent=False,
                error_code=ERR_SMTP_TIMEOUT,
                error_message=str(exc),
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            logger.exception(
                "Failed to send email",
                extra=_log_extra(
                    to,
                    duration_ms=duration_ms,
                    error_code=ERR_UNKNOWN,
                    request_id=request_id,
                ),
            )
            email_send_total.labels(
                result="failure", error_code=ERR_UNKNOWN
            ).inc()
            return SendResult(
                sent=False,
                error_code=ERR_UNKNOWN,
                error_message=str(exc),
            )
        finally:
            email_send_active.dec()
