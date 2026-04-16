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

    def send(self, to: str, subject: str, html_body: str) -> bool:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._cfg.from_addr
        msg["To"] = to
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            server = smtplib.SMTP(self._cfg.host, self._cfg.port,
                                  timeout=self._cfg.timeout)
            if self._cfg.use_tls:
                server.starttls()
            if self._cfg.user and self._cfg.password:
                server.login(self._cfg.user, self._cfg.password)
            server.sendmail(self._cfg.from_addr, [to], msg.as_string())
            server.quit()
            logger.info("Email sent to %s", to)
            return True
        except Exception:
            logger.exception("Failed to send email to %s", to)
            return False
