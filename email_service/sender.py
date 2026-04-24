"""SMTP email sender — no project-specific dependencies."""
import logging
import smtplib
from dataclasses import dataclass
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)


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
    ) -> bool:
        for value in (self._cfg.from_addr, subject, to, *(cc or ()), *(bcc or ())):
            if "\r" in value or "\n" in value:
                logger.warning("Rejected email to %s: CRLF in header value", to)
                return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._cfg.from_addr
        msg["To"] = to
        if cc:
            msg["Cc"] = ", ".join(cc)

        # multipart/alternative: plain text must precede HTML so clients
        # without HTML support fall back correctly.
        if text_body is not None:
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        recipients = [to] + list(cc or []) + list(bcc or [])

        try:
            with smtplib.SMTP(self._cfg.host, self._cfg.port,
                              timeout=self._cfg.timeout) as server:
                if self._cfg.use_tls:
                    server.starttls()
                if self._cfg.user and self._cfg.password:
                    server.login(self._cfg.user, self._cfg.password)
                # sendmail returns a dict of refused recipients; non-empty means
                # partial delivery failure that would otherwise be silent.
                refused = server.sendmail(
                    self._cfg.from_addr, recipients, msg.as_string()
                )
            if refused:
                logger.warning(
                    "Email to %s partially refused: %s", to, sorted(refused)
                )
                return False
            logger.info("Email sent to %s", to)
            return True
        except Exception:
            logger.exception("Failed to send email to %s", to)
            return False
